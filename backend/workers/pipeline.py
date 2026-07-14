"""
workers/pipeline.py — Main orchestration pipeline

This is the heart of the code review system. It orchestrates:
1. Fetch file contents from GitHub (before/after)
2. Check Redis cache for existing AST snapshots
3. Parse cache misses in parallel
4. Store new AST snapshots in cache
5. Run heuristics on all changed functions
6. Triage and route to appropriate LLM path
7. Execute LLM analysis
8. Return formatted results

The pipeline is designed to be resumable: if it fails partway through,
cached AST data is preserved and won't need re-parsing.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional
import asyncio

from core.parser import extract_file_ast, FileAST
from core.heuristics import (
    compute_file_evidence,
    compute_pr_evidence,
    FileEvidence,
    PREvidence,
)
from core.triage import triage, TriageResult, Route
from workers.pool import parse_files_parallel
from cache.redis import get_cached_ast, set_cached_ast, set_job_stage
from github_utils.client import GitHubClient, GitHubFetchError
from llm.client import BaseLLMClient
from llm.schemas import PRAnalysis
import logging

logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    """Configuration for the analysis pipeline."""
    max_files: int = 500  # Skip PRs with too many files
    max_file_size: int = 100_000  # Skip files larger than 100KB
    file_extensions: frozenset[str] = field(
        default_factory=lambda: frozenset({".c", ".h"})
    )
    parallel_workers: int = 4


@dataclass
class PipelineResult:
    """Result from the analysis pipeline."""
    success: bool
    job_id: str
    pr_number: int
    repo_full_name: str
    
    # Triage info
    triage_result: Optional[TriageResult] = None
    
    # Analysis results
    analysis: Optional[PRAnalysis] = None
    
    # Stats
    files_analyzed: int = 0
    functions_analyzed: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    
    # Errors
    error: Optional[str] = None
    skipped_reason: Optional[str] = None


class AnalysisPipeline:
    """
    Main analysis pipeline for C code review.
    
    Usage:
        pipeline = AnalysisPipeline(config)
        result = await pipeline.analyze_pr(
            github_client=gh,
            llm_client=llm,
            repo_owner="owner",
            repo_name="repo",
            pr_number=123,
            job_id="job-abc",
        )
    """
    
    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or PipelineConfig()
    
    async def analyze_pr(
        self,
        github_client: GitHubClient,
        llm_client: BaseLLMClient,
        repo_owner: str,
        repo_name: str,
        pr_number: int,
        job_id: str,
    ) -> PipelineResult:
        """
        Run the full analysis pipeline for a PR.
        """
        repo_full_name = f"{repo_owner}/{repo_name}"
        
        result = PipelineResult(
            success=False,
            job_id=job_id,
            pr_number=pr_number,
            repo_full_name=repo_full_name,
        )
        
        try:
            # 1. Fetch PR info and changed files
            logger.info("--- Stage 1: Fetch PR info and changed files ---")
            await set_job_stage(job_id, "fetching_pr")
            pr_info = await github_client.get_pr_info(repo_owner, repo_name, pr_number)
            logger.info(f"pr_info: {pr_info}")
            if not pr_info:
                logger.error(f"pr_info fetch failed")
                result.error = "Failed to fetch PR info"
                return result
            
            changed_files = await github_client.get_pr_files(repo_owner, repo_name, pr_number)
            logger.info(f"changed_files: {changed_files}")
            # Filter to C/H files only
            c_files = [
                f for f in changed_files
                if any(f["filename"].endswith(ext) for ext in self.config.file_extensions)
            ]
            
            if not c_files:
                logger.info("no changed files")
                result.success = True
                result.skipped_reason = "No C/H files changed"
                return result
            
            if len(c_files) > self.config.max_files:
                logger.info("Too many files")
                result.success = True
                result.skipped_reason = f"Too many files ({len(c_files)} > {self.config.max_files})"
                return result
            
            result.files_analyzed = len(c_files)

            # 2. Fetch and parse file contents
            logger.info("--- Stage 2: Fetch and parse file contents ---")
            await set_job_stage(job_id, "parsing_files")
            base_sha = pr_info["base"]["sha"]
            head_sha = pr_info["head"]["sha"]
            
            logger.info(f"base: {base_sha}; head: {head_sha}")
            file_asts: dict[str, tuple[FileAST, FileAST]] = {}  # filepath -> (before, after)
            
            for file_info in c_files:
                filepath = file_info["filename"]
                status = file_info["status"]  # added, removed, modified, renamed
                
                # Get before AST (if file existed)
                before_ast = FileAST(source_hash="empty")
                if status != "added":
                    logger.info(f"status not added: ${status}")
                    # For renames, the old file lives at previous_filename
                    before_path = file_info.get("previous_filename", filepath) if status == "renamed" else filepath
                    before_ast = await self._get_or_parse_ast(
                        github_client, repo_owner, repo_name, base_sha, before_path, result
                    )
                logger.info(f"before_ast: {before_ast}")
                # Get after AST (if file still exists)
                after_ast = FileAST(source_hash="empty")
                logger.info(f"after_ast: {after_ast}")
                if status != "removed":
                    logger.info(f"status not removed: {status}")
                    # For renames, the new file lives at filepath (the new name)
                    after_ast = await self._get_or_parse_ast(
                        github_client, repo_owner, repo_name, head_sha, filepath, result
                    )
                logger.info(f"after_ast2: {after_ast}")
                file_asts[filepath] = (before_ast, after_ast)
            
            # 3. Compute evidence
            logger.info("--- Stage 3: Compute evidence ---")
            await set_job_stage(job_id, "computing_evidence")
            file_evidences: list[FileEvidence] = []
            for filepath, (before, after) in file_asts.items():
                evidence = compute_file_evidence(filepath, before, after)
                file_evidences.append(evidence)
                result.functions_analyzed += len(evidence.functions)
            
            pr_evidence = compute_pr_evidence(file_evidences)
            logger.info(f"pr_evidence: {pr_evidence}")
            # 4. Triage
            logger.info("--- Stage 4: Triage ---")
            await set_job_stage(job_id, "triage")
            triage_result = triage(pr_evidence)
            result.triage_result = triage_result
            logger.info(f"tri_res: {triage_result}")
            # 5. Route to LLM (or skip)
            logger.info("--- Stage 5: Route to LLM ---")
            if triage_result.route == Route.SKIP:
                logger.info(f"Route.SKIP")
                result.success = True
                result.skipped_reason = triage_result.skip_reason
                logger.info(f"skip: {triage_result.skip_reason}")
                logger.info(f"5. result: {result}")
                return result
            
            # 6. LLM Analysis
            await set_job_stage(job_id, "llm_analysis")
            if triage_result.route == Route.FAST_PATH:
                logger.info(f"Route.FAST_PATH")
                analysis = await llm_client.analyze_fast_path(
                    pr_evidence=pr_evidence,
                    triage_result=triage_result,
                    file_asts=file_asts,
                )
            else:  # DEEP_ANALYSIS
                logger.info(f"DEEP_ANALYSIS")
                analysis = await llm_client.analyze_deep(
                    pr_evidence=pr_evidence,
                    triage_result=triage_result,
                    file_asts=file_asts,
                )
            
            result.analysis = analysis
            logger.info(f"LLM result: {result}")
            logger.info(f"LLM analysis result: {result.analysis}")
            logger.info(f"result SUCCESS")
            result.success = True
            
        except Exception as e:
            result.error = str(e)
        
        # logger.info(f"final result: {result}")
        return result
    
    async def _get_or_parse_ast(
        self,
        github_client: GitHubClient,
        repo_owner: str,
        repo_name: str,
        sha: str,
        filepath: str,
        result: PipelineResult,
    ) -> FileAST:
        """Get AST from cache or parse fresh."""
        logger.info("ENtered _get_or_parse_ast")
        # Check cache first
        cached = await get_cached_ast(sha, filepath)
        if cached:
            result.cache_hits += 1
            return _dict_to_file_ast(cached)
        
        result.cache_misses += 1

        # Fetch content from GitHub.
        #
        # IMPORTANT: get_file_content raises GitHubFetchError for anything
        # that isn't a confirmed "file doesn't exist at this SHA" (rate
        # limits, transient network/5xx errors, auth issues). We must NOT
        # treat that the same as "file is genuinely empty/absent" — doing so
        # was the root cause of false "function deleted" reports: an empty
        # FileAST diffed against a real before/after AST makes every function
        # in the file look deleted (or added), even though it's untouched and
        # we simply failed to fetch it. See FileAST.fetch_failed and
        # core.heuristics.compute_file_evidence.
        try:
            content = await github_client.get_file_content(repo_owner, repo_name, sha, filepath)
        except GitHubFetchError as e:
            logger.error(
                f"Failed to fetch {filepath}@{sha}, marking as fetch_failed "
                f"(NOT treated as deleted/absent): {e}"
            )
            return FileAST(source_hash="fetch_error", has_parse_errors=True, fetch_failed=True)

        if content is None:
            # Confirmed absent at this SHA (e.g. newly added or removed file).
            return FileAST(source_hash="empty")

        # Parse (this is sync, but fast)
        ast = extract_file_ast(content)
        
        # Cache the result
        await set_cached_ast(sha, filepath, _file_ast_to_dict(ast))
        
        return ast


def _file_ast_to_dict(ast: FileAST) -> dict:
    """Convert FileAST to a JSON-serializable dict."""
    logger.info("entered _file_ast_to_dict")
    return {
        "source_hash": ast.source_hash,
        "has_parse_errors": ast.has_parse_errors,
        "error_count": ast.error_count,
        "global_calls": ast.global_calls,
        "functions": {
            name: {
                "name": info.name,
                "params": info.params,
                "return_type": info.return_type,
                "calls": info.calls,
                "complexity": info.complexity,
                "max_depth": info.max_depth,
                "local_vars": info.local_vars,
                "memory_ops": info.memory_ops,
                "pointer_ops": info.pointer_ops,
                "has_recursion": info.has_recursion,
                "loop_count": info.loop_count,
                "line_start": info.line_start,
                "line_end": info.line_end,
                "raw_text": info.raw_text,
            }
            for name, info in ast.functions.items()
        },
    }


def _dict_to_file_ast(d: dict) -> FileAST:
    """Convert a dict back to FileAST."""
    from core.parser import FunctionInfo
    
    ast = FileAST(
        source_hash=d.get("source_hash", ""),
        has_parse_errors=d.get("has_parse_errors", False),
        error_count=d.get("error_count", 0),
        global_calls=d.get("global_calls", []),
    )
    
    for name, func_dict in d.get("functions", {}).items():
        ast.functions[name] = FunctionInfo(
            name=func_dict.get("name", name),
            params=func_dict.get("params", []),
            return_type=func_dict.get("return_type", "unknown"),
            calls=func_dict.get("calls", []),
            complexity=func_dict.get("complexity", 1),
            max_depth=func_dict.get("max_depth", 0),
            local_vars=func_dict.get("local_vars", []),
            memory_ops=func_dict.get("memory_ops", {}),
            pointer_ops=func_dict.get("pointer_ops", 0),
            has_recursion=func_dict.get("has_recursion", False),
            loop_count=func_dict.get("loop_count", 0),
            line_start=func_dict.get("line_start", 0),
            line_end=func_dict.get("line_end", 0),
            raw_text=func_dict.get("raw_text", ""),
        )
    
    return ast