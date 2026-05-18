"""
workers/pool.py — Thread pool for parallel file parsing

Tree-sitter Parser objects are NOT thread-safe, but Language objects are.
We create a fresh Parser per parse call, which is fast (~1ms overhead).

This module provides a simple wrapper around concurrent.futures.ThreadPoolExecutor
for parallel file parsing. Each file gets its own thread and parser instance.
"""

from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, TypeVar, Iterator
from dataclasses import dataclass
import os

T = TypeVar("T")
R = TypeVar("R")


# Default to number of CPUs, capped at 8 for serverless environments
DEFAULT_WORKERS = min(os.cpu_count() or 4, 8)


@dataclass
class ParseResult:
    """Result from a parse operation."""
    filepath: str
    sha: str
    success: bool
    data: dict | None
    error: str | None = None


def parse_files_parallel(
    files: list[tuple[str, str, str]],  # (filepath, sha, content)
    parse_fn: Callable[[str], dict],
    max_workers: int = DEFAULT_WORKERS,
) -> Iterator[ParseResult]:
    """
    Parse multiple files in parallel.
    
    Args:
        files: List of (filepath, sha, content) tuples
        parse_fn: Function that takes content and returns parsed data dict
        max_workers: Maximum number of parallel workers
    
    Yields:
        ParseResult objects as they complete
    """
    def _parse_one(filepath: str, sha: str, content: str) -> ParseResult:
        try:
            data = parse_fn(content)
            return ParseResult(
                filepath=filepath,
                sha=sha,
                success=True,
                data=data,
            )
        except Exception as e:
            return ParseResult(
                filepath=filepath,
                sha=sha,
                success=False,
                data=None,
                error=str(e),
            )
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_parse_one, fp, sha, content): (fp, sha)
            for fp, sha, content in files
        }
        
        for future in as_completed(futures):
            yield future.result()


def map_parallel(
    items: list[T],
    fn: Callable[[T], R],
    max_workers: int = DEFAULT_WORKERS,
) -> list[R]:
    """
    Generic parallel map over items.
    
    Args:
        items: List of items to process
        fn: Function to apply to each item
        max_workers: Maximum number of parallel workers
    
    Returns:
        List of results in original order
    """
    results: list[tuple[int, R]] = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(fn, item): i
            for i, item in enumerate(items)
        }
        
        for future in as_completed(futures):
            idx = futures[future]
            try:
                results.append((idx, future.result()))
            except Exception as e:
                # Re-raise to let caller handle
                raise RuntimeError(f"Error processing item {idx}: {e}") from e
    
    # Sort by original index
    results.sort(key=lambda x: x[0])
    return [r for _, r in results]
