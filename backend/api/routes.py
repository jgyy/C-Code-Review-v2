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
    JobStatus,
)
from cache.redis import (
    enqueue_job,
    get_job_status,
    get_job_result,
    get_cache_stats,
)
from github.webhook import process_pr_job


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
    
    # Queue the job
    job_data = {
        "owner": request.owner,
        "repo": request.repo,
        "pr_number": request.pr_number,
        "action": "manual",
        "installation_id": request.installation_id,
    }
    
    success = await enqueue_job(job_id, job_data)
    
    if not success:
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
        message=f"Analysis queued for {request.owner}/{request.repo}#{request.pr_number}",
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
            status=status,
        )
    
    # Get the result
    result = await get_job_result(job_id)
    
    if not result:
        return AnalysisResultResponse(
            job_id=job_id,
            status=status,
            headline="Analysis completed but results not available",
        )
    
    # Extract analysis data
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
    
    return AnalysisResultResponse(
        job_id=job_id,
        status=status,
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
