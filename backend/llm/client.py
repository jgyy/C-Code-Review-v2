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
from typing import Optional

from dotenv import load_dotenv
from google import genai
from google.genai import types

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
    build_fast_path_prompt,
)
from llm.schemas import FunctionAnalysisOutput, PRAnalysis

logger = logging.getLogger(__name__)

load_dotenv()

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


class GeminiClient:
    """
    Client for Gemini API interactions.

    One LLM call per PR. All rate-limit and token-budget concerns are handled
    internally; callers just call analyze() and get a PRAnalysis back.

    Usage:
        client = GeminiClient()
        analysis = await client.analyze(pr_evidence, triage_result, file_asts)
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        fast_model: str = "gemini-2.5-flash-lite",
        deep_model: str = "gemini-2.5-flash",
    ):
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        self.fast_model = fast_model
        self.deep_model = deep_model

        self.client: Optional[genai.Client] = None
        if self.api_key:
            logger.info(f"Initializing Gemini client (fast={fast_model}, deep={deep_model})")
            self.client = genai.Client(api_key=self.api_key)
        else:
            logger.warning("GEMINI_API_KEY not configured — will return static-analysis results")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def analyze(
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
            f"llm_functions={len(triage_result.llm_selected_functions)}, "
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

        # If all selected functions were cached, skip the LLM call entirely
        if not uncached_selected:
            logger.info("All selected functions served from cache — skipping LLM call")
            return self._build_pr_analysis(
                pr_evidence, triage_result, list(all_function_results.values())
            )

        # Build prompt with uncached functions only
        context = self._build_context(
            pr_evidence=pr_evidence,
            triage_result=triage_result,
            file_asts=file_asts,
            selected_functions=uncached_selected,
        )
        user_prompt = build_fast_path_prompt(context)

        try:
            response = await self._call_gemini(
                system_prompt=SYSTEM_PROMPT_FAST_PATH,
                user_prompt=user_prompt,
                model=model,
            )
            pr_analysis = self._parse_pr_analysis(response, triage_result)

            # Overwrite static results with LLM results for selected functions
            for fa in pr_analysis.function_analyses:
                all_function_results[fa.name] = fa

            # Cache the freshly computed LLM results
            await self._cache_function_results(
                pr_analysis.function_analyses, uncached_selected, file_asts
            )

            # Attach the full function list (LLM + static) to the PR analysis
            pr_analysis.function_analyses = list(all_function_results.values())
            return pr_analysis

        except Exception as e:
            logger.exception("Gemini analysis failed after retries")
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

    async def _call_gemini(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> str:
        """
        Call Gemini with exponential backoff retry on transient errors.

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
            raise RuntimeError("Gemini client not initialized")

        last_exception: Exception = RuntimeError("No attempts made")

        for attempt in range(MAX_RETRIES):
            try:
                def _sync_call():
                    response = self.client.models.generate_content(
                        model=model,
                        contents=user_prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=system_prompt,
                            temperature=0.2,
                            max_output_tokens=16384,
                            response_mime_type="application/json",
                        ),
                    )
                    return response.text or ""

                result = await asyncio.to_thread(_sync_call)
                if attempt > 0:
                    logger.info(f"Gemini call succeeded on attempt {attempt + 1}")
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
                )

                if not is_retryable or attempt == MAX_RETRIES - 1:
                    logger.error(
                        f"Gemini call failed (attempt {attempt + 1}/{MAX_RETRIES},"
                        f" non-retryable or out of retries): {e}"
                    )
                    raise

                delay = min(BACKOFF_BASE * (2 ** attempt), BACKOFF_MAX)
                jitter = random.uniform(0, delay * 0.2)
                wait = delay + jitter
                logger.warning(
                    f"Gemini call failed (attempt {attempt + 1}/{MAX_RETRIES}): {e}. "
                    f"Retrying in {wait:.1f}s"
                )
                await asyncio.sleep(wait)

        raise last_exception

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
        evidence_lookup: dict[tuple[str, str], FunctionEvidence] = {
            (file_ev.filepath, func_ev.name): func_ev
            for file_ev in pr_evidence.files
            for func_ev in file_ev.functions
        }

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
            "omitted_functions_summary": omitted_summary,
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
            summary="Gemini API key not configured. Results are from static heuristics only.",
            insights=["Configure GEMINI_API_KEY to enable LLM analysis"],
            recommendations=["Set up Gemini API access"],
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