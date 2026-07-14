<!-- C-Code-Review backend/api/, AGENTS.md. -->

# backend/api/

REST route handlers, mounted under `/api` by `main.py`.

| File | What it is |
|---|---|
| `routes.py` | All endpoints: manual analyze trigger, job status/result polling, PR picker (`/repos/{owner}/{repo}/pulls`), user-scoped PR lists (`/me/*`), cache stats. |
| `schemas.py` | Pydantic request/response models for these endpoints. |

## Conventions
- Handlers stay thin: validate input, call into `core/`/`llm/`/`workers/`/`cache/`, shape the
  response. No parsing, triage, or LLM logic inline here.
- Endpoints acting "as the logged-in user" (repo/PR lists, anything under `/me/*` or scoped by
  `owner/repo`) must call `require_github_token(authorization)` and pass that token down —
  never accept a client-supplied `installation_id` or similar to pick a credential.
- Don't log full request/response bodies at `info` level (job results and PR evidence can
  contain source code); use `debug` with sizes/counts if you need visibility.
