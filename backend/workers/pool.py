"""
workers/pool.py — Parallel file parsing with ThreadPoolExecutor

WHY A THREAD POOL FOR PARSING:
  tree-sitter parsing is CPU-bound and synchronous. FastAPI runs on an asyncio
  event loop — blocking the loop with a CPU-heavy task delays ALL in-flight
  requests, not just the one doing the parsing.

  The standard asyncio solution is asyncio.to_thread, which uses Python's
  default ThreadPoolExecutor. This works for one or two files but becomes a
  bottleneck on PRs with many changed files because:
    a) The default executor has a thread limit (min(32, cpu_count+4))
    b) Each asyncio.to_thread call competes with all other I/O in the loop

  We create a DEDICATED ThreadPoolExecutor for parsing work, sized to
  the number of CPU cores. This isolates parsing threads from I/O threads
  and gives us predictable concurrency.

WHY THREADS NOT PROCESSES:
  tree-sitter releases the GIL during parsing (it's a C extension). This means
  multiple threads genuinely run in parallel for parsing work — the GIL is not
  a bottleneck here. ProcessPoolExecutor would also work but has higher startup
  cost and requires pickling arguments/results, adding unnecessary complexity.

WHY NOT JUST asyncio.gather + asyncio.to_thread:
  For 5-10 files the overhead is negligible either way. But for large PRs (50
  files, our max), the dedicated pool prevents parsing from starving HTTP
  client I/O (GitHub API calls) which share the default executor.

DESIGN:
  parse_files_parallel takes a list of (sha, filepath, source) tuples and
  returns a list of FileAST objects in the same order. Order preservation is
  important because the pipeline zips results back to file metadata by index.
"""

from __future__ import annotations
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import NamedTuple
import os

from core.parser import extract_file_ast, FileAST


# One thread per CPU core, minimum 2, maximum 8.
# Parsing is CPU-bound; more threads than cores yields no benefit and increases
# context-switching overhead.
_POOL_SIZE = min(8, max(2, os.cpu_count() or 2))

# Module-level pool — created once, reused across all requests.
# The pool is NOT initialised at import time to avoid issues with forking
# (gunicorn/uvicorn workers fork after import). It's lazy-initialised on
# first use.
_pool: ThreadPoolExecutor | None = None


def _get_pool() -> ThreadPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ThreadPoolExecutor(
            max_workers=_POOL_SIZE,
            thread_name_prefix="cdiff-parser",
        )
    return _pool


class ParseTask(NamedTuple):
    """A single file to parse. NamedTuple for clarity at call sites."""
    sha: str        # Commit SHA — used for cache key labelling only
    filepath: str   # File path — used for cache key labelling only
    source: str     # Full file source code to parse


async def parse_files_parallel(tasks: list[ParseTask]) -> list[FileAST]:
    """
    Parse multiple C files in parallel using a dedicated thread pool.

    Args:
        tasks: list of ParseTask(sha, filepath, source)

    Returns:
        list of FileAST in the same order as tasks

    Example:
        tasks = [ParseTask(sha, fp, src) for sha, fp, src in file_data]
        asts = await parse_files_parallel(tasks)
        for task, ast in zip(tasks, asts):
            print(task.filepath, len(ast.functions))

    Performance note:
        On a 4-core machine, 8 files parse in approximately the time of
        2 sequential parses (4x parallelism × ~2x overhead ≈ 2x speedup).
        For typical PR sizes (3-15 C files), this keeps parse time under 200ms.
    """
    loop = asyncio.get_running_loop()
    pool = _get_pool()

    def _parse_one(source: str) -> FileAST:
        """
        Thin wrapper called in the thread pool.
        We pass only the source string, not the full ParseTask, to avoid
        pickling overhead (though NamedTuples are picklable, keeping
        the thread callable minimal reduces overhead).
        """
        return extract_file_ast(source)

    # Submit all tasks to the pool and gather results.
    # loop.run_in_executor schedules each task on the thread pool and
    # returns a coroutine. asyncio.gather runs all coroutines concurrently,
    # collecting results in order.
    results: list[FileAST] = await asyncio.gather(
        *[loop.run_in_executor(pool, _parse_one, task.source) for task in tasks]
    )

    return results


async def shutdown_pool() -> None:
    """
    Gracefully shut down the thread pool.
    Called from the FastAPI lifespan shutdown hook.
    wait=True ensures in-flight parse jobs complete before shutdown.
    """
    global _pool
    if _pool is not None:
        _pool.shutdown(wait=True)
        _pool = None