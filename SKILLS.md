<!-- C-Code-Review, project-root SKILLS.md. Task-oriented companion to
     AGENTS.md: "how do I do X here" rather than "how is this built". Each
     subdirectory has its own local SKILLS.md; read it when working there.
     Keep entries anchored on stable paths, not counts that rot. -->

# Skills: C-Code-Review

Common tasks across this repo, with the file(s) they touch.

| Task | Where |
|---|---|
| Add or change a backend endpoint | `backend/api/` — see `backend/api/SKILLS.md`; must call `require_github_token`, never a client-supplied credential ID |
| Add a new risk heuristic | `backend/core/heuristics.py`, wired into `backend/core/triage.py`'s weighting |
| Change LLM prompts, model selection, or caching | `backend/llm/` — see `backend/llm/SKILLS.md` |
| Change GitHub API integration or webhook handling | `backend/github_utils/` — see `backend/github_utils/SKILLS.md` |
| Change the end-to-end job pipeline | `backend/workers/pipeline.py` |
| Change job/result storage | `backend/cache/redis.py` — the single source of truth for job state |
| Add a new dashboard page | `frontend/app/(app)/` |
| Add a new dashboard widget or job view | `frontend/components/` — see `frontend/components/SKILLS.md` |
| Add a new backend call from the frontend | `frontend/lib/api.ts`'s `request()` helper (never a raw `fetch()`) |

See each subdirectory's `SKILLS.md` for area-specific task lists.
