<!-- C-Code-Review backend/cache/, AGENTS.md. -->

# backend/cache/

Redis-backed state: job status/results, per-function and per-PR LLM result caching, cache stats.

| File | What it is |
|---|---|
| `redis.py` | `enqueue_job`, `get_job_status`, `get_job_result`, `update_job_status`, `list_jobs`, `get_cache_stats`. |

## Conventions
- This is the single source of truth for job lifecycle state — don't track job status anywhere
  else (no in-memory dict, no second store).
- Result TTLs (job results, per-function LLM cache) are intentional cost/freshness tradeoffs;
  don't change them without checking `llm/AGENTS.md`'s caching notes.
