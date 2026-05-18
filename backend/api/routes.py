"""
api/routes.py — REST API endpoints

Provides endpoints for:
- Manual PR analysis triggers
- Job status checking
- Analysis result retrieval
- Cache statistics
"""

from __future__ import annotations
import uuid

from fastapi import APIRouter, HTTPException, BackgroundTasks

from api.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    JobStatusResponse,
    AnalysisResultResponse,
    FunctionAnalysisSummary,
    CacheStatsResponse,
    JobListResponse,
    JobStatus,
)
from cache.redis import (
    enqueue_job,
    get_job_status,
    get_job_result,
    get_cache_stats,
    list_jobs,
)
from github_utils.webhook import process_pr_job
import logging
from typing import Optional, List
import asyncio

logger = logging.getLogger(__name__)

router = APIRouter(tags=["api"])


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_pr(
    request: AnalyzeRequest,
    background_tasks: BackgroundTasks,
):
    """
    Trigger analysis of a PR.
    
    This endpoint queues a job for background processing and returns
    immediately with a job ID that can be used to check status.
    """
    # Generate job ID
    job_id = f"manual-{request.owner}-{request.repo}-{request.pr_number}-{uuid.uuid4().hex[:8]}"
    logger.info(f"Analyze request received for job: {job_id}")
    
    # Queue the job
    job_data = {
        "owner": request.owner,
        "repo": request.repo,
        "pr_number": request.pr_number,
        "action": "manual",
        "installation_id": request.installation_id,
    }
    
    # asyncio.create_task(enqueue_job(job_id, job_data))
    success = await enqueue_job(job_id, job_data)
    logger.info(f"enqueue: {success}")    
    if not success:
        logger.error(f"Analyze request failed for job: {job_id}")
        raise HTTPException(
            status_code=503,
            detail="Failed to queue job. Redis may be unavailable."
        )
    
    # Process in background
    background_tasks.add_task(
        process_pr_job,
        job_id=job_id,
        owner=request.owner,
        repo_name=request.repo,
        pr_number=request.pr_number,
        installation_id=request.installation_id,
    )
    
    return AnalyzeResponse(
        job_id=job_id,
        status=JobStatus.PENDING,
        message=f"Analysis queued for {request.owner}/{request.repo}/{request.pr_number}",
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
        files_analyzed=job_data.get("files_analyzed"),
        functions_analyzed=job_data.get("functions_analyzed"),
        cache_hits=job_data.get("cache_hits"),
        cache_misses=job_data.get("cache_misses"),
        skipped_reason=job_data.get("skipped_reason"),
        error=job_data.get("error"),
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
        )
    
    # Get the result
    result = await get_job_result(job_id)
    logger.info(f"res {result} for id: {job_id}")
    if not result:
        return AnalysisResultResponse(
            job_id=job_id,
            status=status,
            headline="Analysis completed but results not available",
        )
    
    # Extract analysis data
    files_analyzed = result.get("files_analyzed")
    cache_hits = result.get("cache_hits")
    cache_misses = result.get("cache_misses")

    analysis = result.get("analysis", {})
    
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
            files_analyzed=job_data.get("files_analyzed"),
            functions_analyzed=job_data.get("functions_analyzed"),
            cache_hits=job_data.get("cache_hits"),
            cache_misses=job_data.get("cache_misses"),
            skipped_reason=job_data.get("skipped_reason"),
            error=job_data.get("error"),
            created_at=job_data.get("created_at"),
            updated_at=job_data.get("updated_at"),
        ))

    return JobListResponse(
        jobs=jobs,
        total=total,
        limit=limit,
        offset=offset,
    )
