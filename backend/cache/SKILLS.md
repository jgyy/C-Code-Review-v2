<!-- C-Code-Review backend/cache/, SKILLS.md. -->

# Skills: backend/cache/

| Task | Where |
|---|---|
| Read/write job status or results | `redis.py` (`enqueue_job`, `get_job_status`, `get_job_result`, `update_job_status`, `list_jobs`) — the only place job state should live |
| Expose cache stats | `get_cache_stats` in `redis.py` |
| Change a result TTL | `redis.py`, but check `../llm/SKILLS.md`'s caching notes first — TTLs are a deliberate cost/freshness tradeoff |
