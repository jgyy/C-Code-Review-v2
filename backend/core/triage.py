"""
core/triage.py — Risk scoring and routing logic

The triage layer examines the evidence bundle and decides:
1. Risk score (0-100): How risky is this change?
2. Route: skip | fast_path | deep_analysis
3. Which functions the LLM should actually analyse (ranked selection)

ROUTING THRESHOLDS (revised for large-PR safety):
- skip:          No substantive function changes (renames, whitespace, trivial)
- fast_path:     All PRs that aren't skipped, regardless of size.
                 The fast path is now the ONLY LLM route. Deep analysis was
                 removed as a separate route because the old implementation
                 fired one LLM call per function with no cap, making it
                 O(N) in API calls and guaranteed to hit rate limits and
                 Lambda timeouts on any non-trivial PR.

FUNCTION SELECTION CAP (new):
  Triage now produces a ranked list of functions for LLM analysis, capped at
  MAX_FUNCTIONS_FOR_LLM. Functions are ranked by risk score descending.
  The remaining functions receive static-analysis-only results from triage
  signals alone, with no LLM call. This gives the LLM budget a hard ceiling
  regardless of PR size.

  MAX_FUNCTIONS_FOR_LLM = 15  (configurable)
  MAX_EVIDENCE_FOR_FAST_PATH = 30  (evidence rows sent in the single prompt)

  For a 200-file PR with 300 changed functions:
    Before: up to 300 sequential LLM calls + 1 reduce = 301 calls
    After:  1 LLM call (fast path, top-30 evidence rows, top-15 snippets)

Risk signals (weighted, unchanged):
- Memory imbalance: +30 (malloc without free or vice versa)
- Complexity increase high: +20 (>10 complexity delta)
- Complexity increase medium: +10 (>5 complexity delta)
- Signature changes: +15 (breaking API changes)
- New memory ops: +15 (function gains malloc/free)
- Orphan function: +12 (lost all callers)
- Pointer density increase: +10 (more pointer operations)
- Recursion added: +10 (potential stack overflow)
- Parse errors: +10 (incomplete/broken code)
- Depth increase: +8 (deeper nesting)
- Recursion removed: +5
- Large change: +5 (>50 lines changed)
- New loops: +5 per loop
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from core.heuristics import (
    PREvidence,
    FileEvidence,
    FunctionEvidence,
    ChangeType,
)

# ---------------------------------------------------------------------------
# Tuneable limits — the only knobs you need to touch for rate-limit tuning
# ---------------------------------------------------------------------------

# Hard cap on how many functions receive individual LLM analysis (map phase).
# Functions beyond this limit are scored by static heuristics only.
MAX_FUNCTIONS_FOR_LLM = 15

# Hard cap on how many function evidence rows are included in the fast-path
# prompt. Controls token usage. Functions are ranked by risk score; the top N
# are sent in full, the rest are omitted from the prompt entirely.
MAX_EVIDENCE_FOR_FAST_PATH = 30

# Code snippets are the most token-expensive part of the prompt. Only include
# snippets for functions above this risk score threshold, and only up to the
# LLM function cap.
MIN_RISK_SCORE_FOR_SNIPPET = 30


class Route(str, Enum):
    SKIP = "skip"
    FAST_PATH = "fast_path"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class FunctionRisk:
    """Risk assessment for a single function."""
    name: str
    risk_score: int          # 0-100
    risk_level: RiskLevel
    signals: list[str]       # human-readable risk signals
    filepath: str = ""       # which file this function lives in
    send_to_llm: bool = False  # True for the top-N highest-risk functions


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

    # Ranked functions selected for LLM analysis (top MAX_FUNCTIONS_FOR_LLM).
    # Populated by triage(); consumed by GeminiClient to build prompts.
    llm_selected_functions: list[FunctionRisk] = field(default_factory=list)

    # Summary stats for the functions NOT sent to the LLM.
    # Used to enrich the prompt context without burning extra API calls.
    unanalysed_function_count: int = 0
    unanalysed_high_risk_count: int = 0


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
# Function-Level Risk Scoring (unchanged logic, new filepath/send_to_llm fields)
# ---------------------------------------------------------------------------

def score_function(evidence: FunctionEvidence, filepath: str = "") -> FunctionRisk:
    """Compute risk score for a single function."""
    score = 0
    signals = []

    if evidence.change_type == ChangeType.DELETED:
        return FunctionRisk(
            name=evidence.name,
            risk_score=5,
            risk_level=RiskLevel.LOW,
            signals=["Function deleted"],
            filepath=filepath,
        )

    if evidence.change_type == ChangeType.UNCHANGED:
        return FunctionRisk(
            name=evidence.name,
            risk_score=0,
            risk_level=RiskLevel.LOW,
            signals=["No changes"],
            filepath=filepath,
        )

    # Memory safety signals (highest weight)
    if evidence.malloc_free_imbalance != 0:
        score += WEIGHTS["memory_imbalance"]
        if evidence.malloc_free_imbalance > 0:
            signals.append(
                f"Potential memory leak: {evidence.malloc_free_imbalance} unmatched malloc(s)"
            )
        else:
            signals.append(
                f"Potential double-free risk: {-evidence.malloc_free_imbalance} extra free(s)"
            )

    if not evidence.memory_ops_before and evidence.memory_ops_after:
        score += WEIGHTS["new_memory_ops"]
        signals.append(
            f"New memory operations introduced: {list(evidence.memory_ops_after.keys())}"
        )

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
    if evidence.pointer_density_delta > 0.1:
        score += WEIGHTS["pointer_density_increase"]
        signals.append(
            f"Pointer operation density increased by {evidence.pointer_density_delta:.1%}"
        )

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

    # Depth increase
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

    score = min(score, 100)

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
        filepath=filepath,
    )


def score_file(evidence: FileEvidence) -> FileRisk:
    """Compute risk score for a file."""
    function_risks = [
        score_function(fe, evidence.filepath) for fe in evidence.functions
    ]

    if not function_risks:
        return FileRisk(
            filepath=evidence.filepath,
            risk_score=0,
            risk_level=RiskLevel.LOW,
            functions=[],
        )

    max_risk = max(fr.risk_score for fr in function_risks)

    if evidence.had_parse_errors_after and not evidence.had_parse_errors_before:
        max_risk += WEIGHTS["parse_errors"]

    max_risk = min(max_risk, 100)

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
    """Check if the PR is trivial enough to skip LLM analysis entirely."""
    if pr_evidence.total_functions_changed == 0:
        return True, "No function changes detected"

    all_renames = all(
        func_ev.change_type in (ChangeType.RENAMED, ChangeType.UNCHANGED)
        for file_ev in pr_evidence.files
        for func_ev in file_ev.functions
    )
    if all_renames:
        return True, "Only function renames detected"

    total_lines_changed = sum(
        abs(fe.line_delta)
        for file_ev in pr_evidence.files
        for fe in file_ev.functions
    )
    if total_lines_changed <= 3 and pr_evidence.total_functions_changed == 1:
        return True, "Trivial single-function change"

    return False, ""


def _select_functions_for_llm(
    file_risks: list[FileRisk],
    cap: int = MAX_FUNCTIONS_FOR_LLM,
) -> tuple[list[FunctionRisk], int, int]:
    """
    Rank all changed functions by risk score and select the top N for LLM
    analysis. Returns (selected, unanalysed_total, unanalysed_high_risk).

    Functions are tagged with send_to_llm=True in-place so callers can
    look up selection status without carrying a separate set.
    """
    all_functions: list[FunctionRisk] = [
        fr
        for file_risk in file_risks
        for fr in file_risk.functions
    ]

    # Sort descending by risk score, stable (preserves file order on ties)
    ranked = sorted(all_functions, key=lambda fr: fr.risk_score, reverse=True)

    selected = ranked[:cap]
    unanalysed = ranked[cap:]

    for fr in selected:
        fr.send_to_llm = True

    unanalysed_high_risk = sum(
        1 for fr in unanalysed
        if fr.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
    )

    return selected, len(unanalysed), unanalysed_high_risk


def triage(pr_evidence: PREvidence) -> TriageResult:
    """
    Analyse PR evidence and determine routing + LLM function selection.

    Key differences from the original:
    - DEEP_ANALYSIS route removed. All non-trivial PRs go to FAST_PATH.
      The LLM call count is bounded by MAX_FUNCTIONS_FOR_LLM regardless of
      PR size, so the distinction between "fast" and "deep" is no longer
      meaningful as a routing decision — it only matters for prompt construction,
      which GeminiClient handles internally based on triage_result.llm_selected_functions.
    - llm_selected_functions is populated here so GeminiClient doesn't need to
      re-rank; it just iterates what triage already chose.
    - unanalysed_* stats are passed through so the prompt can mention that
      N additional lower-risk functions were not individually analysed.
    """
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

    file_risks = [score_file(fe) for fe in pr_evidence.files]

    if not file_risks:
        overall_risk = 0
    else:
        overall_risk = max(fr.risk_score for fr in file_risks)
        high_risk_files = sum(1 for fr in file_risks if fr.risk_score >= 40)
        if high_risk_files > 1:
            overall_risk = min(100, overall_risk + high_risk_files * 5)

    if overall_risk >= 60:
        overall_risk_level = RiskLevel.CRITICAL
    elif overall_risk >= 40:
        overall_risk_level = RiskLevel.HIGH
    elif overall_risk >= 20:
        overall_risk_level = RiskLevel.MEDIUM
    else:
        overall_risk_level = RiskLevel.LOW

    selected, unanalysed_count, unanalysed_high_risk = _select_functions_for_llm(
        file_risks
    )

    total_changed = pr_evidence.total_functions_changed
    selected_count = len(selected)

    reasoning = (
        f"Fast-path analysis: {overall_risk_level.value} risk ({overall_risk}/100), "
        f"{total_changed} functions changed, "
        f"top {selected_count} by risk score sent to LLM"
        + (
            f", {unanalysed_count} lower-risk functions analysed by static heuristics only"
            if unanalysed_count > 0
            else ""
        )
    )

    return TriageResult(
        route=Route.FAST_PATH,
        overall_risk_score=overall_risk,
        overall_risk_level=overall_risk_level,
        files=file_risks,
        reasoning=reasoning,
        llm_selected_functions=selected,
        unanalysed_function_count=unanalysed_count,
        unanalysed_high_risk_count=unanalysed_high_risk,
    )