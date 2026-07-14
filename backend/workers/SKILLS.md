<!-- C-Code-Review backend/workers/, SKILLS.md. -->

# Skills: backend/workers/

| Task | Where |
|---|---|
| Change a pipeline step (fetch, parse, triage, LLM, cache, comment) | `pipeline.py`, keep it identical whether triggered by webhook or manual trigger |
| Handle a step failure | mark the job `failed` in Redis via `../cache/redis.py`, don't leave it stuck at `pending` |
| Change worker concurrency/pooling | `pool.py` |
