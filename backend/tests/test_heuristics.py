"""Tests for core/heuristics.py — identity matching and evidence computation.

Uses real FileAST objects produced by extract_file_ast, so a match or an
evidence field being wrong here means the actual PR pipeline would score a
diff incorrectly.
"""

from core.parser import extract_file_ast, FileAST
from core.heuristics import (
    ChangeType,
    match_functions,
    compute_function_evidence,
    compute_file_evidence,
    compute_pr_evidence,
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


def test_fetch_failure_does_not_report_false_deletions():
    """
    Regression test for issue #7: a failed content fetch for the after-side
    of a file (rate limit / transient GitHub API error) must NOT be treated
    as "these functions were deleted". Previously, a fetch failure produced
    an empty FileAST that was diffed against the real before-AST exactly
    like a genuine deletion, so every untouched function in the file was
    misreported as deleted with dangling callers.
    """
    before = extract_file_ast(
        "int clean_ast(void) { return 1; }\n"
        "int clean_tok(void) { return clean_ast(); }\n"
    )
    # Simulates github_utils.client.GitHubFetchError being caught in the
    # pipeline and converted into a fetch_failed placeholder, rather than an
    # empty-but-legitimate FileAST.
    after = FileAST(source_hash="fetch_error", has_parse_errors=True, fetch_failed=True)

    evidence = compute_file_evidence("lexer.c", before, after)

    assert evidence.fetch_failed is True
    # No function evidence should be produced — in particular, no DELETED
    # entries for clean_ast/clean_tok, which still exist and were untouched.
    assert evidence.functions == []
    assert evidence.functions_deleted == 0

    pr_evidence = compute_pr_evidence([evidence])
    assert pr_evidence.files_with_fetch_errors == ["lexer.c"]
    assert pr_evidence.total_functions_changed == 0


def test_fetch_failure_on_before_side_also_suppressed():
    """Same guard, mirrored: a failed BEFORE fetch must not fabricate ADDED
    functions for content that was actually untouched."""
    before = FileAST(source_hash="fetch_error", has_parse_errors=True, fetch_failed=True)
    after = extract_file_ast("int ft_crutch(void) { return 1; }\n")

    evidence = compute_file_evidence("parser.c", before, after)

    assert evidence.fetch_failed is True
    assert evidence.functions == []
    assert evidence.functions_added == 0
