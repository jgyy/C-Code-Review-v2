"""
llm/client.py — Gemini API client for code analysis

Updated for the latest google-genai SDK.

Uses Google's latest Gemini SDK:
    pip install google-genai

Model selection:
- gemini-2.5-flash-lite: Fast path, lower latency
- gemini-2.5-flash: Deep analysis, stronger reasoning
"""

from __future__ import annotations

import os
import json
import asyncio
import logging
from typing import Optional

from google import genai
from google.genai import types

from dotenv import load_dotenv

from llm.schemas import (
    PRAnalysis,
    FunctionAnalysisOutput,
    RiskLevel,
)

from llm.prompts import (
    SYSTEM_PROMPT_FAST_PATH,
    SYSTEM_PROMPT_DEEP_MAP,
    SYSTEM_PROMPT_DEEP_REDUCE,
    build_fast_path_prompt,
    build_deep_map_prompt,
    build_deep_reduce_prompt,
)

from core.heuristics import (
    PREvidence,
    FunctionEvidence,
    ChangeType,
)

from core.triage import TriageResult
from core.parser import FileAST

logger = logging.getLogger(__name__)

load_dotenv()


class GeminiClient:
    """
    Client for Gemini API interactions.

    Usage:
        client = GeminiClient()
        analysis = await client.analyze_fast_path(
            evidence,
            triage_result,
            file_asts
        )
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

        logger.info(f"fast model: {self.fast_model}")
        logger.info(f"deep model: {self.deep_model}")

        self.client: Optional[genai.Client] = None

        if self.api_key:
            logger.info("Initializing Gemini client")
            self.client = genai.Client(api_key=self.api_key)
        else:
            logger.warning("GEMINI_API_KEY not configured")

    async def analyze_fast_path(
        self,
        pr_evidence: PREvidence,
        triage_result: TriageResult,
        file_asts: dict[str, tuple[FileAST, FileAST]],
    ) -> PRAnalysis:
        """
        Fast-path analysis:
        Single LLM call for low-medium risk PRs.
        """

        if not self.client:
            return self._mock_analysis(pr_evidence, triage_result)

        context = self._build_context(
            pr_evidence,
            triage_result,
            file_asts,
        )

        user_prompt = build_fast_path_prompt(context)

        try:
            response = await self._call_gemini(
                system_prompt=SYSTEM_PROMPT_FAST_PATH,
                user_prompt=user_prompt,
                model=self.fast_model,
            )

            return self._parse_pr_analysis(
                response,
                triage_result,
            )

        except Exception as e:
            logger.exception("Gemini fast-path analysis failed")

            return self._fallback_analysis(
                pr_evidence,
                triage_result,
                str(e),
            )

    async def analyze_deep(
        self,
        pr_evidence: PREvidence,
        triage_result: TriageResult,
        file_asts: dict[str, tuple[FileAST, FileAST]],
    ) -> PRAnalysis:
        """
        Deep analysis: map-reduce over functions.

        1. Map: Analyze each function
        2. Reduce: Synthesize PR-level analysis
        """

        if not self.client:
            return self._mock_analysis(pr_evidence, triage_result)

        function_analyses: list[FunctionAnalysisOutput] = []

        for file_ev in pr_evidence.files:
            before_ast, after_ast = file_asts.get(
                file_ev.filepath,
                (FileAST(""), FileAST("")),
            )

            for func_ev in file_ev.functions:

                func_input = self._build_function_input(
                    func_ev,
                    file_ev.filepath,
                    before_ast,
                    after_ast,
                )

                try:
                    user_prompt = build_deep_map_prompt(func_input)

                    response = await self._call_gemini(
                        system_prompt=SYSTEM_PROMPT_DEEP_MAP,
                        user_prompt=user_prompt,
                        model=self.deep_model,
                    )

                    func_analysis = self._parse_function_analysis(
                        response,
                        func_ev.name,
                    )

                    function_analyses.append(func_analysis)

                except Exception as e:
                    logger.exception(
                        f"Error analyzing function {func_ev.name}"
                    )

                    function_analyses.append(
                        FunctionAnalysisOutput(
                            name=func_ev.name,
                            risk_level=RiskLevel.MEDIUM,
                            risk_signals=["Analysis failed"],
                        )
                    )

        reduce_context = {
            "function_analyses": [
                fa.model_dump()
                for fa in function_analyses
            ],
            "total_functions": len(function_analyses),
            "high_risk_count": sum(
                1
                for fa in function_analyses
                if fa.risk_level in (
                    RiskLevel.HIGH,
                    RiskLevel.CRITICAL,
                )
            ),
            "file_paths": [
                fe.filepath
                for fe in pr_evidence.files
            ],
            "patterns": self._detect_patterns(
                function_analyses
            ),
        }

        try:
            user_prompt = build_deep_reduce_prompt(
                reduce_context
            )

            response = await self._call_gemini(
                system_prompt=SYSTEM_PROMPT_DEEP_REDUCE,
                user_prompt=user_prompt,
                model=self.deep_model,
            )

            pr_analysis = self._parse_pr_analysis(
                response,
                triage_result,
            )

            pr_analysis.function_analyses = function_analyses

            return pr_analysis

        except Exception as e:
            logger.exception("Reduce phase failed")

            return self._fallback_analysis(
                pr_evidence,
                triage_result,
                str(e),
            )

    async def _call_gemini(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
    ) -> str:
        """
        Async Gemini API call.
        """

        if not self.client:
            raise RuntimeError(
                "Gemini client not initialized"
            )

        def _sync_call():

            response = self.client.models.generate_content(
                model=model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.2,
                    max_output_tokens=4096,
                    response_mime_type="application/json",
                ),
            )

            return response.text or ""

        return await asyncio.to_thread(_sync_call)

    def _build_context(
        self,
        pr_evidence: PREvidence,
        triage_result: TriageResult,
        file_asts: dict[str, tuple[FileAST, FileAST]],
    ) -> dict:
        """
        Build context dict for prompts.
        """

        function_evidences = []
        code_snippets = {}

        for file_ev in pr_evidence.files:

            before_ast, after_ast = file_asts.get(
                file_ev.filepath,
                (FileAST(""), FileAST("")),
            )

            for func_ev in file_ev.functions:

                fe_dict = {
                    "name": func_ev.name,
                    "filepath": file_ev.filepath,
                    "change_type": func_ev.change_type.value,
                    "complexity_before": func_ev.complexity_before,
                    "complexity_after": func_ev.complexity_after,
                    "complexity_delta": func_ev.complexity_delta,
                    "malloc_free_imbalance": func_ev.malloc_free_imbalance,
                    "return_type_changed": func_ev.return_type_changed,
                    "calls_added": func_ev.calls_added,
                    "calls_removed": func_ev.calls_removed,
                }

                function_evidences.append(fe_dict)

                file_risk = next(
                    (
                        fr
                        for fr in triage_result.files
                        if fr.filepath == file_ev.filepath
                    ),
                    None,
                )

                if file_risk:

                    func_risk = next(
                        (
                            fr
                            for fr in file_risk.functions
                            if fr.name == func_ev.name
                        ),
                        None,
                    )

                    if (
                        func_risk
                        and func_risk.risk_score >= 30
                    ):

                        if (
                            func_ev.change_type
                            == ChangeType.DELETED
                        ):

                            if (
                                func_ev.name
                                in before_ast.functions
                            ):
                                code_snippets[
                                    func_ev.name
                                ] = before_ast.functions[
                                    func_ev.name
                                ].raw_text

                        else:

                            if (
                                func_ev.name
                                in after_ast.functions
                            ):
                                code_snippets[
                                    func_ev.name
                                ] = after_ast.functions[
                                    func_ev.name
                                ].raw_text

        return {
            "repo_name": f"PR#{pr_evidence.total_files_changed}",
            "pr_number": 0,
            "overall_risk_score": triage_result.overall_risk_score,
            "overall_risk_level": triage_result.overall_risk_level.value,
            "triage_reasoning": triage_result.reasoning,
            "function_evidences": function_evidences,
            "code_snippets": code_snippets,
        }

    def _build_function_input(
        self,
        func_ev: FunctionEvidence,
        filepath: str,
        before_ast: FileAST,
        after_ast: FileAST,
    ) -> dict:
        """
        Build input for function analysis.
        """

        code_before = ""
        code_after = ""

        name_before = func_ev.renamed_from or func_ev.name

        if name_before in before_ast.functions:
            code_before = before_ast.functions[
                name_before
            ].raw_text

        if func_ev.name in after_ast.functions:
            code_after = after_ast.functions[
                func_ev.name
            ].raw_text

        return {
            "name": func_ev.name,
            "filepath": filepath,
            "change_type": func_ev.change_type.value,
            "complexity_before": func_ev.complexity_before,
            "complexity_after": func_ev.complexity_after,
            "complexity_delta": func_ev.complexity_delta,
            "depth_before": func_ev.depth_before,
            "depth_after": func_ev.depth_after,
            "depth_delta": func_ev.depth_delta,
            "memory_ops_before": func_ev.memory_ops_before,
            "memory_ops_after": func_ev.memory_ops_after,
            "malloc_free_imbalance": func_ev.malloc_free_imbalance,
            "pointer_density_delta": func_ev.pointer_density_delta,
            "calls_added": func_ev.calls_added,
            "calls_removed": func_ev.calls_removed,
            "is_recursive": func_ev.is_recursive,
            "recursion_changed": func_ev.recursion_changed,
            "params_before": func_ev.params_before,
            "params_after": func_ev.params_after,
            "return_type_changed": func_ev.return_type_changed,
            "code_before": code_before,
            "code_after": code_after,
        }

    def _parse_pr_analysis(
        self,
        response: str,
        triage_result: TriageResult,
    ) -> PRAnalysis:
        """
        Parse LLM response into PRAnalysis.
        """

        try:
            data = json.loads(response)

            risk_level_str = data.get(
                "risk_level",
                "medium",
            ).lower()

            risk_level = (
                RiskLevel(risk_level_str)
                if risk_level_str
                in [r.value for r in RiskLevel]
                else RiskLevel.MEDIUM
            )

            return PRAnalysis(
                headline=data.get(
                    "headline",
                    "Code review analysis",
                ),
                risk_level=risk_level,
                risk_score=data.get(
                    "risk_score",
                    triage_result.overall_risk_score,
                ),
                summary=data.get("summary"),
                insights=data.get("insights", []),
                recommendations=data.get(
                    "recommendations",
                    [],
                ),
                memory_safety_issues=data.get(
                    "memory_safety_issues",
                    [],
                ),
                security_concerns=data.get(
                    "security_concerns",
                    [],
                ),
                potential_bugs=data.get(
                    "potential_bugs",
                    [],
                ),
                cross_function_concerns=data.get(
                    "cross_function_concerns",
                    [],
                ),
            )

        except Exception:
            logger.exception(
                "Failed to parse PR analysis"
            )

            return self._fallback_analysis_from_triage(
                triage_result
            )

    def _parse_function_analysis(
        self,
        response: str,
        func_name: str,
    ) -> FunctionAnalysisOutput:
        """
        Parse function analysis JSON.
        """

        try:
            data = json.loads(response)

            risk_level_str = data.get(
                "risk_level",
                "medium",
            ).lower()

            risk_level = (
                RiskLevel(risk_level_str)
                if risk_level_str
                in [r.value for r in RiskLevel]
                else RiskLevel.MEDIUM
            )

            return FunctionAnalysisOutput(
                name=data.get("name", func_name),
                risk_level=risk_level,
                risk_signals=data.get(
                    "risk_signals",
                    [],
                ),
                suggestion=data.get("suggestion"),
                potential_bugs=data.get(
                    "potential_bugs",
                    [],
                ),
                security_concerns=data.get(
                    "security_concerns",
                    [],
                ),
            )

        except Exception:
            logger.exception(
                "Failed to parse function analysis"
            )

            return FunctionAnalysisOutput(
                name=func_name,
                risk_level=RiskLevel.MEDIUM,
                risk_signals=[
                    "Analysis parsing failed"
                ],
            )

    def _detect_patterns(
        self,
        analyses: list[FunctionAnalysisOutput],
    ) -> list[str]:
        """
        Detect cross-function patterns.
        """

        patterns = []

        memory_issues = sum(
            1
            for fa in analyses
            if any(
                (
                    "memory" in s.lower()
                    or "malloc" in s.lower()
                    or "free" in s.lower()
                )
                for s in (
                    fa.risk_signals
                    + fa.potential_bugs
                )
            )
        )

        if memory_issues > 1:
            patterns.append(
                f"Memory management changes detected "
                f"in {memory_issues} functions"
            )

        high_risk = [
            fa
            for fa in analyses
            if fa.risk_level
            in (
                RiskLevel.HIGH,
                RiskLevel.CRITICAL,
            )
        ]

        if len(high_risk) > 2:
            patterns.append(
                f"{len(high_risk)} high-risk functions "
                f"require careful review"
            )

        return patterns

    def _mock_analysis(
        self,
        pr_evidence: PREvidence,
        triage_result: TriageResult,
    ) -> PRAnalysis:
        """
        Mock analysis when API key missing.
        """

        return PRAnalysis(
            headline="API key not configured",
            risk_level=RiskLevel(
                triage_result.overall_risk_level.value
            ),
            risk_score=triage_result.overall_risk_score,
            summary=(
                "Gemini API key not configured."
            ),
            insights=[
                "Configure GEMINI_API_KEY"
            ],
            recommendations=[
                "Set up Gemini API access"
            ],
        )

    def _fallback_analysis(
        self,
        pr_evidence: PREvidence,
        triage_result: TriageResult,
        error: str,
    ) -> PRAnalysis:
        """
        Fallback analysis on API failure.
        """

        return PRAnalysis(
            headline=(
                f"Analysis incomplete: "
                f"{error[:50]}"
            ),
            risk_level=RiskLevel(
                triage_result.overall_risk_level.value
            ),
            risk_score=triage_result.overall_risk_score,
            summary=(
                f"LLM analysis failed: {error}"
            ),
            insights=[
                f"Static analysis detected "
                f"{pr_evidence.total_functions_changed} "
                f"function changes"
            ],
            recommendations=[
                "Review changes manually"
            ],
        )

    def _fallback_analysis_from_triage(
        self,
        triage_result: TriageResult,
    ) -> PRAnalysis:
        """
        Fallback when parsing fails.
        """

        return PRAnalysis(
            headline="Static analysis only",
            risk_level=RiskLevel(
                triage_result.overall_risk_level.value
            ),
            risk_score=triage_result.overall_risk_score,
            summary=triage_result.reasoning,
            insights=[
                "LLM parsing failed"
            ],
            recommendations=[
                "Review triage signals manually"
            ],
        )