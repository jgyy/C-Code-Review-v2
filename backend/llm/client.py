"""
llm/client.py — Gemini API client for code analysis

Model selection:
- gemini-2.5-flash-lite: default for all analysis (fast, cheap, large context)
- gemini-2.5-flash: used only for CRITICAL-risk PRs (stronger reasoning)

OPTIMISATION SUMMARY (compared to original):
─────────────────────────────────────────────
1. BOUNDED LLM CALLS
   The original deep-analysis path fired one LLM call per changed function
   with no cap — O(N) calls, guaranteed rate-limit failure on large PRs.
   Now there is exactly ONE LLM call per PR, always. Triage pre-selects the
   top MAX_FUNCTIONS_FOR_LLM (15) highest-risk functions; the single prompt
   contains their evidence + code. All other functions get static-analysis
   results from triage signals.

2. RETRY WITH EXPONENTIAL BACKOFF
   The original had no retry logic. A 429 (rate limit) or transient 5xx from
   Gemini silently produced a fallback result. Now _call_gemini retries up to
   MAX_RETRIES (3) times with jittered exponential backoff, only falling back
   to static analysis after all retries are exhausted.

3. PROMPT TOKEN BUDGETING
   _build_context now takes only the triage-selected functions (up to
   MAX_EVIDENCE_FOR_FAST_PATH = 30 evidence rows) rather than all changed
   functions. Code snippets are included only for functions above
   MIN_RISK_SCORE_FOR_SNIPPET (30) and are hard-truncated at
   MAX_SNIPPET_CHARS (1500) each. This keeps the prompt well within a
   predictable token range regardless of PR size.

4. MODEL SELECTION BY RISK
   CRITICAL-risk PRs use gemini-2.5-flash (stronger reasoning).
   Everything else uses gemini-2.5-flash-lite (faster, cheaper, higher RPM).
   This concentrates the expensive model budget where it matters most.

5. STATIC-ANALYSIS FALLBACK FOR UNSELECTED FUNCTIONS
   Functions not sent to the LLM receive a FunctionAnalysisOutput synthesised
   entirely from triage signals (risk score, signals list). No LLM call, no
   token cost, but the result object is indistinguishable from an LLM result
   at the API layer — the frontend doesn't need to change.

6. LLM RESULT CACHING
   Each function's analysis is cached in Redis keyed by a hash of its
   before+after source text. Identical functions in different PRs (e.g. a
   function touched repeatedly across a stack of PRs) are never re-analysed.
   TTL matches RESULT_TTL (7 days).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import random
from typing import Any, Optional

from dotenv import load_dotenv
from google import genai
from google.genai import types
import anthropic

from cache.redis import _get_redis
from core.heuristics import ChangeType, FunctionEvidence, PREvidence
from core.parser import FileAST
from core.triage import (
    MAX_EVIDENCE_FOR_FAST_PATH,
    MIN_RISK_SCORE_FOR_SNIPPET,
    RiskLevel,
    TriageResult,
)
from llm.prompts import (
    SYSTEM_PROMPT_FAST_PATH,
    SYSTEM_PROMPT_MERMAID,
    build_fast_path_prompt,
    build_mermaid_prompt,
)
from llm.schemas import FunctionAnalysisOutput, PRAnalysis

logger = logging.getLogger(__name__)


def build_reverse_call_graph(
    file_asts: dict[str, tuple[FileAST, FileAST]],
) -> dict[str, set[str]]:
    """
    Build a callee → set-of-callers map from the after-AST of every file.

    Used by _build_context to annotate each LLM-selected function with the
    chain of functions that call it (up to depth 3), giving the LLM visibility
    into the blast radius of changes to that function.
    """
    reverse: dict[str, set[str]] = {}
    for _, (_, after_ast) in file_asts.items():
        for caller_name, func_info in after_ast.functions.items():
            for callee in func_info.calls:
                reverse.setdefault(callee, set()).add(caller_name)
    return reverse


def _walk_callers(
    func_name: str,
    reverse_graph: dict[str, set[str]],
    max_depth: int = 3,
) -> list[str]:
    """
    BFS upward through the reverse call graph to find the caller chain.

    Returns a flat list of caller names reachable within max_depth steps,
    ordered BFS level by level (immediate callers first).  Cycles are
    handled by a visited set so we never loop.
    """
    visited: set[str] = {func_name}
    frontier: set[str] = {func_name}
    result: list[str] = []
    for _ in range(max_depth):
        next_frontier: set[str] = set()
        for node in frontier:
            for caller in reverse_graph.get(node, set()):
                if caller not in visited:
                    visited.add(caller)
                    next_frontier.add(caller)
                    result.append(caller)
        frontier = next_frontier
        if not frontier:
            break
    return result

def find_top_feature_entry_point(
    file_asts: dict[str, tuple[FileAST, FileAST]],
    changed_function_names: set[str],
    top_n: int = 3,
) -> list[tuple[str, int, float]]:
    """
    Identify the most likely "feature entry point" added or modified by this PR.

    Strategy:
    1. Build a forward call graph from the after-AST of all files.
    2. Find root functions — those with zero in-degree in the call graph
       (no other function in the AST calls them).  These are the externally
       visible entry points.
    3. From each root, DFS to find the maximum reachable call depth and the
       fraction of reachable nodes that are in `changed_function_names`.
    4. Score = depth × fraction_changed.  Higher score → better proxy for
       "this is the root of the new feature."

    Returns up to top_n results as (func_name, max_depth, fraction_changed),
    sorted by score descending.

    An empty list is returned if there are no changed functions or no roots
    can be identified (e.g. every function is called by another — a fully
    internal refactor with no new entry points).
    """
    if not changed_function_names:
        return []

    # Build forward call graph: caller → set of callees (after-AST only)
    forward: dict[str, set[str]] = {}
    all_functions: set[str] = set()
    for _, (_, after_ast) in file_asts.items():
        for name, func_info in after_ast.functions.items():
            all_functions.add(name)
            forward.setdefault(name, set()).update(func_info.calls)

    # in-degree: how many functions in the after-AST call each function
    in_degree: dict[str, int] = {name: 0 for name in all_functions}
    for caller, callees in forward.items():
        for callee in callees:
            if callee in in_degree:
                in_degree[callee] += 1

    roots = {name for name, deg in in_degree.items() if deg == 0}
    # Only consider roots that are themselves changed or reach changed functions
    if not roots:
        return []

    def dfs_stats(start: str) -> tuple[int, int]:
        """Return (max_depth, count_of_changed_reachable_nodes) from start."""
        visited: set[str] = set()
        max_depth_found = [0]
        changed_count = [0]

        def _dfs(node: str, depth: int) -> None:
            if node in visited:
                return
            visited.add(node)
            if depth > max_depth_found[0]:
                max_depth_found[0] = depth
            if node in changed_function_names:
                changed_count[0] += 1
            for callee in forward.get(node, set()):
                _dfs(callee, depth + 1)

        _dfs(start, 0)
        return max_depth_found[0], changed_count[0]

    scored: list[tuple[str, int, float]] = []
    for root in roots:
        depth, n_changed = dfs_stats(root)
        reachable_total = depth + 1  # rough proxy; avoids a second traversal
        fraction = n_changed / max(reachable_total, 1)
        score = depth * fraction
        if score > 0:  # skip roots with no changed descendants
            scored.append((root, depth, fraction))

    scored.sort(key=lambda x: x[1] * x[2], reverse=True)
    return scored[:top_n]

# ---------------------------------------------------------------------------
# Retry / rate-limit constants
# ---------------------------------------------------------------------------

# Maximum number of retry attempts on transient errors (429, 503, etc.)
MAX_RETRIES = 3

# Base delay in seconds for exponential backoff. Actual delay is:
#   min(BACKOFF_BASE * 2**attempt + jitter, BACKOFF_MAX)
BACKOFF_BASE = 2.0
BACKOFF_MAX = 30.0

# HTTP status codes that warrant a retry
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# Max characters per code snippet included in the prompt.
# A 1500-char snippet is ~375 tokens; 15 snippets ≈ 5600 tokens.
MAX_SNIPPET_CHARS = 1500

# Cache TTL for LLM function analysis results (seconds). Matches RESULT_TTL.
LLM_CACHE_TTL = 86400 * 7  # 7 days

# How many times to ask the LLM to fix an invalid Mermaid diagram before
# giving up and dropping it. Each attempt is a small, cheap follow-up call
# (just the diagram, not the full PR analysis) — not a full re-analysis retry.
MAX_MERMAID_FIX_ATTEMPTS = 2

# Recognised Mermaid diagram-type headers. We only ever ask for "flowchart TD"
# but accept "graph" too since some models default to the older syntax name.
_MERMAID_VALID_HEADERS = ("flowchart", "graph")


def _validate_mermaid_syntax(diagram: str) -> Optional[str]:
    """
    Lightweight structural validator for the constrained Mermaid subset we
    ask the LLM to produce (see the "Mermaid diagram" section of
    SYSTEM_PROMPT_FAST_PATH). This is NOT a full Mermaid grammar parser —
    it's a fast, dependency-free sanity check that catches the failure modes
    LLMs actually produce: unbalanced brackets, wrong/missing header, code
    fences leaking through, empty output.

    Returns None if the diagram looks structurally valid, otherwise a short
    human-readable description of what's wrong (fed back to the LLM so it
    can fix it).
    """
    if not diagram or not diagram.strip():
        return "empty diagram"

    text = diagram.strip()

    # Reject markdown fences / HTML the model sometimes adds despite instructions.
    if "```" in text:
        return "contains a markdown code fence — output raw Mermaid only, no ``` fences"
    if "<" in text and ">" in text:
        return "contains what looks like an HTML tag — Mermaid flowchart syntax only, no HTML"

    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return "empty diagram"

    header = lines[0].strip().lower()
    if not any(header.startswith(h) for h in _MERMAID_VALID_HEADERS):
        return f"first line must be 'flowchart TD', got: {lines[0]!r}"

    if len(lines) < 2:
        return "diagram has a header but no edges/nodes"

    # Balanced-delimiter check across the whole diagram body.
    pairs = {"[": "]", "(": ")", "{": "}"}
    closers = set(pairs.values())
    stack: list[str] = []
    in_quote = False
    for ch in text:
        if ch == '"':
            in_quote = not in_quote
            continue
        if in_quote:
            continue
        if ch in pairs:
            stack.append(pairs[ch])
        elif ch in closers:
            if not stack or stack[-1] != ch:
                return f"unbalanced bracket near {ch!r} — every [, (, {{ needs a matching closer"
            stack.pop()
    if in_quote:
        return "unbalanced quote (\") somewhere in a node label"
    if stack:
        return f"unclosed bracket(s): missing {''.join(reversed(stack))!r}"

    return None


class BaseLLMClient:
    """
    Shared logic for LLM-backed PR analysis (prompt building, caching, retry,
    response parsing, fallbacks). Subclasses only need to set up their own
    provider client in __init__ and implement _call_llm_api().

    One LLM call per PR. All rate-limit and token-budget concerns are handled
    internally; callers just call analyze() and get a PRAnalysis back.
    """

    #: Human-readable provider name, used in status/fallback messages.
    provider_label: str = "LLM"
    #: Name of the environment variable holding this provider's API key,
    #: surfaced in the "not configured" message.
    api_key_env_var: str = "LLM_API_KEY"

    def __init__(
        self,
        api_key: Optional[str] = None,
        fast_model: str = "",
        deep_model: str = "",
    ):
        self.api_key = api_key
        self.fast_model = fast_model
        self.deep_model = deep_model
        self.client: Optional[Any] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def analyze(  # noqa: keep signature identical across subclasses
        self,
        pr_evidence: PREvidence,
        triage_result: TriageResult,
        file_asts: dict[str, tuple[FileAST, FileAST]],
    ) -> PRAnalysis:
        """
        Analyse a PR with a single LLM call.

        Functions selected by triage (llm_selected_functions) are sent to the
        LLM. All other changed functions receive static-analysis-only results.
        """
        if not self.client:
            return self._mock_analysis(pr_evidence, triage_result)

        # Build static results for ALL functions upfront.
        # LLM results will overwrite entries for selected functions below.
        all_function_results = self._static_results_for_all(triage_result)

        # Choose model based on overall risk level
        model = (
            self.deep_model
            if triage_result.overall_risk_level == RiskLevel.CRITICAL
            else self.fast_model
        )
        logger.info(
            f"Using model={model} for risk={triage_result.overall_risk_level.value}, "
            f"llm_functions={triage_result.llm_selected_functions}, "
            f"static_only={triage_result.unanalysed_function_count}"
        )

        # Check cache for each selected function; collect cache misses
        selected = triage_result.llm_selected_functions
        cached_results, uncached_selected = await self._check_function_cache(
            selected, file_asts
        )

        # Merge cached results into all_function_results
        for name, fa in cached_results.items():
            all_function_results[name] = fa
            logger.info(f"Cache hit for function analysis: {name}")

        # Build the PR-level cache key from the selected function names + scores.
        # This key is stable across re-runs of the same PR as long as triage picks
        # the same top-N (which it does deterministically for identical code).
        pr_cache_key = self._pr_summary_cache_key(triage_result)

        # If all selected functions were cached, try to restore the PR-level summary too
        if not uncached_selected:
            logger.info("All selected functions served from cache — checking PR summary cache")
            cached_pr = await self._get_pr_summary_cache(pr_cache_key)
            if cached_pr:
                logger.info("PR summary cache hit — skipping LLM call entirely")
                cached_pr.function_analyses = list(all_function_results.values())
                return cached_pr
            # Function results are cached but no PR summary yet — still call LLM
            logger.info("PR summary cache miss — calling LLM for summary (functions already cached)")

        # Build prompt with uncached functions only (or all if PR summary was missing)
        functions_for_prompt = uncached_selected if uncached_selected else list(triage_result.llm_selected_functions)
        context = self._build_context(
            pr_evidence=pr_evidence,
            triage_result=triage_result,
            file_asts=file_asts,
            selected_functions=functions_for_prompt,
        )
        user_prompt = build_fast_path_prompt(context)

        try:
            logger.info(f"user_prompt: {user_prompt}")
            response = await self._call_gemini(
                system_prompt=SYSTEM_PROMPT_FAST_PATH,
                user_prompt=user_prompt,
                model=model,
            )
            logger.info(f"LLM response: {response}")
            pr_analysis = self._parse_pr_analysis(response, triage_result)

            # Diagram is generated as a SEPARATE call (see _generate_mermaid_diagram
            # docstring for why) so a bad diagram never risks the main analysis parse.
            pr_analysis.mermaid_diagram = await self._generate_mermaid_diagram(context, model)

            # Overwrite static results with LLM results for selected functions
            for fa in pr_analysis.function_analyses:
                all_function_results[fa.name] = fa

            # Cache per-function LLM results (only for newly computed ones)
            await self._cache_function_results(
                pr_analysis.function_analyses, functions_for_prompt, file_asts
            )

            # Attach the full function list (LLM + static) to the PR analysis
            pr_analysis.function_analyses = list(all_function_results.values())

            # Cache the PR-level summary so re-runs skip the LLM call entirely
            await self._set_pr_summary_cache(pr_cache_key, pr_analysis)

            return pr_analysis

        except Exception as e:
            logger.exception(f"Gemini analysis failed after retries: {e}")
            return self._fallback_analysis(pr_evidence, triage_result, str(e))

    # Keep the old method names as thin wrappers so webhook.py / pipeline.py
    # don't need to change.
    async def analyze_fast_path(
        self,
        pr_evidence: PREvidence,
        triage_result: TriageResult,
        file_asts: dict[str, tuple[FileAST, FileAST]],
    ) -> PRAnalysis:
        return await self.analyze(pr_evidence, triage_result, file_asts)

    async def analyze_deep(
        self,
        pr_evidence: PREvidence,
        triage_result: TriageResult,
        file_asts: dict[str, tuple[FileAST, FileAST]],
    ) -> PRAnalysis:
        return await self.analyze(pr_evidence, triage_result, file_asts)

    # ------------------------------------------------------------------
    # LLM call with retry + backoff
    # ------------------------------------------------------------------

    def _call_llm_api(
        self, system_prompt: str, user_prompt: str, model: str, json_mode: bool = True
    ) -> str:
        """
        Provider-specific synchronous API call. Must be implemented by
        subclasses. Runs inside asyncio.to_thread() by _call_gemini().

        json_mode controls whether the provider is told to constrain output
        to JSON (e.g. Gemini's response_mime_type). Pass False for prompts
        that ask for plain-text output (e.g. the Mermaid diagram) — forcing
        JSON mode there makes some providers wrap the answer in a JSON
        envelope instead of returning the requested plain text.
        """
        raise NotImplementedError

    async def _call_gemini(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        json_mode: bool = True,
    ) -> str:
        """
        Call the configured LLM provider with exponential backoff retry on
        transient errors. (Named _call_gemini for backwards compatibility —
        it dispatches to whichever provider this client wraps.)

        Retries on:
        - 429 Too Many Requests (rate limit)
        - 500/502/503/504 transient server errors

        Does NOT retry on:
        - 400 Bad Request (prompt/config issue — won't self-heal)
        - 401/403 Auth errors

        Jitter is added to backoff delay to avoid thundering-herd when multiple
        worker Lambdas are running concurrently against the same API key.
        """
        if not self.client:
            raise RuntimeError(f"{self.provider_label} client not initialized")

        last_exception: Exception = RuntimeError("No attempts made")

        for attempt in range(MAX_RETRIES):
            try:
                result = await asyncio.to_thread(
                    self._call_llm_api, system_prompt, user_prompt, model, json_mode
                )
                if attempt > 0:
                    logger.info(f"{self.provider_label} call succeeded on attempt {attempt + 1}")
                return result

            except Exception as e:
                last_exception = e
                error_str = str(e).lower()

                # Check if this looks like a retryable error
                is_retryable = (
                    "429" in error_str
                    or "quota" in error_str
                    or "rate" in error_str
                    or "503" in error_str
                    or "502" in error_str
                    or "500" in error_str
                    or "unavailable" in error_str
                    or "overloaded" in error_str
                )

                if not is_retryable or attempt == MAX_RETRIES - 1:
                    logger.error(
                        f"{self.provider_label} call failed (attempt {attempt + 1}/{MAX_RETRIES},"
                        f" non-retryable or out of retries): {e}"
                    )
                    raise

                delay = min(BACKOFF_BASE * (2 ** attempt), BACKOFF_MAX)
                jitter = random.uniform(0, delay * 0.2)
                wait = delay + jitter
                logger.warning(
                    f"{self.provider_label} call failed (attempt {attempt + 1}/{MAX_RETRIES}): {e}. "
                    f"Retrying in {wait:.1f}s"
                )
                await asyncio.sleep(wait)

        raise last_exception

    # ------------------------------------------------------------------
    # Mermaid diagram generation / validation / repair
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_diagram_fences(text: str) -> str:
        """Strip stray markdown code fences a model might add despite instructions."""
        candidate = text.strip()
        if candidate.startswith("```"):
            candidate = candidate.strip("`")
            if candidate.lower().startswith("mermaid"):
                candidate = candidate[len("mermaid"):]
            candidate = candidate.strip()
        return candidate

    async def _generate_mermaid_diagram(
        self, context: dict, model: str
    ) -> Optional[str]:
        """
        Generate the Mermaid change-impact diagram as a SEPARATE, plain-text
        LLM call — deliberately not a field in the main structured-JSON
        analysis. A multi-line diagram string with quotes/newlines is exactly
        the kind of value that breaks strict JSON parsing when a model
        doesn't escape it perfectly, and a parse failure there would take
        down the entire PR analysis, not just the diagram. Isolating it means
        a bad diagram just means "no diagram" — everything else still works.

        Validates the result and asks the LLM to fix it (up to
        MAX_MERMAID_FIX_ATTEMPTS times) before giving up and returning None.
        """
        try:
            raw = await self._call_gemini(
                system_prompt=SYSTEM_PROMPT_MERMAID,
                user_prompt=build_mermaid_prompt(context),
                model=model,
                json_mode=False,
            )
        except Exception as e:
            logger.warning(f"Mermaid diagram generation call failed: {e}")
            return None

        candidate = self._strip_diagram_fences(raw)
        if not candidate or candidate.strip().upper() == "NONE":
            return None

        error = _validate_mermaid_syntax(candidate)
        if error is None:
            return candidate

        for attempt in range(1, MAX_MERMAID_FIX_ATTEMPTS + 1):
            logger.warning(
                f"Mermaid diagram invalid (attempt {attempt}/{MAX_MERMAID_FIX_ATTEMPTS}): {error}"
            )
            try:
                fixed = await self._call_gemini(
                    system_prompt=SYSTEM_PROMPT_MERMAID,
                    user_prompt=(
                        f"Validation error in the diagram you produced: {error}\n\n"
                        f"Broken diagram:\n{candidate}\n\n"
                        "Respond with ONLY the corrected Mermaid source (or NONE)."
                    ),
                    model=model,
                    json_mode=False,
                )
            except Exception as e:
                logger.warning(f"Mermaid fix attempt {attempt} call failed: {e}")
                return None

            candidate = self._strip_diagram_fences(fixed)
            if not candidate or candidate.strip().upper() == "NONE":
                return None

            error = _validate_mermaid_syntax(candidate)
            if error is None:
                logger.info(f"Mermaid diagram fixed on attempt {attempt}")
                return candidate

        logger.warning(
            f"Mermaid diagram still invalid after {MAX_MERMAID_FIX_ATTEMPTS} fix attempts "
            f"({error}) — dropping it"
        )
        return None

    # ------------------------------------------------------------------
    # Context / prompt building
    # ------------------------------------------------------------------

    def _build_context(
        self,
        pr_evidence: PREvidence,
        triage_result: TriageResult,
        file_asts: dict[str, tuple[FileAST, FileAST]],
        selected_functions: list,  # list[FunctionRisk] — already ranked by triage
    ) -> dict:
        """
        Build the prompt context dict.

        Only includes the top MAX_EVIDENCE_FOR_FAST_PATH functions by risk
        score (already ranked by triage). Code snippets are included only for
        functions above MIN_RISK_SCORE_FOR_SNIPPET and truncated at
        MAX_SNIPPET_CHARS each.
        """
        # Build a quick lookup: (filepath, func_name) -> FunctionEvidence
        logger.info(f"build context")
        logger.info(f"build context | pr_evidence: {pr_evidence}")
        logger.info(f"build context | triage_result: {triage_result}")
        logger.info(f"build context | file_asts: {file_asts}")
        logger.info(f"build context | selected_functions: {selected_functions}")

        evidence_lookup: dict[tuple[str, str], FunctionEvidence] = {
            (file_ev.filepath, func_ev.name): func_ev
            for file_ev in pr_evidence.files
            for func_ev in file_ev.functions
        }

        # Reverse call graph for caller-chain annotation (fix 2)
        reverse_graph = build_reverse_call_graph(file_asts)

        # Top feature entry points (fix 4)
        changed_names: set[str] = {
            func_ev.name
            for file_ev in pr_evidence.files
            for func_ev in file_ev.functions
        }
        top_features = find_top_feature_entry_point(file_asts, changed_names)

        # Cap evidence rows sent to the prompt
        capped = selected_functions[:MAX_EVIDENCE_FOR_FAST_PATH]

        function_evidences = []
        code_snippets: dict[str, str] = {}

        for func_risk in capped:
            key = (func_risk.filepath, func_risk.name)
            func_ev = evidence_lookup.get(key)
            if not func_ev:
                continue

            fe_dict = {
                "name": func_ev.name,
                "filepath": func_risk.filepath,
                "change_type": func_ev.change_type.value,
                "complexity_before": func_ev.complexity_before,
                "complexity_after": func_ev.complexity_after,
                "complexity_delta": func_ev.complexity_delta,
                "malloc_free_imbalance": func_ev.malloc_free_imbalance,
                "return_type_changed": func_ev.return_type_changed,
                "calls_added": func_ev.calls_added,
                "calls_removed": func_ev.calls_removed,
                "callers_lost": func_ev.callers_lost,   # fix 3b
                "caller_chain": _walk_callers(           # fix 2
                    func_ev.name, reverse_graph, max_depth=3
                ),
                "risk_score": func_risk.risk_score,
                "risk_signals": func_risk.signals,
            }
            function_evidences.append(fe_dict)

            # Include code snippet only for high-enough risk functions
            if func_risk.risk_score >= MIN_RISK_SCORE_FOR_SNIPPET:
                before_ast, after_ast = file_asts.get(
                    func_risk.filepath, (FileAST(""), FileAST(""))
                )
                snippet = self._get_snippet(func_ev, before_ast, after_ast)
                if snippet:
                    code_snippets[func_ev.name] = snippet

        # Callee snippets: for each selected function, include source of callees
        # that also exist in the AST but aren't already in code_snippets.
        # This gives the LLM the full context of what a newly-added call does,
        # not just that the call was added.
        # Budget: max 5 callee snippets total, prioritised by the risk score of
        # the calling function (highest-risk function's callees first).
        MAX_CALLEE_SNIPPETS = 5
        callee_snippets: dict[str, str] = {}
        for func_risk in capped:
            if len(callee_snippets) >= MAX_CALLEE_SNIPPETS:
                break
            key = (func_risk.filepath, func_risk.name)
            func_ev = evidence_lookup.get(key)
            if not func_ev:
                continue
            # Only look at newly added calls — these are the unknown quantities
            for callee_name in func_ev.calls_added:
                if len(callee_snippets) >= MAX_CALLEE_SNIPPETS:
                    break
                if callee_name in code_snippets or callee_name in callee_snippets:
                    continue  # already included
                # Search all after-ASTs for the callee's definition
                for _filepath, (_, after_ast) in file_asts.items():
                    if callee_name in after_ast.functions:
                        raw = after_ast.functions[callee_name].raw_text
                        if raw:
                            if len(raw) > MAX_SNIPPET_CHARS:
                                raw = raw[:MAX_SNIPPET_CHARS] + "\n// ... (truncated)"
                            callee_snippets[callee_name] = raw
                        break

        # Summarise the functions that weren't selected to give the LLM
        # awareness of the full scope without sending all the details
        omitted_summary = ""
        if triage_result.unanalysed_function_count > 0:
            omitted_summary = (
                f"{triage_result.unanalysed_function_count} additional lower-risk functions "
                f"were changed but are not shown here "
                f"({triage_result.unanalysed_high_risk_count} of them scored HIGH/CRITICAL "
                f"by static analysis)."
            )

        return {
            "repo_name": f"PR#{pr_evidence.total_files_changed}files",
            "pr_number": 0,
            "overall_risk_score": triage_result.overall_risk_score,
            "overall_risk_level": triage_result.overall_risk_level.value,
            "triage_reasoning": triage_result.reasoning,
            "function_evidences": function_evidences,
            "code_snippets": code_snippets,
            "callee_snippets": callee_snippets,
            "top_feature_entry_points": [
                {"name": name, "call_depth": depth, "fraction_changed": round(frac, 2)}
                for name, depth, frac in top_features
            ],
            "omitted_functions_summary": omitted_summary,
            # Files whose content couldn't be fetched — NOT analysed, NOT
            # evidence of deletion. Told to the LLM explicitly so it can't
            # infer "deleted" from their absence in the evidence above.
            "files_with_fetch_errors": list(pr_evidence.files_with_fetch_errors),
        }

    def _get_snippet(
        self,
        func_ev: FunctionEvidence,
        before_ast: FileAST,
        after_ast: FileAST,
    ) -> str:
        """
        Return the most relevant code snippet for a function: after-version
        for modifications/additions, before-version for deletions.
        Truncated to MAX_SNIPPET_CHARS.
        """
        text = ""
        if func_ev.change_type == ChangeType.DELETED:
            name_before = func_ev.renamed_from or func_ev.name
            if name_before in before_ast.functions:
                text = before_ast.functions[name_before].raw_text
        else:
            if func_ev.name in after_ast.functions:
                text = after_ast.functions[func_ev.name].raw_text

        if len(text) > MAX_SNIPPET_CHARS:
            text = text[:MAX_SNIPPET_CHARS] + "\n// ... (truncated)"
        return text

    # ------------------------------------------------------------------
    # Function-level caching
    # ------------------------------------------------------------------

    @staticmethod
    def _function_cache_key(
        func_name: str,
        code_before: str,
        code_after: str,
    ) -> str:
        """
        Cache key for a function analysis result.
        Keyed on the actual source text so identical functions across different
        PRs or commits share the same cache entry.
        """
        payload = f"{func_name}::{code_before}::{code_after}".encode()
        return "llm_fn:" + hashlib.sha256(payload).hexdigest()[:20]

    async def _check_function_cache(
        self,
        selected: list,  # list[FunctionRisk]
        file_asts: dict[str, tuple[FileAST, FileAST]],
    ) -> tuple[dict[str, FunctionAnalysisOutput], list]:
        """
        Check Redis cache for each selected function's analysis.
        Returns (cached_results_by_name, uncached_function_risks).
        """
        rc = _get_redis()
        if not rc:
            return {}, selected

        cached: dict[str, FunctionAnalysisOutput] = {}
        uncached = []

        for func_risk in selected:
            before_ast, after_ast = file_asts.get(
                func_risk.filepath, (FileAST(""), FileAST(""))
            )
            code_before = (
                before_ast.functions[func_risk.name].raw_text
                if func_risk.name in before_ast.functions
                else ""
            )
            code_after = (
                after_ast.functions[func_risk.name].raw_text
                if func_risk.name in after_ast.functions
                else ""
            )
            cache_key = self._function_cache_key(func_risk.name, code_before, code_after)

            try:
                data = await rc.get(cache_key)
                if data:
                    parsed = json.loads(data) if isinstance(data, str) else data
                    risk_level_str = parsed.get("risk_level", "medium")
                    cached[func_risk.name] = FunctionAnalysisOutput(
                        name=parsed.get("name", func_risk.name),
                        risk_level=RiskLevel(risk_level_str)
                        if risk_level_str in [r.value for r in RiskLevel]
                        else RiskLevel.MEDIUM,
                        risk_signals=parsed.get("risk_signals", []),
                        suggestion=parsed.get("suggestion"),
                        potential_bugs=parsed.get("potential_bugs", []),
                        security_concerns=parsed.get("security_concerns", []),
                    )
                else:
                    uncached.append(func_risk)
            except Exception:
                uncached.append(func_risk)

        return cached, uncached

    async def _cache_function_results(
        self,
        results: list[FunctionAnalysisOutput],
        selected: list,  # list[FunctionRisk]
        file_asts: dict[str, tuple[FileAST, FileAST]],
    ) -> None:
        """Write freshly computed LLM results to Redis."""
        rc = _get_redis()
        if not rc:
            return

        # Build name -> FunctionRisk lookup for code retrieval
        risk_by_name = {fr.name: fr for fr in selected}

        for fa in results:
            func_risk = risk_by_name.get(fa.name)
            if not func_risk:
                continue

            before_ast, after_ast = file_asts.get(
                func_risk.filepath, (FileAST(""), FileAST(""))
            )
            code_before = (
                before_ast.functions[fa.name].raw_text
                if fa.name in before_ast.functions
                else ""
            )
            code_after = (
                after_ast.functions[fa.name].raw_text
                if fa.name in after_ast.functions
                else ""
            )
            cache_key = self._function_cache_key(fa.name, code_before, code_after)

            try:
                await rc.set(
                    cache_key,
                    json.dumps(fa.model_dump()),
                    ex=LLM_CACHE_TTL,
                )
            except Exception as e:
                logger.warning(f"Failed to cache function analysis for {fa.name}: {e}")

    # ------------------------------------------------------------------
    # PR-level summary caching
    # ------------------------------------------------------------------

    @staticmethod
    def _pr_summary_cache_key(triage_result) -> str:
        """
        Cache key for the PR-level LLM summary.
        Keyed on the sorted list of selected function names and their risk scores
        so it's stable across re-runs of the same PR with the same triage output.
        """
        fingerprint = "|".join(
            f"{fr.name}:{fr.risk_score}"
            for fr in sorted(triage_result.llm_selected_functions, key=lambda f: f.name)
        )
        return "llm_pr:" + hashlib.sha256(fingerprint.encode()).hexdigest()[:24]

    async def _get_pr_summary_cache(self, key: str) -> "PRAnalysis | None":
        """Retrieve a cached PR-level summary (without function_analyses)."""
        rc = _get_redis()
        if not rc:
            return None
        try:
            data = await rc.get(key)
            if not data:
                return None
            parsed = json.loads(data) if isinstance(data, str) else data
            risk_level_str = parsed.get("risk_level", "medium")
            return PRAnalysis(
                headline=parsed.get("headline", ""),
                risk_level=RiskLevel(risk_level_str)
                if risk_level_str in [r.value for r in RiskLevel]
                else RiskLevel.MEDIUM,
                risk_score=parsed.get("risk_score", 0),
                summary=parsed.get("summary"),
                insights=parsed.get("insights", []),
                recommendations=parsed.get("recommendations", []),
                memory_safety_issues=parsed.get("memory_safety_issues", []),
                security_concerns=parsed.get("security_concerns", []),
                potential_bugs=parsed.get("potential_bugs", []),
                cross_function_concerns=parsed.get("cross_function_concerns", []),
                mermaid_diagram=parsed.get("mermaid_diagram"),
            )
        except Exception as e:
            logger.warning(f"PR summary cache get failed: {e}")
            return None

    async def _set_pr_summary_cache(self, key: str, analysis: "PRAnalysis") -> None:
        """Store the PR-level summary (without function_analyses to save space)."""
        rc = _get_redis()
        if not rc:
            return
        try:
            payload = {
                "headline": analysis.headline,
                "risk_level": analysis.risk_level.value if hasattr(analysis.risk_level, "value") else analysis.risk_level,
                "risk_score": analysis.risk_score,
                "summary": analysis.summary,
                "insights": analysis.insights,
                "recommendations": analysis.recommendations,
                "memory_safety_issues": analysis.memory_safety_issues,
                "security_concerns": analysis.security_concerns,
                "potential_bugs": analysis.potential_bugs,
                "cross_function_concerns": analysis.cross_function_concerns,
                "mermaid_diagram": analysis.mermaid_diagram,
            }
            await rc.set(key, json.dumps(payload), ex=LLM_CACHE_TTL)
        except Exception as e:
            logger.warning(f"PR summary cache set failed: {e}")

    # ------------------------------------------------------------------
    # Static results for non-LLM functions
    # ------------------------------------------------------------------

    def _static_results_for_all(
        self, triage_result: TriageResult
    ) -> dict[str, FunctionAnalysisOutput]:
        """
        Build static-analysis FunctionAnalysisOutput for every changed function
        using triage signals. These are the baseline results; LLM results
        overwrite them for selected functions.
        """
        results: dict[str, FunctionAnalysisOutput] = {}
        for file_risk in triage_result.files:
            for func_risk in file_risk.functions:
                results[func_risk.name] = FunctionAnalysisOutput(
                    name=func_risk.name,
                    risk_level=RiskLevel(func_risk.risk_level.value),
                    risk_signals=func_risk.signals,
                    suggestion=(
                        "Review manually — not individually analysed by LLM due to PR size."
                        if not func_risk.send_to_llm
                        else None
                    ),
                )
        return results

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _recover_truncated_json(raw: str) -> str:
        """
        Best-effort recovery for JSON truncated mid-stream by a token limit.

        Walks the string character-by-character to track open braces/brackets
        and whether we are inside a string literal. If the response was cut off
        mid-string, the incomplete string is removed back to the last safe
        delimiter. Open structures are then closed in reverse order so the
        result is at least syntactically valid JSON, preserving every field
        that was fully written before truncation.

        Returns the original string unchanged if it already parses cleanly.
        Raises ValueError if recovery still produces invalid JSON.
        """
        # Fast path — already valid
        try:
            json.loads(raw)
            return raw
        except json.JSONDecodeError:
            pass

        # Second fast path — valid JSON followed by trailing garbage, e.g. a
        # stray ``` fence the model appends after the object despite
        # response_mime_type=application/json / "JSON only" instructions.
        # json.loads() rejects this as "Extra data"; raw_decode() parses just
        # the first complete value and tells us where it ends, which is
        # exactly what we want to slice out.
        try:
            _, end_idx = json.JSONDecoder().raw_decode(raw.lstrip())
            return raw.lstrip()[:end_idx]
        except json.JSONDecodeError:
            pass

        s = raw.rstrip()
        stack: list[str] = []
        in_string = False
        escape_next = False

        for ch in s:
            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch in ("{", "["):
                stack.append(ch)
            elif ch in ("}", "]") and stack:
                stack.pop()

        if not stack and not in_string:
            # Balanced but still invalid — nothing recoverable
            raise ValueError("JSON structure is balanced but still unparseable")

        # If we ended inside a string literal, cut back to the opening quote
        # and strip any trailing comma so the enclosing object/array stays valid
        if in_string:
            last_quote = s.rfind('"')
            if last_quote > 0:
                s = s[:last_quote].rstrip().rstrip(",").rstrip()

        # Close any open structures
        closers = {"[": "]", "{": "}"}
        s = s + "".join(closers[c] for c in reversed(stack))

        json.loads(s)  # raises ValueError/JSONDecodeError if still broken
        return s

    def _parse_pr_analysis(
        self, response: str, triage_result: TriageResult
    ) -> PRAnalysis:
        try:
            try:
                recovered = self._recover_truncated_json(response)
            except Exception as recover_err:
                logger.warning(
                    f"Gemini response could not be recovered as JSON: {recover_err}. "
                    f"Response length={len(response)}. Falling back to triage."
                )
                return self._fallback_analysis_from_triage(triage_result)

            if recovered != response:
                logger.warning(
                    "Gemini response was truncated (hit token limit); recovered partial JSON. "
                    f"Original length={len(response)}, recovered length={len(recovered)}"
                )

            data = json.loads(recovered)
            risk_level_str = data.get("risk_level", "medium").lower()
            risk_level = (
                RiskLevel(risk_level_str)
                if risk_level_str in [r.value for r in RiskLevel]
                else RiskLevel.MEDIUM
            )

            func_analyses = []
            for fa in data.get("function_analyses", []):
                rl_str = fa.get("risk_level", "medium").lower()
                func_analyses.append(
                    FunctionAnalysisOutput(
                        name=fa.get("name", "unknown"),
                        risk_level=RiskLevel(rl_str)
                        if rl_str in [r.value for r in RiskLevel]
                        else RiskLevel.MEDIUM,
                        risk_signals=fa.get("risk_signals", []),
                        suggestion=fa.get("suggestion"),
                        potential_bugs=fa.get("potential_bugs", []),
                        security_concerns=fa.get("security_concerns", []),
                    )
                )

            return PRAnalysis(
                headline=data.get("headline", "Code review analysis"),
                risk_level=risk_level,
                risk_score=data.get("risk_score", triage_result.overall_risk_score),
                summary=data.get("summary"),
                insights=data.get("insights", []),
                recommendations=data.get("recommendations", []),
                memory_safety_issues=data.get("memory_safety_issues", []),
                security_concerns=data.get("security_concerns", []),
                potential_bugs=data.get("potential_bugs", []),
                cross_function_concerns=data.get("cross_function_concerns", []),
                function_analyses=func_analyses,
                # mermaid_diagram is generated by a separate call, not part of
                # this JSON response — see _generate_mermaid_diagram().
            )

        except Exception:
            logger.exception("Failed to parse PR analysis response")
            return self._fallback_analysis_from_triage(triage_result)

    def _build_pr_analysis(
        self,
        pr_evidence: PREvidence,
        triage_result: TriageResult,
        function_analyses: list[FunctionAnalysisOutput],
    ) -> PRAnalysis:
        """Build a PRAnalysis from cached/static results without an LLM call."""
        high_risk = [
            fa for fa in function_analyses
            if fa.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)
        ]
        return PRAnalysis(
            headline=f"Static analysis: {triage_result.overall_risk_level.value} risk "
                     f"({triage_result.overall_risk_score}/100)",
            risk_level=RiskLevel(triage_result.overall_risk_level.value),
            risk_score=triage_result.overall_risk_score,
            summary=triage_result.reasoning,
            insights=[
                f"{len(high_risk)} high/critical risk functions detected by static analysis"
            ] if high_risk else ["No high-risk functions detected"],
            recommendations=["Review high-risk functions manually"] if high_risk else [],
            function_analyses=function_analyses,
        )

    # ------------------------------------------------------------------
    # Fallback / mock
    # ------------------------------------------------------------------

    def _mock_analysis(
        self, pr_evidence: PREvidence, triage_result: TriageResult
    ) -> PRAnalysis:
        return PRAnalysis(
            headline="API key not configured — static analysis only",
            risk_level=RiskLevel(triage_result.overall_risk_level.value),
            risk_score=triage_result.overall_risk_score,
            summary=f"{self.provider_label} API key not configured. Results are from static heuristics only.",
            insights=[f"Configure {self.api_key_env_var} to enable LLM analysis"],
            recommendations=[f"Set up {self.provider_label} API access"],
            function_analyses=self._static_results_for_all(triage_result),
        )

    def _fallback_analysis(
        self, pr_evidence: PREvidence, triage_result: TriageResult, error: str
    ) -> PRAnalysis:
        return PRAnalysis(
            headline=f"LLM analysis failed: {error[:60]}",
            risk_level=RiskLevel(triage_result.overall_risk_level.value),
            risk_score=triage_result.overall_risk_score,
            summary=f"LLM analysis failed after {MAX_RETRIES} retries: {error}. "
                    f"Results below are from static heuristics only.",
            insights=[
                f"Static analysis detected {pr_evidence.total_functions_changed} function changes"
            ],
            recommendations=["Review changes manually"],
            function_analyses=list(self._static_results_for_all(triage_result).values()),
        )

    def _fallback_analysis_from_triage(self, triage_result: TriageResult) -> PRAnalysis:
        return PRAnalysis(
            headline="Static analysis only (LLM response parsing failed)",
            risk_level=RiskLevel(triage_result.overall_risk_level.value),
            risk_score=triage_result.overall_risk_score,
            summary=triage_result.reasoning,
            insights=["LLM response could not be parsed"],
            recommendations=["Review triage signals manually"],
        )


class GeminiClient(BaseLLMClient):
    """
    Client for Gemini API interactions.

    Usage:
        client = GeminiClient()
        analysis = await client.analyze(pr_evidence, triage_result, file_asts)
    """

    provider_label = "Gemini"
    api_key_env_var = "GEMINI_API_KEY"

    def __init__(
        self,
        api_key: Optional[str] = None,
        fast_model: str = "gemini-2.5-flash-lite",
        deep_model: str = "gemini-2.5-flash",
    ):
        super().__init__(
            api_key=api_key or os.environ.get("GEMINI_API_KEY"),
            fast_model=fast_model,
            deep_model=deep_model,
        )
        if self.api_key:
            logger.info(f"Initializing Gemini client (fast={fast_model}, deep={deep_model})")
            self.client = genai.Client(api_key=self.api_key)
        else:
            logger.warning("GEMINI_API_KEY not configured — will return static-analysis results")

    def _call_llm_api(
        self, system_prompt: str, user_prompt: str, model: str, json_mode: bool = True
    ) -> str:
        response = self.client.models.generate_content(
            model=model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.2,
                max_output_tokens=16384,
                response_mime_type="application/json" if json_mode else "text/plain",
            ),
        )
        return response.text or ""


class ClaudeClient(BaseLLMClient):
    """
    Client for Anthropic Claude API interactions — a drop-in alternative to
    GeminiClient with the same public interface (analyze/analyze_fast_path/
    analyze_deep), selectable via LLM_PROVIDER=claude.

    Usage:
        client = ClaudeClient()
        analysis = await client.analyze(pr_evidence, triage_result, file_asts)
    """

    provider_label = "Claude"
    api_key_env_var = "ANTHROPIC_API_KEY"

    def __init__(
        self,
        api_key: Optional[str] = None,
        fast_model: str = "claude-haiku-4-5",
        deep_model: str = "claude-sonnet-4-5",
    ):
        super().__init__(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"),
            fast_model=fast_model,
            deep_model=deep_model,
        )
        if self.api_key:
            logger.info(f"Initializing Claude client (fast={fast_model}, deep={deep_model})")
            self.client = anthropic.Anthropic(api_key=self.api_key)
        else:
            logger.warning("ANTHROPIC_API_KEY not configured — will return static-analysis results")

    def _call_llm_api(
        self, system_prompt: str, user_prompt: str, model: str, json_mode: bool = True
    ) -> str:
        if json_mode:
            # Claude has no native JSON-mode flag like Gemini's response_mime_type;
            # instruct it in the system prompt and prefill the assistant turn with
            # "{" so it can't wrap the JSON in prose or a markdown fence.
            response = self.client.messages.create(
                model=model,
                max_tokens=16384,
                temperature=0.2,
                system=system_prompt + "\n\nRespond with ONLY valid JSON, no markdown fences, no prose.",
                messages=[
                    {"role": "user", "content": user_prompt},
                    {"role": "assistant", "content": "{"},
                ],
            )
            text = "".join(
                block.text for block in response.content if hasattr(block, "text")
            )
            return "{" + text

        response = self.client.messages.create(
            model=model,
            max_tokens=16384,
            temperature=0.2,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return "".join(block.text for block in response.content if hasattr(block, "text"))


def get_llm_client() -> BaseLLMClient:
    """
    Factory returning the configured LLM client.

    Selected via LLM_PROVIDER env var: "claude"/"anthropic" -> ClaudeClient,
    anything else (including unset) -> GeminiClient (default, unchanged
    behaviour for existing deployments).
    """
    provider = os.environ.get("LLM_PROVIDER", "gemini").strip().lower()
    if provider in ("claude", "anthropic"):
        return ClaudeClient()
    return GeminiClient()