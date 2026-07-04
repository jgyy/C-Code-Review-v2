"""
llm/schemas.py — Pydantic models for LLM input/output

Defines the structured data formats for:
- Input to LLM: Evidence bundles, code snippets
- Output from LLM: Analysis results, recommendations

Using Pydantic ensures type safety and enables JSON serialization.
"""

from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Function-Level Analysis
# ---------------------------------------------------------------------------

class FunctionAnalysisInput(BaseModel):
    """Input data for analyzing a single function."""
    name: str
    filepath: str
    change_type: str  # added, deleted, modified, renamed
    
    # Code snippets
    code_before: Optional[str] = None
    code_after: Optional[str] = None
    
    # Evidence signals
    complexity_delta: int = 0
    depth_delta: int = 0
    memory_ops_before: dict = Field(default_factory=dict)
    memory_ops_after: dict = Field(default_factory=dict)
    malloc_free_imbalance: int = 0
    pointer_density_delta: float = 0.0
    
    # Signature info
    params_before: list[str] = Field(default_factory=list)
    params_after: list[str] = Field(default_factory=list)
    return_type_changed: bool = False
    
    # Call graph
    calls_added: list[str] = Field(default_factory=list)
    calls_removed: list[str] = Field(default_factory=list)
    
    # Flags
    recursion_changed: bool = False
    is_recursive: bool = False
    renamed_from: Optional[str] = None


class FunctionAnalysisOutput(BaseModel):
    """LLM output for a single function analysis."""
    name: str
    risk_level: RiskLevel = RiskLevel.LOW
    risk_signals: list[str] = Field(default_factory=list)
    suggestion: Optional[str] = None
    potential_bugs: list[str] = Field(default_factory=list)
    security_concerns: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# PR-Level Analysis
# ---------------------------------------------------------------------------

class PRAnalysisInput(BaseModel):
    """Input data for analyzing an entire PR."""
    repo_name: str
    pr_number: int
    
    # Aggregate metrics
    total_files: int
    total_functions: int
    overall_risk_score: int
    
    # Top-level signals
    has_memory_issues: bool = False
    has_signature_changes: bool = False
    has_orphaned_functions: bool = False
    max_complexity_delta: int = 0
    
    # Function analyses
    functions: list[FunctionAnalysisInput] = Field(default_factory=list)


class PRAnalysis(BaseModel):
    """Complete analysis result for a PR."""
    headline: str = Field(description="One-line summary of the PR's risk profile")
    risk_level: RiskLevel = RiskLevel.LOW
    risk_score: int = Field(ge=0, le=100, description="Risk score 0-100")
    
    summary: Optional[str] = Field(
        default=None,
        description="2-3 sentence summary of the changes and their implications"
    )
    
    insights: list[str] = Field(
        default_factory=list,
        description="Key observations about the code changes"
    )
    
    recommendations: list[str] = Field(
        default_factory=list,
        description="Actionable recommendations for the PR author"
    )
    
    function_analyses: list[FunctionAnalysisOutput] = Field(
        default_factory=list,
        description="Per-function analysis results"
    )
    
    # Specific concern categories
    memory_safety_issues: list[str] = Field(default_factory=list)
    security_concerns: list[str] = Field(default_factory=list)
    potential_bugs: list[str] = Field(default_factory=list)
    
    # For deep analysis: map-reduce synthesis
    cross_function_concerns: list[str] = Field(
        default_factory=list,
        description="Issues that span multiple functions"
    )

    # Optional visual: a Mermaid flowchart illustrating the call-graph impact
    # of the change (changed functions, their callers/callees). Validated and
    # retried server-side before being stored — see llm/client.py
    # _ensure_valid_mermaid(). None if generation/validation didn't succeed.
    mermaid_diagram: Optional[str] = Field(
        default=None,
        description="Mermaid flowchart source illustrating the change's call-graph impact",
    )


# ---------------------------------------------------------------------------
# Prompt Context Models
# ---------------------------------------------------------------------------

class PromptContext(BaseModel):
    """Context passed to prompt templates."""
    # PR metadata
    repo_name: str
    pr_number: int
    
    # Risk info from triage
    overall_risk_score: int
    overall_risk_level: str
    triage_reasoning: str
    
    # Function evidence (serialized)
    function_evidences: list[dict] = Field(default_factory=list)
    
    # Code snippets (for high-risk functions)
    code_snippets: dict[str, str] = Field(default_factory=dict)  # func_name -> code


class MapReduceContext(BaseModel):
    """Context for map-reduce deep analysis."""
    # Map phase: per-function analyses
    function_analyses: list[FunctionAnalysisOutput] = Field(default_factory=list)
    
    # Reduce phase: synthesis context
    total_functions: int
    high_risk_count: int
    file_paths: list[str] = Field(default_factory=list)
    
    # Cross-cutting patterns detected
    patterns: list[str] = Field(default_factory=list)
