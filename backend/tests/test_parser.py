"""Tests for core/parser.py — the tree-sitter extraction layer.

These parse real C source with the actual tree-sitter grammar (no mocking):
the goal is to pin down the exact structural signals every downstream
heuristic and risk score depends on.
"""

from core.parser import extract_file_ast


def test_simple_function_has_complexity_one():
    src = "int add(int a, int b) { return a + b; }"
    ast = extract_file_ast(src)

    assert "add" in ast.functions
    fn = ast.functions["add"]
    assert fn.complexity == 1  # no branches -> single path
    assert fn.return_type == "int"
    assert fn.params == ["int a", "int b"]
    assert fn.loop_count == 0
    assert not fn.has_recursion


def test_branches_increase_complexity():
    src = """
    int classify(int x) {
        if (x < 0) {
            return -1;
        } else if (x == 0) {
            return 0;
        }
        for (int i = 0; i < x; i++) {
            if (i % 2 == 0) {
                continue;
            }
        }
        return 1;
    }
    """
    ast = extract_file_ast(src)
    fn = ast.functions["classify"]

    # 1 (base) + if + else-if + for + nested-if = 5
    assert fn.complexity == 5
    assert fn.loop_count == 1


def test_recursive_function_is_flagged():
    src = """
    int fact(int n) {
        if (n <= 1) return 1;
        return n * fact(n - 1);
    }
    """
    ast = extract_file_ast(src)
    fn = ast.functions["fact"]

    assert fn.has_recursion is True
    assert "fact" in fn.calls


def test_memory_ops_are_counted_by_name():
    src = """
    void leaky(int n) {
        int *buf = malloc(n * sizeof(int));
        int *buf2 = malloc(n * sizeof(int));
        free(buf);
    }
    """
    ast = extract_file_ast(src)
    fn = ast.functions["leaky"]

    assert fn.memory_ops.get("malloc") == 2
    assert fn.memory_ops.get("free") == 1


def test_pointer_ops_are_counted():
    src = """
    int deref(int *p) {
        return *p + p[0];
    }
    """
    ast = extract_file_ast(src)
    fn = ast.functions["deref"]

    assert fn.pointer_ops > 0


def test_malformed_source_reports_parse_errors_not_a_crash():
    src = "int broken( { return"
    ast = extract_file_ast(src)

    assert ast.has_parse_errors is True
    assert ast.error_count > 0


def test_multiple_functions_are_all_extracted():
    src = """
    int a(void) { return 1; }
    int b(void) { return a(); }
    """
    ast = extract_file_ast(src)

    assert set(ast.functions.keys()) == {"a", "b"}
    assert "a" in ast.functions["b"].calls
