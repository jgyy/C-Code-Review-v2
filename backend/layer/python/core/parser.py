"""
core/parser.py — Tree-sitter parsing layer

WHY TREE-SITTER:
  Tree-sitter is a deterministic, incremental, error-tolerant parser. For a
  diff tool the error-tolerance matters: PR code is often syntactically
  incomplete (missing headers, ifdef blocks stripped, etc.). Tree-sitter
  produces a partial AST with ERROR nodes rather than failing entirely, so
  downstream heuristics still get useful signal from broken files.

  We use tree-sitter-language-pack rather than building grammars manually.
  The pack pre-compiles ~40 grammars as shared libraries. For a code-review
  tool that may encounter C, C++, or embedded C variants, this future-proofs
  language support without grammar maintenance overhead.

WHY PARSE BOTH SIDES:
  We parse the FULL file on each side of the diff, not just changed hunks.
  Reason: a hunk-only parse loses function boundaries. If line 50 changes
  inside `process()`, we need the full AST of `process()` to compute
  complexity, call graph, etc. The hunk gives us location; the full AST gives
  us context. Cost is negligible — tree-sitter parses ~1MB/s+ on a single core.

CACHING STRATEGY:
  AST snapshots are keyed by (sha, filepath). Identical files across PRs
  (e.g. headers that didn't change) are never re-parsed. The cache lives in
  the caller (pipeline.py) using an in-process dict for single-process mode
  and Redis for distributed mode.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import hashlib

from tree_sitter import Language, Parser, Node
import tree_sitter_c as tsc

# ---------------------------------------------------------------------------
# Language setup
# ---------------------------------------------------------------------------
# We instantiate the language once per process. Language objects are
# thread-safe and cheap to share; Parser objects are NOT thread-safe and must
# be created per-thread/per-call.
C_LANGUAGE = Language(tsc.language())


def _make_parser() -> Parser:
    """Create a fresh parser instance. Not thread-safe — create one per call."""
    p = Parser()
    p.language = C_LANGUAGE
    return p


# ---------------------------------------------------------------------------
# AST node types we care about
# ---------------------------------------------------------------------------
BRANCH_NODES = frozenset({
    "if_statement", "for_statement", "while_statement",
    "do_statement", "switch_statement", "case_statement",
    "conditional_expression",  # ternary
})

LOOP_NODES = frozenset({
    "for_statement", "while_statement", "do_statement",
})

MEMORY_CALLS = frozenset({
    "malloc", "calloc", "realloc", "free", "alloca",
    "mmap", "munmap", "new", "delete",
})

POINTER_NODES = frozenset({
    "pointer_declarator",       # int *p
    "pointer_expression",       # *p, &x
    "field_expression",         # p->field
    "subscript_expression",     # arr[i]
})


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class FunctionInfo:
    """
    All structural information extracted from a single function definition.
    This is the atomic unit that flows through the entire pipeline.

    WHY A DATACLASS:
      Plain dicts work but make downstream code fragile (KeyError-prone) and
      untyped. Dataclasses give us slot-based access, __repr__, and are
      trivially JSON-serialisable via dataclasses.asdict().
    """
    name: str
    params: list[str]           # ["int a", "int *b"]
    return_type: str            # "int", "void", "char *"
    calls: list[str]            # all callee names
    complexity: int             # McCabe cyclomatic complexity
    max_depth: int              # maximum AST nesting depth
    local_vars: list[str]       # locally declared variable names
    memory_ops: dict            # {"malloc": 2, "free": 1, ...}
    pointer_ops: int            # count of pointer-related AST nodes
    has_recursion: bool         # calls itself
    loop_count: int             # number of loop nodes
    line_start: int
    line_end: int
    raw_text: str               # full function source text


@dataclass
class FileAST:
    """
    Parsed representation of one version of a file.
    """
    source_hash: str            # sha256 of source bytes — used for cache keying
    functions: dict[str, FunctionInfo] = field(default_factory=dict)
    global_calls: list[str] = field(default_factory=list)  # calls outside functions
    has_parse_errors: bool = False
    error_count: int = 0


# ---------------------------------------------------------------------------
# Recursive AST walker
# ---------------------------------------------------------------------------
def _walk(node: Node, visitor, depth: int = 0):
    """
    DFS walker. visitor(node, depth) is called for every node.

    WHY NOT tree-sitter's built-in walk():
      The built-in TreeCursor is faster for full traversals but awkward when
      you need depth tracking and early-exit logic. For function-level
      analysis (our use case), the trees are small enough that recursive DFS
      is fine and the code is much cleaner.
    """
    visitor(node, depth)
    for child in node.children:
        _walk(child, visitor, depth + 1)


def _max_depth(node: Node, depth: int = 0) -> int:
    if not node.children:
        return depth
    return max(_max_depth(c, depth + 1) for c in node.children)


# ---------------------------------------------------------------------------
# Function-level extractors
# ---------------------------------------------------------------------------
def _extract_name(fn_node: Node) -> Optional[str]:
    """
    Walk the function_declarator to find the identifier name.
    Handles: plain functions, pointer-returning functions (int *foo()),
    and function pointers stored in declarators.
    """
    for child in fn_node.children:
        if child.type == "function_declarator":
            for sub in child.children:
                if sub.type == "identifier":
                    return sub.text.decode("utf8")
                if sub.type == "pointer_declarator":
                    for s2 in sub.children:
                        if s2.type == "identifier":
                            return s2.text.decode("utf8")
    return None


def _extract_return_type(fn_node: Node) -> str:
    """
    Extract the return type declaration. The first non-declarator child of a
    function_definition is the return type specifier. We join multiple tokens
    to handle "unsigned long int", "const char *", etc.
    """
    parts = []
    for child in fn_node.children:
        if child.type in ("function_declarator",):
            break
        if child.type not in ("{", "}", ";"):
            parts.append(child.text.decode("utf8").strip())
    return " ".join(parts) if parts else "unknown"


def _extract_params(fn_node: Node) -> list[str]:
    for child in fn_node.children:
        if child.type == "function_declarator":
            for sub in child.children:
                if sub.type == "parameter_list":
                    return [
                        p.text.decode("utf8").strip()
                        for p in sub.children
                        if p.type == "parameter_declaration"
                    ]
    return []


def _extract_calls(fn_node: Node) -> list[str]:
    calls = []
    def visit(n, _):
        if n.type == "call_expression":
            for c in n.children:
                if c.type == "identifier":
                    calls.append(c.text.decode("utf8"))
    _walk(fn_node, visit)
    return calls


def _extract_local_vars(fn_node: Node) -> list[str]:
    """
    Collect variable names from declaration nodes inside the function.
    We skip the parameter list (those are params, not locals).
    Handles pointer declarators: int *p = malloc(...).
    """
    vars_ = []
    def visit(n, _):
        if n.type == "declaration":
            for c in n.children:
                if c.type == "init_declarator":
                    for s in c.children:
                        if s.type == "identifier":
                            vars_.append(s.text.decode("utf8"))
                        elif s.type == "pointer_declarator":
                            for s2 in s.children:
                                if s2.type == "identifier":
                                    vars_.append(s2.text.decode("utf8"))
    _walk(fn_node, visit)
    return vars_


def _extract_memory_ops(fn_node: Node) -> dict[str, int]:
    """
    Count memory management calls by name.

    WHY THIS IS HIGH-SIGNAL FOR C:
      Memory errors (leaks, double-free, use-after-free) are the dominant
      bug class in C. A function that gains a malloc() without a corresponding
      free(), or vice versa, is a strong candidate for manual review regardless
      of what the code "looks like". Heuristic: malloc_count != free_count
      inside a function is a WARNING-level signal even before LLM analysis.
    """
    counts: dict[str, int] = {}
    def visit(n, _):
        if n.type == "call_expression":
            for c in n.children:
                if c.type == "identifier":
                    name = c.text.decode("utf8")
                    if name in MEMORY_CALLS:
                        counts[name] = counts.get(name, 0) + 1
    _walk(fn_node, visit)
    return counts


def _count_pointer_ops(fn_node: Node) -> int:
    """
    Count pointer-related AST nodes: dereferences, field access (->),
    address-of (&), subscript operations on pointers.

    WHY COUNT, NOT ENUMERATE:
      The exact pointer operations matter less than the density. A function
      that jumps from 3 to 15 pointer operations is a complexity red flag.
      We track the count delta, not the specific operations.
    """
    count = [0]
    def visit(n, _):
        if n.type in POINTER_NODES:
            count[0] += 1
    _walk(fn_node, visit)
    return count[0]


def _cyclomatic_complexity(fn_node: Node) -> int:
    """
    McCabe cyclomatic complexity: 1 + number of decision points.
    Decision points are branch nodes (if, for, while, switch, ternary).

    WHY +1:
      Every function has at least one path through it (the straight-line path).
      Each branch adds one additional independent path. So complexity = 1 +
      number of branches. A function with no branches has complexity 1 (one
      path). This matches the standard McCabe definition.

    THRESHOLDS (industry standard):
      1-5:  simple, low risk
      6-10: moderate complexity, increased test burden
      11+:  complex, high error probability, candidate for refactoring
    """
    count = [1]
    def visit(n, _):
        if n.type in BRANCH_NODES:
            count[0] += 1
    _walk(fn_node, visit)
    return count[0]


# ---------------------------------------------------------------------------
# File-level extraction
# ---------------------------------------------------------------------------
def _count_errors(node: Node) -> int:
    count = [0]
    def visit(n, _):
        if n.type == "ERROR":
            count[0] += 1
    _walk(node, visit)
    return count[0]


def extract_file_ast(source: str) -> FileAST:
    """
    Parse a complete C source file and extract all function-level information.

    This is the only public entry point for parsing. Everything else in the
    pipeline receives FileAST objects, never raw tree-sitter nodes. This
    isolation means we can swap tree-sitter for another parser (e.g. libclang
    for more accurate type information) without touching heuristic or LLM code.
    """
    source_bytes = bytes(source, "utf8")
    source_hash = hashlib.sha256(source_bytes).hexdigest()[:16]

    parser = _make_parser()
    tree = parser.parse(source_bytes)
    root = tree.root_node

    error_count = _count_errors(root)
    file_ast = FileAST(
        source_hash=source_hash,
        has_parse_errors=error_count > 0,
        error_count=error_count,
    )

    # Collect all function definitions at translation-unit level
    # We only look at direct children of the root (top-level functions).
    # Nested functions are a GCC extension; we skip them for now.
    for child in root.children:
        if child.type != "function_definition":
            # Also collect calls at file scope (e.g. in global initializers)
            if child.type == "call_expression":
                for c in child.children:
                    if c.type == "identifier":
                        file_ast.global_calls.append(c.text.decode("utf8"))
            continue

        name = _extract_name(child)
        if not name:
            continue

        calls = _extract_calls(child)
        mem_ops = _extract_memory_ops(child)
        loop_count_val = [0]

        def count_loops(n, _):
            if n.type in LOOP_NODES:
                loop_count_val[0] += 1
        _walk(child, count_loops)

        file_ast.functions[name] = FunctionInfo(
            name=name,
            params=_extract_params(child),
            return_type=_extract_return_type(child),
            calls=calls,
            complexity=_cyclomatic_complexity(child),
            max_depth=_max_depth(child),
            local_vars=_extract_local_vars(child),
            memory_ops=mem_ops,
            pointer_ops=_count_pointer_ops(child),
            has_recursion=name in calls,
            loop_count=loop_count_val[0],
            line_start=child.start_point[0] + 1,
            line_end=child.end_point[0] + 1,
            raw_text=child.text.decode("utf8", errors="replace"),
        )

    return file_ast
