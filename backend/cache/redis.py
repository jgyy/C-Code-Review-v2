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
import logging
from dotenv import load_dotenv

from datetime import datetime, timezone

from upstash_redis.asyncio import Redis

load_dotenv()

logger = logging.getLogger(__name__)
# Global Redis client - created at module level for connection reuse
redis_client: Optional[Redis] = None

# Cache TTLs
AST_CACHE_TTL = 86400  # 24 hours
JOB_TTL = 3600  # 1 hour
RESULT_TTL = 86400 * 7  # 7 days


def _build_redis_client() -> Optional[Redis]:
    """
    Build a Redis client from environment variables.
    Called at lifespan startup AND lazily on first use, so Lambda cold starts
    that somehow skip lifespan still get a working client.
    """
    url = os.environ.get("UPSTASH_REDIS_REST_URL") or os.environ.get("KV_REST_API_URL")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN") or os.environ.get("KV_REST_API_TOKEN")

    if url and token:
        logger.info("Redis: connecting with explicit URL/token")
        return Redis(url=url, token=token)

    logger.warning(f"Redis: env vars missing (url={url!r}, token={'set' if token else 'unset'})")
    try:
        return Redis.from_env()
    except Exception as e:
        logger.error(f"Redis: from_env() failed: {e}")
        return None


async def init_redis() -> None:
    """Initialize the Redis client. Called from FastAPI lifespan on startup."""
    global redis_client
    redis_client = _build_redis_client()
    if redis_client is None:
        logger.error("Redis not configured — caching and job queue disabled")


def _get_redis() -> Optional[Redis]:
    """Return the Redis client, initialising lazily if needed (e.g. Lambda cold start)."""
    global redis_client
    if redis_client is None:
        redis_client = _build_redis_client()
    return redis_client


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
    rc = _get_redis()
    if not rc:
        return None
    
    key = f"ast:{sha}:{_hash_filepath(filepath)}"
    try:
        data = await rc.get(key)
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
    rc = _get_redis()
    if not rc:
        return False
    
    key = f"ast:{sha}:{_hash_filepath(filepath)}"
    try:
        await rc.set(key, json.dumps(ast_data), ex=AST_CACHE_TTL)
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
    rc = _get_redis()
    if not rc:
        logger.error("No redis client")
        return False
    
    try:
        # Store job metadata
        await rc.set(f"job:{job_id}", json.dumps({
            **job_data,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }), ex=JOB_TTL)
        
        # Add to queue
        await rc.lpush("job_queue", job_id)
        logger.info("Added to redis queue successfully")
        return True
    except Exception as e:
        print(f"Redis enqueue error: {e}")
    return False


async def dequeue_job() -> Optional[tuple[str, dict]]:
    """
    Get the next job from the queue.
    Returns (job_id, job_data) or None if queue is empty.
    """
    rc = _get_redis()
    if not rc:
        return None
    
    try:
        # Pop from queue (blocking with timeout)
        job_id = await rc.rpop("job_queue")
        if not job_id:
            return None
        
        # Get job metadata
        job_data = await rc.get(f"job:{job_id}")
        if job_data:
            data = json.loads(job_data) if isinstance(job_data, str) else job_data
            return (job_id, data)
    except Exception as e:
        print(f"Redis dequeue error: {e}")
    return None


async def update_job_status(job_id: str, status: str, result: Optional[dict] = None) -> bool:
    """Update job status and optionally store result."""
    rc = _get_redis()
    if not rc:
        return False
    
    try:
        # Merge with existing data if present; otherwise write a minimal record.
        # The key may have expired (JOB_TTL) if the worker took a long time to
        # start — we still write the status so polling endpoints see the update.
        existing = await rc.get(f"job:{job_id}")
        if existing:
            data = json.loads(existing) if isinstance(existing, str) else existing
        else:
            data = {"job_id": job_id}
        data["status"] = status
        if status == "processing" and "started_at" not in data:
            data["started_at"] = datetime.now(timezone.utc).isoformat()
        if status in ("completed", "failed") and "completed_at" not in data:
            data["completed_at"] = datetime.now(timezone.utc).isoformat()
        await rc.set(f"job:{job_id}", json.dumps(data), ex=JOB_TTL)
        
        # Store result if provided
        if result:
            await rc.set(f"result:{job_id}", json.dumps(result), ex=RESULT_TTL)
        
        return True
    except Exception as e:
        print(f"Redis update error: {e}")
    return False


async def get_job_status(job_id: str) -> Optional[dict]:
    """Get current job status."""
    rc = _get_redis()
    if not rc:
        return None
    
    try:
        data = await rc.get(f"job:{job_id}")
        if data:
            return json.loads(data) if isinstance(data, str) else data
    except Exception as e:
        print(f"Redis get error: {e}")
    return None


async def get_job_result(job_id: str) -> Optional[dict]:
    """Get job result if completed."""
    rc = _get_redis()
    if not rc:
        return None
    
    try:
        data = await rc.get(f"result:{job_id}")
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
    rc = _get_redis()
    if not rc:
        return ([], 0)

    try:
        # Get all job keys
        keys = await rc.keys("job:*")
        if not keys:
            return ([], 0)

        # Fetch all job data
        jobs = []
        for key in keys:
            try:
                data = await rc.get(key)
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
    rc = _get_redis()
    if not rc:
        return {"status": "disabled", "reason": "Redis not configured"}

    try:
        # Count keys by pattern (approximate)
        info = await rc.dbsize()
        return {
            "status": "connected",
            "total_keys": info,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}