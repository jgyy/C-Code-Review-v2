"""
api/schemas.py — Pydantic models for API requests and responses

Defines the REST API contract for:
- Manual analysis triggers
- Job status queries
- Analysis results
"""

from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum
from datetime import datetime
from typing import Optional

class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------

class AnalyzeRequest(BaseModel):
    """Request to analyze a PR."""
    owner: str = Field(description="Repository owner (user or org)")
    repo: str = Field(description="Repository name")
    pr_number: int = Field(description="Pull request number", gt=0)
    
    # Optional: for GitHub App installations
    installation_id: Optional[int] = Field(
        default=None,
        description="GitHub App installation ID (optional, for app auth)"
    )


# ---------------------------------------------------------------------------
# Response Models
# ---------------------------------------------------------------------------

class AnalyzeResponse(BaseModel):
    """Response from analyze endpoint."""
    job_id: str = Field(description="Unique job identifier")
    status: JobStatus = Field(description="Current job status")
    message: str = Field(description="Human-readable status message")


class JobStatusResponse(BaseModel):
    """Response from job status endpoint."""
    job_id: str
    status: JobStatus

    # Job metadata (stored at enqueue time)
    owner: Optional[str] = None
    repo: Optional[str] = None
    pr_number: Optional[int] = None

    # Timestamps
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
    updated_at: Optional[str] = None

    # For completed jobs
    risk_level: Optional[str] = None
    files_analyzed: Optional[int] = None
    functions_analyzed: Optional[int] = None
    cache_hits: Optional[int] = None
    cache_misses: Optional[int] = None

    # For skipped jobs
    skipped_reason: Optional[str] = None

    # For failed jobs
    error: Optional[str] = None


class FunctionAnalysisSummary(BaseModel):
    """Summary of a function's analysis."""
    name: str
    risk_level: str
    risk_signals: list[str] = Field(default_factory=list)
    suggestion: Optional[str] = None


class AnalysisResultResponse(BaseModel):
    """Full analysis result."""
    job_id: str
    status: JobStatus

    owner: Optional[str] = None
    repo: Optional[str] = None
    pr_number: Optional[int] = None

    # Timestamps
    created_at: Optional[str] = None
    completed_at: Optional[str] = None

    # Files analysis
    files_analyzed: Optional[int] = None
    cache_hits: Optional[int] = None
    cache_misses: Optional[int] = None

    # Analysis summary
    headline: Optional[str] = None
    risk_level: Optional[str] = None
    risk_score: Optional[int] = None
    summary: Optional[str] = None

    # Details
    insights: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    function_analyses: list[FunctionAnalysisSummary] = Field(default_factory=list)

    # Issues
    memory_safety_issues: list[str] = Field(default_factory=list)
    security_concerns: list[str] = Field(default_factory=list)
    potential_bugs: list[str] = Field(default_factory=list)


class CacheStatsResponse(BaseModel):
    """Cache statistics."""
    status: str
    total_keys: Optional[int] = None
    error: Optional[str] = None


class JobListResponse(BaseModel):
    """Response for listing jobs."""
    jobs: list[JobStatusResponse] = Field(default_factory=list)
    total: int
    limit: int
    offset: int


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    service: str
    version: str = "0.1.0"