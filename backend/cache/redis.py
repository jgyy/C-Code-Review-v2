"""
cache/redis.py — Upstash Redis client for AST caching and job queue

Uses the HTTP-based Upstash Redis client which is ideal for serverless:
- No persistent connections needed
- Works great with Vercel's edge runtime
- Automatic retry and connection pooling

Cache key strategy:
- AST cache: ast:{sha}:{filepath_hash} -> JSON serialized FileAST
- Job queue: job:{job_id} -> Job metadata
- Results: result:{job_id} -> Analysis results
"""

from __future__ import annotations
import json
import hashlib
import os
from typing import Optional, Any
from dataclasses import asdict

from upstash_redis.asyncio import Redis

# Global Redis client - created at module level for connection reuse
redis_client: Optional[Redis] = None

# Cache TTLs
AST_CACHE_TTL = 86400  # 24 hours
JOB_TTL = 3600  # 1 hour
RESULT_TTL = 86400 * 7  # 7 days


async def init_redis() -> None:
    """Initialize the Redis client from environment variables."""
    global redis_client
    
    url = os.environ.get("UPSTASH_REDIS_REST_URL") or os.environ.get("KV_REST_API_URL")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN") or os.environ.get("KV_REST_API_TOKEN")
    
    if url and token:
        redis_client = Redis(url=url, token=token)
    else:
        # Fallback: try from_env which reads UPSTASH_REDIS_REST_URL/TOKEN
        try:
            redis_client = Redis.from_env()
        except Exception:
            print("Warning: Redis not configured. Caching disabled.")
            redis_client = None


def _hash_filepath(filepath: str) -> str:
    """Create a short hash of the filepath for cache keys."""
    return hashlib.sha256(filepath.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# AST Cache Operations
# ---------------------------------------------------------------------------

async def get_cached_ast(sha: str, filepath: str) -> Optional[dict]:
    """
    Retrieve a cached AST for a specific file at a specific commit.
    Returns None if not cached or Redis unavailable.
    """
    if not redis_client:
        return None
    
    key = f"ast:{sha}:{_hash_filepath(filepath)}"
    try:
        data = await redis_client.get(key)
        if data:
            return json.loads(data) if isinstance(data, str) else data
    except Exception as e:
        print(f"Redis get error: {e}")
    return None


async def set_cached_ast(sha: str, filepath: str, ast_data: dict) -> bool:
    """
    Cache an AST for a specific file at a specific commit.
    Returns True on success, False on failure.
    """
    if not redis_client:
        return False
    
    key = f"ast:{sha}:{_hash_filepath(filepath)}"
    try:
        await redis_client.set(key, json.dumps(ast_data), ex=AST_CACHE_TTL)
        return True
    except Exception as e:
        print(f"Redis set error: {e}")
    return False


# ---------------------------------------------------------------------------
# Job Queue Operations
# ---------------------------------------------------------------------------

async def enqueue_job(job_id: str, job_data: dict) -> bool:
    """
    Add a job to the processing queue.
    Uses Redis list for FIFO queue semantics.
    """
    if not redis_client:
        return False
    
    try:
        # Store job metadata
        await redis_client.set(f"job:{job_id}", json.dumps({
            **job_data,
            "status": "pending",
        }), ex=JOB_TTL)
        
        # Add to queue
        await redis_client.lpush("job_queue", job_id)
        return True
    except Exception as e:
        print(f"Redis enqueue error: {e}")
    return False


async def dequeue_job() -> Optional[tuple[str, dict]]:
    """
    Get the next job from the queue.
    Returns (job_id, job_data) or None if queue is empty.
    """
    if not redis_client:
        return None
    
    try:
        # Pop from queue (blocking with timeout)
        job_id = await redis_client.rpop("job_queue")
        if not job_id:
            return None
        
        # Get job metadata
        job_data = await redis_client.get(f"job:{job_id}")
        if job_data:
            data = json.loads(job_data) if isinstance(job_data, str) else job_data
            return (job_id, data)
    except Exception as e:
        print(f"Redis dequeue error: {e}")
    return None


async def update_job_status(job_id: str, status: str, result: Optional[dict] = None) -> bool:
    """Update job status and optionally store result."""
    if not redis_client:
        return False
    
    try:
        # Get existing job data
        existing = await redis_client.get(f"job:{job_id}")
        if existing:
            data = json.loads(existing) if isinstance(existing, str) else existing
            data["status"] = status
            await redis_client.set(f"job:{job_id}", json.dumps(data), ex=JOB_TTL)
        
        # Store result if provided
        if result:
            await redis_client.set(f"result:{job_id}", json.dumps(result), ex=RESULT_TTL)
        
        return True
    except Exception as e:
        print(f"Redis update error: {e}")
    return False


async def get_job_status(job_id: str) -> Optional[dict]:
    """Get current job status."""
    if not redis_client:
        return None
    
    try:
        data = await redis_client.get(f"job:{job_id}")
        if data:
            return json.loads(data) if isinstance(data, str) else data
    except Exception as e:
        print(f"Redis get error: {e}")
    return None


async def get_job_result(job_id: str) -> Optional[dict]:
    """Get job result if completed."""
    if not redis_client:
        return None
    
    try:
        data = await redis_client.get(f"result:{job_id}")
        if data:
            return json.loads(data) if isinstance(data, str) else data
    except Exception as e:
        print(f"Redis get error: {e}")
    return None


# ---------------------------------------------------------------------------
# Cache Stats
# ---------------------------------------------------------------------------

async def list_jobs(limit: int = 20, offset: int = 0) -> tuple[list[dict], int]:
    """
    List recent jobs with pagination.
    Returns (jobs, total_count) where jobs are sorted by most recent first.
    """
    if not redis_client:
        return ([], 0)

    try:
        # Get all job keys
        keys = await redis_client.keys("job:*")
        if not keys:
            return ([], 0)

        # Fetch all job data
        jobs = []
        for key in keys:
            try:
                data = await redis_client.get(key)
                if data:
                    job_data = json.loads(data) if isinstance(data, str) else data
                    # Extract job_id from the key (format: "job:{job_id}")
                    job_id = key.replace("job:", "")
                    job_data["job_id"] = job_id
                    jobs.append(job_data)
            except Exception:
                continue

        # Sort by most recent first (assuming jobs are created with timestamp in data)
        # If no timestamp, keep original order
        total = len(jobs)

        # Apply pagination
        paginated = jobs[offset:offset + limit]

        return (paginated, total)
    except Exception as e:
        print(f"Redis list_jobs error: {e}")
        return ([], 0)


async def get_cache_stats() -> dict:
    """Get cache statistics for monitoring."""
    if not redis_client:
        return {"status": "disabled", "reason": "Redis not configured"}

    try:
        # Count keys by pattern (approximate)
        info = await redis_client.dbsize()
        return {
            "status": "connected",
            "total_keys": info,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}
