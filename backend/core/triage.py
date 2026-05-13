"""
core/triage.py — Risk scoring and routing logic

The triage layer examines the evidence bundle and decides:
1. Risk score (0-100): How risky is this change?
2. Route: skip | fast_path | deep_analysis

Routing thresholds:
- skip: Pure renames, formatting-only, comment changes, trivial one-liners
- fast_path: Low-medium risk, can be analyzed in a single LLM call
- deep_analysis: High risk, multi-function impact, needs map-reduce analysis

Risk signals (weighted):
- Memory imbalance: +30 (malloc without free or vice versa)
- Complexity increase: +20 (>5 complexity delta)
- Signature changes: +15 (breaking API changes)
- Pointer density increase: +10 (more pointer operations)
- Recursion added: +10 (potential stack overflow)
- Large function changes: +5 (>50 lines changed)
- Parse errors: +10 (incomplete/broken code)
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from core.heuristics import (
    PREvidence,
    FileEvidence,
    FunctionEvidence,
    ChangeType,
)


class Route(str, Enum):
    SKIP = "skip"
    FAST_PATH = "fast_path"
    DEEP_ANALYSIS = "deep_analysis"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class FunctionRisk:
    """Risk assessment for a single function."""
    name: str
    risk_score: int  # 0-100
    risk_level: RiskLevel
    signals: list[str]  # Human-readable risk signals


@dataclass
class FileRisk:
    """Risk assessment for a file."""
    filepath: str
    risk_score: int
    risk_level: RiskLevel
    functions: list[FunctionRisk]


@dataclass
class TriageResult:
    """Complete triage result for a PR."""
    route: Route
    overall_risk_score: int
    overall_risk_level: RiskLevel
    files: list[FileRisk]
    reasoning: str
    skip_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Risk Weights
# ---------------------------------------------------------------------------

WEIGHTS = {
    "memory_imbalance": 30,
    "complexity_increase_high": 20,
    "complexity_increase_medium": 10,
    "signature_change": 15,
    "pointer_density_increase": 10,
    "recursion_added": 10,
    "recursion_removed": 5,
    "large_change": 5,
    "new_memory_ops": 15,
    "parse_errors": 10,
    "depth_increase": 8,
    "orphan_function": 12,
    "new_loops": 5,
}


# ---------------------------------------------------------------------------
# Function-Level Risk Scoring
# ---------------------------------------------------------------------------

def score_function(evidence: FunctionEvidence) -> FunctionRisk:
    """Compute risk score for a single function."""
    score = 0
    signals = []
    
    # Skip deleted or unchanged functions - low risk by definition
    if evidence.change_type == ChangeType.DELETED:
        return FunctionRisk(
            name=evidence.name,
            risk_score=5,
            risk_level=RiskLevel.LOW,
            signals=["Function deleted"],
        )
    
    if evidence.change_type == ChangeType.UNCHANGED:
        return FunctionRisk(
            name=evidence.name,
            risk_score=0,
            risk_level=RiskLevel.LOW,
            signals=["No changes"],
        )
    
    # Memory safety signals (highest weight)
    if evidence.malloc_free_imbalance != 0:
        score += WEIGHTS["memory_imbalance"]
        if evidence.malloc_free_imbalance > 0:
            signals.append(f"Potential memory leak: {evidence.malloc_free_imbalance} unmatched malloc(s)")
        else:
            signals.append(f"Potential double-free risk: {-evidence.malloc_free_imbalance} extra free(s)")
    
    # New memory operations in a function that didn't have them
    if not evidence.memory_ops_before and evidence.memory_ops_after:
        score += WEIGHTS["new_memory_ops"]
        signals.append(f"New memory operations introduced: {list(evidence.memory_ops_after.keys())}")
    
    # Complexity delta
    if evidence.complexity_delta > 10:
        score += WEIGHTS["complexity_increase_high"]
        signals.append(f"High complexity increase: +{evidence.complexity_delta}")
    elif evidence.complexity_delta > 5:
        score += WEIGHTS["complexity_increase_medium"]
        signals.append(f"Moderate complexity increase: +{evidence.complexity_delta}")
    
    # Signature changes
    if evidence.return_type_changed:
        score += WEIGHTS["signature_change"]
        signals.append("Return type changed")
    
    if evidence.param_count_delta != 0:
        score += WEIGHTS["signature_change"]
        signals.append(f"Parameter count changed by {evidence.param_count_delta}")
    
    # Pointer density
    if evidence.pointer_density_delta > 0.1:  # 10% increase
        score += WEIGHTS["pointer_density_increase"]
        signals.append(f"Pointer operation density increased by {evidence.pointer_density_delta:.1%}")
    
    # Recursion
    if evidence.recursion_changed:
        if evidence.is_recursive and not evidence.was_recursive:
            score += WEIGHTS["recursion_added"]
            signals.append("Recursion introduced")
        elif evidence.was_recursive and not evidence.is_recursive:
            score += WEIGHTS["recursion_removed"]
            signals.append("Recursion removed")
    
    # Large changes
    if abs(evidence.line_delta) > 50:
        score += WEIGHTS["large_change"]
        signals.append(f"Large change: {evidence.line_delta:+d} lines")
    
    # Depth increase (nested complexity)
    if evidence.depth_delta > 3:
        score += WEIGHTS["depth_increase"]
        signals.append(f"Nesting depth increased by {evidence.depth_delta}")
    
    # New loops
    loop_delta = evidence.loop_count_after - evidence.loop_count_before
    if loop_delta > 0:
        score += WEIGHTS["new_loops"] * loop_delta
        signals.append(f"{loop_delta} new loop(s) added")
    
    # Orphan status
    if evidence.is_orphan:
        score += WEIGHTS["orphan_function"]
        signals.append("Function lost all callers (orphaned)")
    
    # Cap at 100
    score = min(score, 100)
    
    # Determine risk level
    if score >= 60:
        risk_level = RiskLevel.CRITICAL
    elif score >= 40:
        risk_level = RiskLevel.HIGH
    elif score >= 20:
        risk_level = RiskLevel.MEDIUM
    else:
        risk_level = RiskLevel.LOW
    
    return FunctionRisk(
        name=evidence.name,
        risk_score=score,
        risk_level=risk_level,
        signals=signals if signals else ["Minor changes"],
    )


def score_file(evidence: FileEvidence) -> FileRisk:
    """Compute risk score for a file."""
    function_risks = [score_function(fe) for fe in evidence.functions]
    
    if not function_risks:
        return FileRisk(
            filepath=evidence.filepath,
            risk_score=0,
            risk_level=RiskLevel.LOW,
            functions=[],
        )
    
    # File risk is max of function risks + parse error penalty
    max_risk = max(fr.risk_score for fr in function_risks)
    
    if evidence.had_parse_errors_after and not evidence.had_parse_errors_before:
        max_risk += WEIGHTS["parse_errors"]
    
    max_risk = min(max_risk, 100)
    
    # Determine risk level
    if max_risk >= 60:
        risk_level = RiskLevel.CRITICAL
    elif max_risk >= 40:
        risk_level = RiskLevel.HIGH
    elif max_risk >= 20:
        risk_level = RiskLevel.MEDIUM
    else:
        risk_level = RiskLevel.LOW
    
    return FileRisk(
        filepath=evidence.filepath,
        risk_score=max_risk,
        risk_level=risk_level,
        functions=function_risks,
    )


# ---------------------------------------------------------------------------
# Triage Decision
# ---------------------------------------------------------------------------

def _is_trivial_change(pr_evidence: PREvidence) -> tuple[bool, str]:
    """
    Check if the PR is trivial enough to skip LLM analysis.
    Returns (is_trivial, reason).
    """
    # No function changes at all (maybe just comments/whitespace)
    if pr_evidence.total_functions_changed == 0:
        return True, "No function changes detected"
    
    # Check if all changes are renames with high confidence
    all_renames = True
    for file_ev in pr_evidence.files:
        for func_ev in file_ev.functions:
            if func_ev.change_type not in (ChangeType.RENAMED, ChangeType.UNCHANGED):
                all_renames = False
                break
        if not all_renames:
            break
    
    if all_renames:
        return True, "Only function renames detected"
    
    # Check for single-line trivial changes
    total_lines_changed = sum(
        abs(fe.line_delta)
        for file_ev in pr_evidence.files
        for fe in file_ev.functions
    )
    
    if total_lines_changed <= 3 and pr_evidence.total_functions_changed == 1:
        # Single function, tiny change - likely trivial
        return True, "Trivial single-function change"
    
    return False, ""


def triage(pr_evidence: PREvidence) -> TriageResult:
    """
    Analyze PR evidence and determine routing.
    
    Returns a TriageResult with:
    - route: skip/fast_path/deep_analysis
    - risk scores at all levels
    - reasoning for the decision
    """
    # Check for trivial skip
    is_trivial, skip_reason = _is_trivial_change(pr_evidence)
    if is_trivial:
        return TriageResult(
            route=Route.SKIP,
            overall_risk_score=0,
            overall_risk_level=RiskLevel.LOW,
            files=[],
            reasoning="Trivial change, skipping analysis",
            skip_reason=skip_reason,
        )
    
    # Score all files
    file_risks = [score_file(fe) for fe in pr_evidence.files]
    
    # Calculate overall risk
    if not file_risks:
        overall_risk = 0
    else:
        # Overall risk is max file risk + bonus for multiple high-risk files
        overall_risk = max(fr.risk_score for fr in file_risks)
        high_risk_files = sum(1 for fr in file_risks if fr.risk_score >= 40)
        if high_risk_files > 1:
            overall_risk = min(100, overall_risk + high_risk_files * 5)
    
    # Determine overall risk level
    if overall_risk >= 60:
        overall_risk_level = RiskLevel.CRITICAL
    elif overall_risk >= 40:
        overall_risk_level = RiskLevel.HIGH
    elif overall_risk >= 20:
        overall_risk_level = RiskLevel.MEDIUM
    else:
        overall_risk_level = RiskLevel.LOW
    
    # Determine route
    if overall_risk >= 50 or pr_evidence.total_functions_changed > 10:
        route = Route.DEEP_ANALYSIS
        reasoning = (
            f"Deep analysis required: {overall_risk_level.value} risk "
            f"({overall_risk}/100), {pr_evidence.total_functions_changed} functions changed"
        )
    elif overall_risk >= 15:
        route = Route.FAST_PATH
        reasoning = (
            f"Fast-path analysis: {overall_risk_level.value} risk "
            f"({overall_risk}/100), {pr_evidence.total_functions_changed} functions changed"
        )
    else:
        route = Route.FAST_PATH  # Still analyze low-risk changes, just quickly
        reasoning = (
            f"Low-risk fast-path: {overall_risk}/100 risk score, "
            f"{pr_evidence.total_functions_changed} functions changed"
        )
    
    return TriageResult(
        route=route,
        overall_risk_score=overall_risk,
        overall_risk_level=overall_risk_level,
        files=file_risks,
        reasoning=reasoning,
    )
