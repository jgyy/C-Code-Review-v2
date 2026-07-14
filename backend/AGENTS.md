<!-- C-Code-Review backend/, AGENTS.md. FastAPI service: parsing, triage, LLM,
     GitHub integration, job pipeline. See the root AGENTS.md for the
     product-level picture; this file is backend-local. -->

# backend/

FastAPI service. Entry point `main.py` (router mount at `/api`). Local dev: `uvicorn main:app
--reload`; see `SETUP.md`. Tests under `tests/`.

| Path | What it is |
|---|---|
| `api/` | REST route handlers — keep thin, no business logic (see `api/AGENTS.md`). |
| `core/` | Parsing, heuristics, and risk triage — the structural-analysis engine (see `core/AGENTS.md`). |
| `llm/` | LLM client, prompts, and schemas for the generated review (see `llm/AGENTS.md`). |
| `github_utils/` | PyGithub wrapper and webhook handling (see `github_utils/AGENTS.md`). |
| `workers/` | The end-to-end job pipeline invoked by both the webhook and manual trigger (see `workers/AGENTS.md`). |
| `cache/` | Redis-backed job/result storage (see `cache/AGENTS.md`). |
| `main.py` | FastAPI app wiring only — no route logic here, no route handlers. |
| `worker.py` / `serverless.yml` | Lambda worker entry point + deploy config. |

## Conventions
- Never put business logic directly in `main.py` or a route handler — it belongs in `core/`,
  `llm/`, or `workers/`.
- Any endpoint that reads/acts on a user's GitHub data must require and use that user's own
  OAuth token (`require_github_token` in `api/routes.py`), never a client-supplied identifier
  that selects server-side credentials.
