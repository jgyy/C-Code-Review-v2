"""Tests for core/heuristics.py — identity matching and evidence computation.

Uses real FileAST objects produced by extract_file_ast, so a match or an
evidence field being wrong here means the actual PR pipeline would score a
diff incorrectly.
"""

from core.parser import extract_file_ast
from core.heuristics import (
    ChangeType,
    match_functions,
    compute_function_evidence,
)


def test_unchanged_function_matches_exactly():
    src = "int add(int a, int b) { return a + b; }"
    before = extract_file_ast(src)
    after = extract_file_ast(src)

    matches = match_functions(before, after)

    assert len(matches) == 1
    assert matches[0].change_type == ChangeType.MODIFIED
    assert matches[0].old_name == matches[0].new_name == "add"


def test_added_function_is_detected():
    before = extract_file_ast("int a(void) { return 1; }")
    after = extract_file_ast(
        "int a(void) { return 1; }\nint b(void) { return 2; }"
    )

    matches = match_functions(before, after)
    added = [m for m in matches if m.change_type == ChangeType.ADDED]

    assert len(added) == 1
    assert added[0].new_name == "b"


def test_deleted_function_is_detected():
    before = extract_file_ast(
        "int a(void) { return 1; }\nint b(void) { return 2; }"
    )
    after = extract_file_ast("int a(void) { return 1; }")

    matches = match_functions(before, after)
    deleted = [m for m in matches if m.change_type == ChangeType.DELETED]

    assert len(deleted) == 1
    assert deleted[0].old_name == "b"


def test_renamed_function_is_matched_by_signature_similarity():
    before = extract_file_ast(
        "int compute_total(int a, int b) { return a + b; }"
    )
    after = extract_file_ast(
        "int compute_sum(int a, int b) { return a + b; }"
    )

    matches = match_functions(before, after)

    assert len(matches) == 1
    match = matches[0]
    assert match.change_type == ChangeType.RENAMED
    assert match.old_name == "compute_total"
    assert match.new_name == "compute_sum"
    assert match.confidence >= 70.0


def test_evidence_flags_memory_imbalance_on_modification():
    before = extract_file_ast(
        "void f(int n) { int *p = malloc(n); free(p); }"
    )
    after = extract_file_ast(
        "void f(int n) { int *p = malloc(n); int *q = malloc(n); free(p); }"
    )

    match = match_functions(before, after)[0]
    evidence = compute_function_evidence(match, all_callers={})

    # before: 1 malloc, 1 free -> balanced (delta 0)
    # after: 2 malloc, 1 free -> +1 unmatched malloc
    assert evidence.memory_ops_before == {"malloc": 1, "free": 1}
    assert evidence.memory_ops_after == {"malloc": 2, "free": 1}


def test_evidence_flags_complexity_delta_on_new_branches():
    before = extract_file_ast("int f(int x) { return x; }")
    after = extract_file_ast(
        "int f(int x) { if (x > 0) { return 1; } return 0; }"
    )

    match = match_functions(before, after)[0]
    evidence = compute_function_evidence(match, all_callers={})

    assert evidence.complexity_before == 1
    assert evidence.complexity_after == 2
    assert evidence.complexity_delta == 1


def test_evidence_flags_signature_change():
    before = extract_file_ast("int f(int a) { return a; }")
    after = extract_file_ast("int f(int a, int b) { return a + b; }")

    match = match_functions(before, after)[0]
    evidence = compute_function_evidence(match, all_callers={})

    assert evidence.param_count_delta == 1
    assert evidence.return_type_changed is False


def test_deleted_function_with_live_caller_is_flagged():
    before = extract_file_ast(
        "int helper(void) { return 1; }\n"
        "int main(void) { return helper(); }"
    )
    after = extract_file_ast("int main(void) { return 0; }")

    matches = match_functions(before, after)
    deleted = next(m for m in matches if m.change_type == ChangeType.DELETED)

    evidence = compute_function_evidence(
        deleted, all_callers={"helper": {"main"}}
    )

    assert evidence.callers_lost == ["main"]
