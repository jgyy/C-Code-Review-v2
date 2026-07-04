"""Tests for core/triage.py — risk scoring and routing.

These pin down the exact score/route a given evidence bundle produces.
The weights and thresholds are the part of the system most likely to
silently regress (e.g. a routing change that quietly makes a memory leak
score LOW instead of CRITICAL), so they're worth locking down explicitly.
"""

from core.heuristics import ChangeType, FunctionEvidence, FileEvidence, PREvidence
from core.triage import (
    Route,
    RiskLevel,
    score_function,
    triage,
    MAX_FUNCTIONS_FOR_LLM,
)


def test_unchanged_function_scores_zero():
    evidence = FunctionEvidence(name="f", change_type=ChangeType.UNCHANGED)
    risk = score_function(evidence)

    assert risk.risk_score == 0
    assert risk.risk_level == RiskLevel.LOW


def test_memory_imbalance_is_flagged_critical():
    evidence = FunctionEvidence(
        name="leaky",
        change_type=ChangeType.MODIFIED,
        malloc_free_imbalance=1,
    )
    risk = score_function(evidence)

    assert risk.risk_score == 20  # WEIGHTS["memory_imbalance"]
    assert any("leak" in s.lower() for s in risk.signals)


def test_double_free_signal_is_distinguished_from_leak():
    evidence = FunctionEvidence(
        name="double_freer",
        change_type=ChangeType.MODIFIED,
        malloc_free_imbalance=-1,
    )
    risk = score_function(evidence)

    assert any("double-free" in s.lower() for s in risk.signals)


def test_deleted_function_with_live_callers_is_critical():
    evidence = FunctionEvidence(
        name="helper",
        change_type=ChangeType.DELETED,
        callers_lost=["main", "worker"],
    )
    risk = score_function(evidence)

    assert risk.risk_level == RiskLevel.CRITICAL


def test_deleted_function_without_callers_is_low_risk():
    evidence = FunctionEvidence(name="unused", change_type=ChangeType.DELETED)
    risk = score_function(evidence)

    assert risk.risk_level == RiskLevel.LOW


def test_high_complexity_delta_crosses_high_threshold():
    evidence = FunctionEvidence(
        name="f",
        change_type=ChangeType.MODIFIED,
        complexity_delta=15,
    )
    risk = score_function(evidence)

    assert risk.risk_score >= 20
    assert any("complexity" in s.lower() for s in risk.signals)


def test_score_is_capped_at_100():
    evidence = FunctionEvidence(
        name="everything_wrong",
        change_type=ChangeType.MODIFIED,
        malloc_free_imbalance=1,
        complexity_delta=20,
        return_type_changed=True,
        param_count_delta=2,
        pointer_density_delta=0.5,
        recursion_changed=True,
        is_recursive=True,
        was_recursive=False,
        line_delta=200,
        depth_delta=10,
        loop_count_before=0,
        loop_count_after=5,
        is_orphan=True,
    )
    risk = score_function(evidence)

    assert risk.risk_score == 100
    assert risk.risk_level == RiskLevel.CRITICAL


def test_triage_skips_pr_with_no_function_changes():
    result = triage(PREvidence(total_functions_changed=0))

    assert result.route == Route.SKIP
    assert result.overall_risk_score == 0
    assert result.skip_reason == "No function changes detected"


def test_triage_skips_rename_only_pr():
    renamed = FunctionEvidence(name="f2", change_type=ChangeType.RENAMED)
    pr_evidence = PREvidence(
        files=[FileEvidence(filepath="a.c", functions=[renamed])],
        total_functions_changed=1,
    )
    result = triage(pr_evidence)

    assert result.route == Route.SKIP
    assert result.skip_reason == "Only function renames detected"


def test_triage_routes_risky_change_to_fast_path():
    risky = FunctionEvidence(
        name="f",
        change_type=ChangeType.MODIFIED,
        malloc_free_imbalance=1,
        line_delta=10,
    )
    pr_evidence = PREvidence(
        files=[FileEvidence(filepath="a.c", functions=[risky])],
        total_functions_changed=1,
    )
    result = triage(pr_evidence)

    assert result.route == Route.FAST_PATH
    assert result.overall_risk_score >= 20
    assert len(result.llm_selected_functions) == 1
    assert result.llm_selected_functions[0].send_to_llm is True


def test_llm_selection_is_capped_and_ranked_by_risk():
    # One function per weight tier so ranking is unambiguous, well over the cap.
    functions = [
        FunctionEvidence(
            name=f"f{i}",
            change_type=ChangeType.MODIFIED,
            complexity_delta=i,
            line_delta=10,
        )
        for i in range(MAX_FUNCTIONS_FOR_LLM + 5)
    ]
    pr_evidence = PREvidence(
        files=[FileEvidence(filepath="a.c", functions=functions)],
        total_functions_changed=len(functions),
    )
    result = triage(pr_evidence)

    assert len(result.llm_selected_functions) == MAX_FUNCTIONS_FOR_LLM
    assert result.unanalysed_function_count == 5
    # Highest complexity_delta (most risk) must be selected, not skipped.
    selected_names = {fr.name for fr in result.llm_selected_functions}
    assert f"f{MAX_FUNCTIONS_FOR_LLM + 4}" in selected_names
