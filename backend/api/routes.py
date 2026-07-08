"""
api/routes.py — REST API endpoints

Provides endpoints for:
- Manual PR analysis triggers
- Job status checking
- Analysis result retrieval
- Cache statistics
"""

from __future__ import annotations
import asyncio
import json
import os
import uuid

import boto3
from fastapi import APIRouter, HTTPException

from api.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    JobStatusResponse,
    AnalysisResultResponse,
    FunctionAnalysisSummary,
    CacheStatsResponse,
    JobListResponse,
    JobStatus,
    OpenPullRequestSummary,
    OpenPullRequestsResponse
)
from github_utils.client import GitHubClient
from cache.redis import (
    enqueue_job,
    get_job_status,
    get_job_result,
    get_cache_stats,
    list_jobs,
    update_job_status,
)
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Constructed once at module level - boto3 clients are thread-safe and cheap to reuse.
# The function name follows Serverless Framework's naming convention:
#   {service}-{stage}-{function_key}
# Read from env so it can be overridden without a redeploy (staging vs prod).
_WORKER_FUNCTION_NAME = os.environ.get(
    "WORKER_FUNCTION_NAME",
    "c-code-review-dev-worker",
)
_lambda_client = boto3.client(
    "lambda",
    region_name=os.environ.get("AWS_REGION", "ap-southeast-1"),
)

# In local dev there's no deployed worker Lambda to invoke. Set
# WORKER_MODE=local (see backend/.env) to run the same pipeline in-process
# instead, as a plain asyncio task on the API server's own event loop.
_LOCAL_WORKER = os.environ.get("WORKER_MODE", "lambda").strip().lower() == "local"


router = APIRouter(tags=["api"])

# Reused across requests — same rationale as the boto3 client above: cheap to
# construct, and PyGithub instances don't hold per-request state we need to
# isolate. Auth (PAT vs GitHub App installation token) is resolved per-call.
_github_client = GitHubClient()

@router.get("/repos/{owner}/{repo}/pulls", response_model=OpenPullRequestsResponse)
async def list_open_pull_requests(
    owner: str,
    repo: str,
    installation_id: Optional[int] = None,
):
    """
    List open pull requests for a repo, for the dashboard's PR picker.
 
    Lets the frontend show a searchable list (by number, title, or author)
    once the user enters an owner/repo, instead of requiring them to already
    know the PR number.
    """
    pulls = await _github_client.list_open_pull_requests(
        owner=owner,
        repo=repo,
        installation_id=installation_id,
    )
 
    if pulls is None:
        raise HTTPException(
            status_code=404,
            detail=f"Couldn't fetch open pull requests for {owner}/{repo}. "
                    "Check the owner/repo name and that the repo is accessible.",
        )
 
    return OpenPullRequestsResponse(
        owner=owner,
        repo=repo,
        pull_requests=[OpenPullRequestSummary(**pr) for pr in pulls],
    )


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_pr(request: AnalyzeRequest):
    """
    Trigger analysis of a PR.

    Enqueues the job in Redis (fast), then fires off the worker Lambda
    asynchronously (InvocationType='Event') and returns the job ID immediately.
    The entire handler completes well within API Gateway's 30s hard limit.
    The worker Lambda runs independently with a 900s timeout and writes its
    result back to Redis. The frontend polls /api/status/{job_id} as before.
    """
    job_id = f"manual-{request.owner}-{request.repo}-{request.pr_number}-{uuid.uuid4().hex[:8]}"
    logger.info(f"Analyze request received for job: {job_id}")

    job_data = {
        "owner": request.owner,
        "repo": request.repo,
        "pr_number": request.pr_number,
        "action": "manual",
        "installation_id": request.installation_id,
        "post_comment": request.post_comment,
    }

    success = await enqueue_job(job_id, job_data)
    logger.info(f"enqueue: {success}")
    if not success:
        logger.error(f"Failed to enqueue job: {job_id}")
        raise HTTPException(
            status_code=503,
            detail="Failed to queue job. Redis may be unavailable.",
        )

    if _LOCAL_WORKER:
        # Local dev: no Lambda to invoke. Run the pipeline in-process as a
        # detached asyncio task so this endpoint still returns immediately;
        # the frontend polls /api/status/{job_id} exactly as in production.
        from github_utils.webhook import process_pr_job

        async def _run_local() -> None:
            try:
                await process_pr_job(
                    job_id=job_id,
                    owner=request.owner,
                    repo_name=request.repo,
                    pr_number=request.pr_number,
                    installation_id=request.installation_id,
                    post_comment=request.post_comment,
                )
            except Exception as e:
                # process_pr_job normally catches its own errors and marks the
                # job "failed", but a crash before/outside that try block (e.g.
                # the initial update_job_status call itself failing) would
                # otherwise leave the job stuck at "pending" forever.
                logger.exception(f"Local worker task crashed for job {job_id}")
                await update_job_status(job_id, "failed", {"error": str(e)})

        asyncio.create_task(_run_local())
        logger.info(f"Running worker in-process (WORKER_MODE=local) for job {job_id}")
        return AnalyzeResponse(
            job_id=job_id,
            status=JobStatus.PENDING,
            message=f"Analysis started (local worker) for {request.owner}/{request.repo}/{request.pr_number}",
        )

    # boto3.invoke is synchronous — run it in a thread so we don't block the
    # asyncio event loop. InvocationType='Event' means fire-and-forget: AWS
    # queues the invocation and returns HTTP 202 in ~100-200ms without waiting
    # for the worker to finish.
    payload = json.dumps({
        "job_id": job_id,
        "owner": request.owner,
        "repo_name": request.repo,
        "pr_number": request.pr_number,
        "installation_id": request.installation_id,
        "post_comment": request.post_comment,
    })

    try:
        response = await asyncio.to_thread(
            _lambda_client.invoke,
            FunctionName=_WORKER_FUNCTION_NAME,
            InvocationType="Event",
            Payload=payload,
        )
        status_code = response.get("StatusCode")
        # 202 Accepted is the success code for async Lambda invocation
        if status_code != 202:
            raise RuntimeError(f"Unexpected Lambda invoke status: {status_code}")
        logger.info(f"Worker Lambda invoked for job {job_id}, status {status_code}")
    except Exception as e:
        # Worker invocation failed — job is enqueued in Redis but won't run.
        # Mark it failed immediately so it doesn't sit at "pending" forever,
        # then return 500 so the client knows something went wrong rather
        # than polling indefinitely on a job that will never complete.
        logger.exception(f"Failed to invoke worker Lambda for job {job_id}")
        await update_job_status(job_id, "failed", {"error": f"Failed to start analysis worker: {e}"})
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start analysis worker: {e}",
        )

    return AnalyzeResponse(
        job_id=job_id,
        status=JobStatus.PENDING,
        message=f"Analysis started for {request.owner}/{request.repo}/{request.pr_number}",
    )


@router.get("/status/{job_id}", response_model=JobStatusResponse)
async def get_job_status_endpoint(job_id: str):
    """
    Get the status of an analysis job.
    """
    job_data = await get_job_status(job_id)
    
    if not job_data:
        raise HTTPException(
            status_code=404,
            detail=f"Job {job_id} not found"
        )
    
    status_str = job_data.get("status", "pending")
    try:
        status = JobStatus(status_str)
    except ValueError:
        status = JobStatus.PENDING
    
    return JobStatusResponse(
        job_id=job_id,
        status=status,
        stage=job_data.get("stage"),
        files_analyzed=job_data.get("files_analyzed"),
        functions_analyzed=job_data.get("functions_analyzed"),
        cache_hits=job_data.get("cache_hits"),
        cache_misses=job_data.get("cache_misses"),
        skipped_reason=job_data.get("skipped_reason"),
        error=job_data.get("error"),
        created_at=job_data.get("created_at"),
        started_at=job_data.get("started_at"),
        completed_at=job_data.get("completed_at"),
    )


@router.get("/result/{job_id}", response_model=AnalysisResultResponse)
async def get_analysis_result(job_id: str):
    """
    Get the full analysis result for a completed job.
    """
    # First check job status
    job_data = await get_job_status(job_id)
    logger.info(f"job: {job_data}")    
    if not job_data:
        raise HTTPException(
            status_code=404,
            detail=f"Job {job_id} not found"
        )
    
    status_str = job_data.get("status", "pending")
    try:
        status = JobStatus(status_str)
    except ValueError:
        status = JobStatus.PENDING
    
    # If not completed, return current status
    if status != JobStatus.COMPLETED:
        return AnalysisResultResponse(
            job_id=job_id,
            owner=job_data.get("owner"),
            repo=job_data.get("repo"),
            pr_number=job_data.get("pr_number"),
            status=status,
            stage=job_data.get("stage"),
            created_at=job_data.get("created_at"),
            started_at=job_data.get("started_at"),
            error=job_data.get("error"),
            skipped_reason=job_data.get("skipped_reason"),
        )
    
    # Get the result
    result = await get_job_result(job_id)
    logger.info(f"res {result} for id: {job_id}")
    if not result:
        return AnalysisResultResponse(
            job_id=job_id,
            status=status,
            created_at=job_data.get("created_at"),
            started_at=job_data.get("started_at"),
            headline="Analysis completed but results not available",
        )
    
    # Extract analysis data
    files_analyzed = result.get("files_analyzed")
    cache_hits = result.get("cache_hits")
    cache_misses = result.get("cache_misses")

    # result["analysis"] is explicitly None (not just missing) when the
    # pipeline skipped analysis (e.g. no .c/.h files changed) — `or {}`
    # catches that case, unlike `.get("analysis", {})` which only applies
    # its default when the key is absent.
    analysis = result.get("analysis") or {}
    
    # Convert function analyses
    func_analyses = []
    for fa in analysis.get("function_analyses", []):
        func_analyses.append(FunctionAnalysisSummary(
            name=fa.get("name", "unknown"),
            risk_level=fa.get("risk_level", "unknown"),
            risk_signals=fa.get("risk_signals", []),
            suggestion=fa.get("suggestion"),
        ))
    logger.info(f"j: {job_data}, o: {job_data.get('owner')}")
    return AnalysisResultResponse(
        job_id=job_id,
        owner=job_data.get("owner"),
        repo=job_data.get("repo"),
        pr_number=job_data.get("pr_number"),
        status=status,
        created_at=job_data.get("created_at"),
        started_at=job_data.get("started_at"),
        completed_at=job_data.get("completed_at"),
        files_analyzed=files_analyzed,
        cache_hits=cache_hits,
        cache_misses=cache_misses,
        headline=analysis.get("headline"),
        risk_level=analysis.get("risk_level"),
        risk_score=analysis.get("risk_score"),
        summary=analysis.get("summary"),
        insights=analysis.get("insights", []),
        recommendations=analysis.get("recommendations", []),
        function_analyses=func_analyses,
        memory_safety_issues=analysis.get("memory_safety_issues", []),
        security_concerns=analysis.get("security_concerns", []),
        potential_bugs=analysis.get("potential_bugs", []),
        skipped_reason=result.get("skipped_reason"),
        error=job_data.get("error"),
        mermaid_diagram=analysis.get("mermaid_diagram"),
    )


@router.get("/cache/stats", response_model=CacheStatsResponse)
async def cache_stats():
    """
    Get cache statistics for monitoring.
    """
    stats = await get_cache_stats()
    return CacheStatsResponse(**stats)


@router.get("/jobs", response_model=JobListResponse)
async def list_jobs_endpoint(limit: int = 20, offset: int = 0):
    """
    List recent analysis jobs with pagination.

    Query parameters:
    - limit: Number of jobs to return (default 20, max 100)
    - offset: Number of jobs to skip (default 0)
    """
    # Limit the maximum results to prevent abuse
    limit = min(limit, 100)
    limit = max(limit, 1)
    offset = max(offset, 0)

    jobs_data, total = await list_jobs(limit=limit, offset=offset)

    # Convert to JobStatusResponse objects
    jobs = []
    for job_data in jobs_data:
        job_id = job_data.get("job_id", "unknown")
        status_str = job_data.get("status", "pending")
        try:
            status = JobStatus(status_str)
        except ValueError:
            status = JobStatus.PENDING

        jobs.append(JobStatusResponse(
            job_id=job_id,
            status=status,
            stage=job_data.get("stage"),
            owner=job_data.get("owner"),
            repo=job_data.get("repo"),
            pr_number=job_data.get("pr_number"),
            risk_level=job_data.get("risk_level"),
            files_analyzed=job_data.get("files_analyzed"),
            functions_analyzed=job_data.get("functions_analyzed"),
            cache_hits=job_data.get("cache_hits"),
            cache_misses=job_data.get("cache_misses"),
            skipped_reason=job_data.get("skipped_reason"),
            error=job_data.get("error"),
            created_at=job_data.get("created_at"),
            started_at=job_data.get("started_at"),
            completed_at=job_data.get("completed_at"),
            updated_at=job_data.get("updated_at"),
        ))

    return JobListResponse(
        jobs=jobs,
        total=total,
        limit=limit,
        offset=offset,
    )