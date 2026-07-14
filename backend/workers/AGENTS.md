<!-- C-Code-Review backend/workers/, AGENTS.md. -->

# backend/workers/

The end-to-end analysis job pipeline, run either as the Lambda worker (`worker.py`) or in-process
during local dev (`WORKER_MODE=local`, see `api/routes.py`).

| File | What it is |
|---|---|
| `pipeline.py` | Fetch PR -> parse -> triage -> LLM -> cache -> post GitHub comment, in order. |
| `pool.py` | Worker pooling/concurrency helpers. |

## Conventions
- The pipeline must stay identical whether triggered by the GitHub webhook or the manual
  `/api/analyze` endpoint — both enqueue the same job shape and run through this module.
- A pipeline step failing should mark the job `failed` in Redis (via `cache/redis.py`) rather than
  leaving it stuck at `pending` forever.
