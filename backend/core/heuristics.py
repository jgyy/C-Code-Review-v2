"""
core/heuristics.py — Structural analysis and identity tracking

This module implements the heuristic layer that sits between parsing and LLM.
It computes structural metrics and tracks function identity across diffs to
produce an evidence bundle that guides triage and provides context to the LLM.

Key signals:
- H1: Complexity delta (McCabe before/after)
- H2: Call graph changes (added/removed callers)
- H3: AST depth changes
- H4: Variable tracking (new locals, type changes)
- H5: Orphan detection (functions that lost callers)
- H6: Signature changes (param type/count)
- Memory ops delta (malloc/free balance)
- Pointer density changes
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum

from rapidfuzz import fuzz, process

from core.parser import FileAST, FunctionInfo


class ChangeType(str, Enum):
    ADDED = "added"
    DELETED = "deleted"
    MODIFIED = "modified"
    RENAMED = "renamed"
    UNCHANGED = "unchanged"


@dataclass
class FunctionMatch:
    """
    Represents a matched function pair between before/after versions.
    For renames, old_name != new_name but confidence is high.
    """
    old_name: Optional[str]
    new_name: Optional[str]
    change_type: ChangeType
    confidence: float  # 0-100, for rename detection
    old_info: Optional[FunctionInfo] = None
    new_info: Optional[FunctionInfo] = None


@dataclass
class FunctionEvidence:
    """
    Evidence bundle for a single function change.
    Contains all heuristic signals that inform triage and LLM analysis.
    """
    name: str
    change_type: ChangeType
    
    # H1: Complexity
    complexity_before: int = 0
    complexity_after: int = 0
    complexity_delta: int = 0
    
    # H2: Call graph
    calls_added: list[str] = field(default_factory=list)
    calls_removed: list[str] = field(default_factory=list)
    callers_gained: list[str] = field(default_factory=list)
    callers_lost: list[str] = field(default_factory=list)
    
    # H3: Depth
    depth_before: int = 0
    depth_after: int = 0
    depth_delta: int = 0
    
    # H4: Variables
    vars_added: list[str] = field(default_factory=list)
    vars_removed: list[str] = field(default_factory=list)
    
    # H5: Orphan status
    is_orphan: bool = False  # Lost all callers
    
    # H6: Signature
    params_before: list[str] = field(default_factory=list)
    params_after: list[str] = field(default_factory=list)
    return_type_changed: bool = False
    param_count_delta: int = 0
    
    # Memory safety signals
    memory_ops_before: dict = field(default_factory=dict)
    memory_ops_after: dict = field(default_factory=dict)
    malloc_free_imbalance: int = 0  # malloc_count - free_count delta
    
    # Pointer operations
    pointer_ops_before: int = 0
    pointer_ops_after: int = 0
    pointer_density_delta: float = 0.0
    
    # Loop changes
    loop_count_before: int = 0
    loop_count_after: int = 0
    
    # Recursion
    was_recursive: bool = False
    is_recursive: bool = False
    recursion_changed: bool = False
    
    # Line counts for context
    lines_before: int = 0
    lines_after: int = 0
    line_delta: int = 0
    
    # Rename tracking
    renamed_from: Optional[str] = None
    rename_confidence: float = 0.0


@dataclass
class FileEvidence:
    """Evidence bundle for all changes in a single file."""
    filepath: str
    functions: list[FunctionEvidence] = field(default_factory=list)
    
    # File-level metrics
    total_functions_before: int = 0
    total_functions_after: int = 0
    functions_added: int = 0
    functions_deleted: int = 0
    functions_modified: int = 0
    functions_renamed: int = 0
    
    # Parse quality
    had_parse_errors_before: bool = False
    had_parse_errors_after: bool = False


@dataclass
class PREvidence:
    """Evidence bundle for an entire PR."""
    files: list[FileEvidence] = field(default_factory=list)
    
    # Aggregate metrics
    total_files_changed: int = 0
    total_functions_changed: int = 0
    max_complexity_delta: int = 0
    total_memory_imbalance: int = 0
    has_orphaned_functions: bool = False
    has_signature_changes: bool = False


# ---------------------------------------------------------------------------
# Identity Matching with RapidFuzz
# ---------------------------------------------------------------------------

def match_functions(
    before: FileAST,
    after: FileAST,
    similarity_threshold: float = 70.0
) -> list[FunctionMatch]:
    """
    Match functions between before/after versions of a file.
    
    Uses a multi-pass approach:
    1. Exact name matches
    2. Fuzzy name matching for renames (rapidfuzz)
    3. Signature similarity for remaining candidates
    
    Returns a list of FunctionMatch objects describing the relationship
    between each function in before/after.
    """
    matches: list[FunctionMatch] = []
    matched_before: set[str] = set()
    matched_after: set[str] = set()
    
    before_funcs = set(before.functions.keys())
    after_funcs = set(after.functions.keys())
    
    # Pass 1: Exact name matches
    exact_matches = before_funcs & after_funcs
    for name in exact_matches:
        matches.append(FunctionMatch(
            old_name=name,
            new_name=name,
            change_type=ChangeType.MODIFIED,  # May be unchanged, checked later
            confidence=100.0,
            old_info=before.functions[name],
            new_info=after.functions[name],
        ))
        matched_before.add(name)
        matched_after.add(name)
    
    # Pass 2: Fuzzy matching for potential renames
    unmatched_before = before_funcs - matched_before
    unmatched_after = after_funcs - matched_after
    
    if unmatched_before and unmatched_after:
        for old_name in unmatched_before:
            if old_name in matched_before:
                continue
            
            old_info = before.functions[old_name]
            
            # Use rapidfuzz to find best match by name
            name_matches = process.extract(
                old_name,
                list(unmatched_after - matched_after),
                scorer=fuzz.ratio,
                limit=3
            )
            
            best_match = None
            best_score = 0.0
            
            for new_name, name_score, _ in name_matches:
                if new_name in matched_after:
                    continue
                
                new_info = after.functions[new_name]
                
                # Combine name similarity with signature similarity
                sig_score = _signature_similarity(old_info, new_info)
                
                # Weighted combination: 40% name, 60% signature
                combined_score = 0.4 * name_score + 0.6 * sig_score
                
                if combined_score > best_score and combined_score >= similarity_threshold:
                    best_score = combined_score
                    best_match = new_name
            
            if best_match:
                matches.append(FunctionMatch(
                    old_name=old_name,
                    new_name=best_match,
                    change_type=ChangeType.RENAMED,
                    confidence=best_score,
                    old_info=old_info,
                    new_info=after.functions[best_match],
                ))
                matched_before.add(old_name)
                matched_after.add(best_match)
    
    # Pass 3: Mark unmatched as added/deleted
    for name in before_funcs - matched_before:
        matches.append(FunctionMatch(
            old_name=name,
            new_name=None,
            change_type=ChangeType.DELETED,
            confidence=100.0,
            old_info=before.functions[name],
            new_info=None,
        ))
    
    for name in after_funcs - matched_after:
        matches.append(FunctionMatch(
            old_name=None,
            new_name=name,
            change_type=ChangeType.ADDED,
            confidence=100.0,
            old_info=None,
            new_info=after.functions[name],
        ))
    
    return matches


def _signature_similarity(a: FunctionInfo, b: FunctionInfo) -> float:
    """
    Compute signature similarity between two functions.
    Considers: return type, parameter count, parameter types.
    """
    score = 0.0
    
    # Return type match (30 points)
    if a.return_type == b.return_type:
        score += 30.0
    elif _types_compatible(a.return_type, b.return_type):
        score += 15.0
    
    # Parameter count (30 points)
    if len(a.params) == len(b.params):
        score += 30.0
    else:
        # Partial credit for similar counts
        diff = abs(len(a.params) - len(b.params))
        score += max(0, 30 - diff * 10)
    
    # Parameter types match (40 points)
    if a.params and b.params:
        type_matches = 0
        for p_a, p_b in zip(a.params, b.params):
            if p_a == p_b:
                type_matches += 1
            elif _types_compatible(p_a, p_b):
                type_matches += 0.5
        score += 40.0 * (type_matches / max(len(a.params), len(b.params)))
    elif not a.params and not b.params:
        score += 40.0  # Both have no params
    
    return score


def _types_compatible(type_a: str, type_b: str) -> bool:
    """Check if two type strings are compatible (e.g., 'int' and 'int32_t')."""
    # Normalize types
    a = type_a.lower().replace(" ", "").replace("*", "")
    b = type_b.lower().replace(" ", "").replace("*", "")
    
    # Check for common equivalences
    int_types = {"int", "int32_t", "int32", "long", "size_t", "ssize_t"}
    if a in int_types and b in int_types:
        return True
    
    char_types = {"char", "uint8_t", "int8_t", "byte"}
    if a in char_types and b in char_types:
        return True
    
    return fuzz.ratio(a, b) > 80


# ---------------------------------------------------------------------------
# Evidence Computation
# ---------------------------------------------------------------------------

def compute_function_evidence(match: FunctionMatch, all_callers: dict[str, set[str]]) -> FunctionEvidence:
    """
    Compute the full evidence bundle for a function match.
    
    all_callers: mapping from function name -> set of functions that call it
    """
    old = match.old_info
    new = match.new_info
    
    evidence = FunctionEvidence(
        name=match.new_name or match.old_name or "unknown",
        change_type=match.change_type,
    )
    
    if match.change_type == ChangeType.RENAMED:
        evidence.renamed_from = match.old_name
        evidence.rename_confidence = match.confidence
    
    # Handle added/deleted functions
    if match.change_type == ChangeType.ADDED:
        evidence.complexity_after = new.complexity if new else 0
        evidence.depth_after = new.max_depth if new else 0
        evidence.pointer_ops_after = new.pointer_ops if new else 0
        evidence.memory_ops_after = new.memory_ops if new else {}
        evidence.loop_count_after = new.loop_count if new else 0
        evidence.is_recursive = new.has_recursion if new else False
        evidence.lines_after = (new.line_end - new.line_start + 1) if new else 0
        evidence.params_after = new.params if new else []
        return evidence
    
    if match.change_type == ChangeType.DELETED:
        evidence.complexity_before = old.complexity if old else 0
        evidence.depth_before = old.max_depth if old else 0
        evidence.pointer_ops_before = old.pointer_ops if old else 0
        evidence.memory_ops_before = old.memory_ops if old else {}
        evidence.loop_count_before = old.loop_count if old else 0
        evidence.was_recursive = old.has_recursion if old else False
        evidence.lines_before = (old.line_end - old.line_start + 1) if old else 0
        evidence.params_before = old.params if old else []
        
        # Track callers that are now broken (deleted function had live callers).
        # This is the most dangerous signal for a deletion: callers exist in the
        # before-AST that call this function, but the function is now gone.
        callers = all_callers.get(match.old_name, set())
        if callers:
            evidence.callers_lost = list(callers)

        return evidence
    
    # Modified/Renamed - compare before and after
    if old and new:
        # H1: Complexity
        evidence.complexity_before = old.complexity
        evidence.complexity_after = new.complexity
        evidence.complexity_delta = new.complexity - old.complexity
        
        # H2: Call graph
        old_calls = set(old.calls)
        new_calls = set(new.calls)
        evidence.calls_added = list(new_calls - old_calls)
        evidence.calls_removed = list(old_calls - new_calls)
        
        # H3: Depth
        evidence.depth_before = old.max_depth
        evidence.depth_after = new.max_depth
        evidence.depth_delta = new.max_depth - old.max_depth
        
        # H4: Variables
        old_vars = set(old.local_vars)
        new_vars = set(new.local_vars)
        evidence.vars_added = list(new_vars - old_vars)
        evidence.vars_removed = list(old_vars - new_vars)
        
        # H6: Signature
        evidence.params_before = old.params
        evidence.params_after = new.params
        evidence.return_type_changed = old.return_type != new.return_type
        evidence.param_count_delta = len(new.params) - len(old.params)
        
        # Memory safety
        evidence.memory_ops_before = old.memory_ops
        evidence.memory_ops_after = new.memory_ops
        
        old_balance = old.memory_ops.get("malloc", 0) - old.memory_ops.get("free", 0)
        new_balance = new.memory_ops.get("malloc", 0) - new.memory_ops.get("free", 0)
        evidence.malloc_free_imbalance = new_balance - old_balance
        
        # Pointer density
        evidence.pointer_ops_before = old.pointer_ops
        evidence.pointer_ops_after = new.pointer_ops
        
        old_lines = old.line_end - old.line_start + 1
        new_lines = new.line_end - new.line_start + 1
        
        old_density = old.pointer_ops / old_lines if old_lines > 0 else 0
        new_density = new.pointer_ops / new_lines if new_lines > 0 else 0
        evidence.pointer_density_delta = new_density - old_density
        
        # Loops
        evidence.loop_count_before = old.loop_count
        evidence.loop_count_after = new.loop_count
        
        # Recursion
        evidence.was_recursive = old.has_recursion
        evidence.is_recursive = new.has_recursion
        evidence.recursion_changed = old.has_recursion != new.has_recursion
        
        # Line counts
        evidence.lines_before = old_lines
        evidence.lines_after = new_lines
        evidence.line_delta = new_lines - old_lines
        
        # Check if function is actually unchanged
        if _functions_identical(old, new):
            evidence.change_type = ChangeType.UNCHANGED
    
    return evidence


def _functions_identical(a: FunctionInfo, b: FunctionInfo) -> bool:
    """Check if two functions are semantically identical."""
    return (
        a.complexity == b.complexity and
        a.max_depth == b.max_depth and
        a.params == b.params and
        a.return_type == b.return_type and
        a.calls == b.calls and
        a.local_vars == b.local_vars and
        a.memory_ops == b.memory_ops and
        a.pointer_ops == b.pointer_ops and
        a.has_recursion == b.has_recursion
    )


def compute_file_evidence(filepath: str, before: FileAST, after: FileAST) -> FileEvidence:
    """Compute evidence for all function changes in a file."""
    evidence = FileEvidence(
        filepath=filepath,
        total_functions_before=len(before.functions),
        total_functions_after=len(after.functions),
        had_parse_errors_before=before.has_parse_errors,
        had_parse_errors_after=after.has_parse_errors,
    )
    
    # Build call graphs for orphan detection and caller tracking.
    # before_callers: callee -> set of functions that called it in the before-AST.
    # after_callers:  callee -> set of functions that call it in the after-AST.
    # Both are needed to compute callers_gained/callers_lost for modified functions
    # and to detect deletions that leave dangling callers (the most dangerous signal).
    before_callers: dict[str, set[str]] = {}
    for name, func in before.functions.items():
        for callee in func.calls:
            before_callers.setdefault(callee, set()).add(name)

    after_callers: dict[str, set[str]] = {}
    for name, func in after.functions.items():
        for callee in func.calls:
            after_callers.setdefault(callee, set()).add(name)

    # Match functions
    matches = match_functions(before, after)

    for match in matches:
        func_evidence = compute_function_evidence(match, before_callers)

        # Skip unchanged functions
        if func_evidence.change_type == ChangeType.UNCHANGED:
            continue

        # Refine callers_gained / callers_lost for all change types using both
        # call graphs.  compute_function_evidence already handles the simple
        # deletion case; here we add the richer before/after comparison.
        effective_before_name = match.old_name
        effective_after_name = match.new_name

        if effective_before_name and effective_after_name:
            # Modified or renamed: compare caller sets across the two graphs.
            b_callers = before_callers.get(effective_before_name, set())
            a_callers = after_callers.get(effective_after_name, set())
            func_evidence.callers_gained = list(a_callers - b_callers)
            func_evidence.callers_lost = list(b_callers - a_callers)
            # A modified function is orphaned if it had callers before and has none now.
            if b_callers and not a_callers:
                func_evidence.is_orphan = True
        elif effective_before_name and not effective_after_name:
            # Deleted: callers_lost already set by compute_function_evidence.
            # is_orphan is not meaningful here — the function is gone, but
            # callers_lost tells us who is now broken.
            pass

        evidence.functions.append(func_evidence)

        # Update counts
        if match.change_type == ChangeType.ADDED:
            evidence.functions_added += 1
        elif match.change_type == ChangeType.DELETED:
            evidence.functions_deleted += 1
        elif match.change_type == ChangeType.RENAMED:
            evidence.functions_renamed += 1
        else:
            evidence.functions_modified += 1

    return evidence


def compute_pr_evidence(file_evidences: list[FileEvidence]) -> PREvidence:
    """Aggregate file-level evidence into PR-level evidence."""
    pr = PREvidence(
        files=file_evidences,
        total_files_changed=len(file_evidences),
    )
    
    for file_ev in file_evidences:
        for func_ev in file_ev.functions:
            pr.total_functions_changed += 1
            pr.max_complexity_delta = max(pr.max_complexity_delta, abs(func_ev.complexity_delta))
            pr.total_memory_imbalance += abs(func_ev.malloc_free_imbalance)
            
            if func_ev.is_orphan:
                pr.has_orphaned_functions = True
            
            if func_ev.return_type_changed or func_ev.param_count_delta != 0:
                pr.has_signature_changes = True
    
    return pr