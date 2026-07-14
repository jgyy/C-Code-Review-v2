<!-- C-Code-Review, project-root CLAUDE.md. Keep this lean and repo-wide;
     anchor guidance on stable paths and symbols, not counts that rot.
     No em dashes, en dashes, or emojis. -->

# C-Code-Review

Structural risk analysis for C pull requests: AST-diff the changed functions, score risk from
weighted heuristics, and route only the risky ones through an LLM for a grounded, function-level
review — instead of asking an LLM to read a raw diff. Stack: FastAPI (Python) backend, Next.js
(TypeScript) frontend, Redis for job/result state, AWS Lambda worker, GitHub App/OAuth for auth
and PR comments.

## Repo map
| Path | What it is |
|---|---|
| `backend/api/routes.py` | REST endpoints: manual analyze trigger, job status/result, PR picker, cache stats. |
| `backend/core/parser.py` | C source -> AST (tree-sitter-based), per-function extraction. |
| `backend/core/heuristics.py` | The six weighted risk heuristics (memory imbalance, cyclomatic complexity, call-graph shift, orphaned functions, signature changes, etc). |
| `backend/core/triage.py` | Combines heuristics into a 0-100 risk score per function and per PR; selects the top-N functions for the LLM. |
| `backend/llm/client.py` | Gemini/Claude client: builds the bounded prompt, one LLM call per PR, retry/backoff, per-function result caching. |
| `backend/llm/prompts.py` | Prompt templates for the fast-path review and the Mermaid diagram generation. |
| `backend/github_utils/client.py` | PyGithub wrapper: PR info/files, PR listing, comment posting. Always authorize with the caller's own OAuth token for anything acting "as the user" (see Invariants). |
| `backend/github_utils/webhook.py` | GitHub webhook handler; enqueues the same pipeline the manual `/api/analyze` trigger uses. |
| `backend/workers/pipeline.py` | The end-to-end job pipeline: fetch PR -> parse -> triage -> LLM -> cache -> post comment. |
| `backend/cache/redis.py` | Job/result storage and cache-stats bookkeeping. |
| `backend/main.py` | FastAPI app wiring; router mount point (`/api`). |
| `frontend/lib/api.ts` | Typed API client; attaches the signed-in user's GitHub access token as `Authorization: Bearer` on every request. |
| `frontend/app/` | Next.js dashboard, search, and job/result pages. |
| `docs/ai-dev/` | AI-assisted development notes for this repo. |

## Commands
- Backend: `cd backend && uvicorn main:app --reload` (see `backend/SETUP.md`); tests live under `backend/tests`.
- Frontend: `cd frontend && pnpm dev`.
- Worker: `backend/worker.py` / `backend/serverless.yml` (Lambda deploy).

## Architecture (the load-bearing ideas)
- **Bounded LLM calls.** Exactly one LLM call per PR. Triage pre-selects the highest-risk
  functions (`MAX_FUNCTIONS_FOR_LLM`); everything else gets a static-analysis-only result
  synthesized from triage signals, indistinguishable from an LLM result at the API layer.
- **Risk-based model selection.** CRITICAL-risk PRs use the stronger model; everything else
  uses the fast/cheap one. Don't special-case this per endpoint — it lives in `llm/client.py`.
- **The user's own GitHub token is the authorization boundary.** Any endpoint that lists or
  acts on a user's repos/PRs (`/me/*`, `/repos/{owner}/{repo}/pulls`) must require and use the
  caller's `Authorization: Bearer <token>` (see `require_github_token` in `api/routes.py`), so
  GitHub itself enforces repo access. Never let a client-supplied identifier (an
  `installation_id`, a repo slug) alone select which credential or scope is used server-side.
- **Caching is keyed by content, not identity.** Per-function LLM results are cached by a hash
  of before/after source text (`RESULT_TTL` in `llm/client.py`), so identical functions across
  different PRs are never re-analyzed.

## Invariants
- Don't log full LLM prompts/responses or full job/PR-result payloads at `info` level — they can
  contain source code and PII. Use `debug` with sizes/counts, gated behind explicit debug config,
  and never pass raw `pr_evidence`/`file_asts`/`triage_result` objects to a logger.
- Don't trust a client-supplied `installation_id` (or any resource-selecting ID) to choose which
  GitHub credential is used. Resolve access from the authenticated user's own token.
- Don't hand-roll GitHub API pagination/search when the Search API already does it in one call
  (see `search_pull_requests` in `github_utils/client.py`).

## Conventions
- Python: FastAPI route handlers stay thin; business logic lives in `core/`, `llm/`, or `workers/`.
- TypeScript: all backend calls go through `frontend/lib/api.ts`'s shared `request()` helper so
  auth headers stay consistent — don't `fetch()` the backend directly from a component.
- Commits: Conventional Commits style (`feat: ...`, `fix: ...`, `security: ...`).

## Pointers
`README.md` (product overview, demo, architecture diagram) · `backend/SETUP.md` (local backend
setup) · `docs/ai-dev/` (AI-assisted development notes).
