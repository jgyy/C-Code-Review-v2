<!-- C-Code-Review, project-root AGENTS.md. AI-agent-agnostic entry point:
     followed by Claude Code, Codex, Cursor, or any other coding agent.
     Keep this lean and repo-wide; each subdirectory listed below has its
     own local AGENTS.md with area-specific guidance, loaded on demand when
     an agent works there — do not duplicate that detail here. Anchor
     guidance on stable paths and symbols, not counts that rot. No em
     dashes, en dashes, or emojis. -->

# C-Code-Review

Structural risk analysis for C pull requests: AST-diff the changed functions, score risk from
weighted heuristics, and route only the risky ones through an LLM for a grounded, function-level
review — instead of asking an LLM to read a raw diff. Stack: FastAPI (Python) backend, Next.js
(TypeScript) frontend, Redis for job/result state, AWS Lambda worker, GitHub App/OAuth for auth
and PR comments.

## Repo map
| Path | What it is |
|---|---|
| `backend/` | FastAPI service root; see `backend/AGENTS.md`. |
| `backend/api/` | REST endpoints: manual analyze trigger, job status/result, PR picker, cache stats. See `backend/api/AGENTS.md`. |
| `backend/core/` | AST parsing, risk heuristics, and triage — the structural-analysis engine. See `backend/core/AGENTS.md`. |
| `backend/llm/` | Gemini/Claude client, prompts, and schemas for the generated review. See `backend/llm/AGENTS.md`. |
| `backend/github_utils/` | PyGithub wrapper, diff parsing, webhook handling. See `backend/github_utils/AGENTS.md`. |
| `backend/workers/` | The end-to-end job pipeline: fetch PR -> parse -> triage -> LLM -> cache -> post comment. See `backend/workers/AGENTS.md`. |
| `backend/cache/` | Redis-backed job/result storage and cache stats. See `backend/cache/AGENTS.md`. |
| `backend/main.py` | FastAPI app wiring; router mount point (`/api`). |
| `frontend/` | Next.js dashboard; see `frontend/AGENTS.md` (and `frontend/app/`, `frontend/components/`, `frontend/lib/` for their own `AGENTS.md`). |
| `docs/ai-dev/` | AI-assisted development notes for this repo. |

Most directories above have their own `AGENTS.md`; read it when you work there.

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
