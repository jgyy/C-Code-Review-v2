# SPull — Intelligent C Code Review

## Overview

SPull is an automated pull request review system for C codebases. It connects to GitHub as an App, intercepts PRs the moment they are opened, parses both sides of every changed file into an Abstract Syntax Tree, runs a battery of structural heuristics, and sends the resulting evidence bundle to an LLM that writes a grounded, function-level code review — posted back to the PR as a comment within seconds.

The system is built around a clean separation: deterministic analysis (tree-sitter, heuristics, triage) runs first and is always fast and free; the LLM only sees structured evidence, not raw diffs, so it explains findings rather than guesses at them.

---

## Problem

**Who is affected:** Engineering teams writing C — embedded systems, firmware, kernel modules, game engines, systems libraries. C has no memory safety guarantees, no exception handling, and minimal static analysis built into the language itself. A single `malloc` without a corresponding `free`, a pointer arithmetic error, or a silently changed function signature can ship unnoticed through a standard PR review.

**What is the issue:** Human reviewers miss memory safety errors because they are cognitively expensive to trace across function boundaries. Existing static analysis tools (cppcheck, clang-tidy) report on individual files in isolation — they have no concept of what changed between two commits, so they cannot answer the question a reviewer actually needs answered: *is this specific change introducing risk that was not there before?* The diff is the unit of work; existing tools don't treat it as one.

---

## Outcome

- **Automated detection of memory imbalance** (unmatched `malloc`/`free`) across every function changed in a PR, surfaced as a labelled risk signal before any human reads the diff.
- **Six structural heuristics** extracted from the AST diff — cyclomatic complexity delta, call graph changes, nesting depth, variable scope, orphan/dead-code detection, signature changes — each weighted into a 0–100 risk score that routes the PR to the appropriate LLM path.
- **Two-tier LLM analysis:** low-risk PRs resolved in a single API call (~3s); high-risk or large PRs processed via a map-reduce pattern (one call per function in parallel, one synthesis call) keeping individual prompts small and accurate regardless of PR size.
- **AST caching by commit SHA:** files that appear in multiple PRs at the same commit are parsed once. On active repositories this eliminates the majority of parsing work on re-runs and follow-up pushes.
- **GitHub PR comment posted automatically** with headline, risk level, per-function breakdown, memory safety issues, and actionable recommendations — no developer action required beyond opening the PR.

---

## Demo
## Product Screenshots

## GitHub OAuth based login
<img width="1501" height="778" alt="image" src="https://github.com/user-attachments/assets/ba89bdb9-90f7-4076-abea-338bb6573d2c" />

<img width="1124" height="772" alt="image" src="https://github.com/user-attachments/assets/0d5941e0-522f-4626-bd2b-e009194b91f5" />

## Dashboard
<img width="1494" height="774" alt="image" src="https://github.com/user-attachments/assets/f7aa2d35-c835-403f-b1c9-f8a21641a9f3" />

## PR Analysis
<img width="1487" height="774" alt="image" src="https://github.com/user-attachments/assets/202a34fb-f21b-4087-bb4f-5f77056abe07" />

### From the user's perspective, start to finish

**1. Install the GitHub App on a repository.**
The developer visits the dashboard, connects their GitHub account via OAuth, and installs the SPull GitHub App on one or more repositories. No configuration files, no CI changes required.

**2. Open a pull request.**
The developer opens a PR as normal. SPull receives the webhook event within milliseconds.

**3. Dashboard shows the job in real time.**
In the SPull dashboard the PR appears immediately as a pending job. A progress indicator shows which files are being parsed. Stats cards update — total jobs, cache hit rate — as the pipeline runs.

**4. Analysis completes (3–15 seconds).**
The pipeline fetches both sides of every `.c` and `.h` file, parses them into ASTs, runs all six heuristics, scores risk, and routes to fast-path or deep analysis. The LLM receives structured evidence — not raw code — and returns a JSON review.

**5. GitHub PR receives an automated comment.**
The comment includes:
- A one-sentence **headline** summarising the most important finding
- A **risk badge** (low / medium / high / critical) with a numeric score out of 100
- A **summary** paragraph explaining what changed and why it matters
- **Per-function breakdown** listing risk signals, memory issues, and a concrete suggestion for each changed function
- **Memory safety issues**, **security concerns**, and **potential bugs** as distinct labelled lists
- **Recommendations** the author can act on before merging

**6. Developer views full results in the dashboard.**
Clicking the job shows the complete analysis: all heuristic evidence (complexity deltas, call graph diffs, orphaned functions, signature changes), the LLM narrative, and cache statistics for the run.

**7. Developer iterates.**
If the author pushes a new commit addressing the findings, SPull fires again automatically on the `synchronize` webhook event. The second run is faster because unchanged files hit the AST cache.

---

## Tech Stack

### Frontend — client-side technologies used for user interaction

| Technology | Purpose |
|---|---|
| **Next.js 14** (App Router) | React framework, file-based routing, server and client components |
| **TypeScript** | End-to-end type safety across API contracts and component props |
| **Tailwind CSS** | Utility-first styling with custom dark theme; status and risk colour tokens defined as CSS variables |
| **SWR** | Data fetching with automatic revalidation for live job status polling (10s interval on jobs, 30s on cache stats) |
| **NextAuth.js v5** | GitHub OAuth authentication, JWT session management, route protection via Next.js middleware |
| **Lucide React** | Icon set |
| **date-fns** | Timestamp formatting for job history display |

### Backend — server-side technologies used for processing, APIs, and coordination

| Technology | Purpose |
|---|---|
| **FastAPI** | Async Python API framework; handles webhook ingestion, job queuing, and result retrieval |
| **uvicorn** | ASGI server running the FastAPI application |
| **tree-sitter + tree-sitter-c** | Deterministic, error-tolerant C parser; produces full ASTs from both sides of every changed file |
| **tree-sitter-language-pack** | Pre-compiled grammar library covering 40+ languages for future extension without grammar maintenance |
| **rapidfuzz** | Fuzzy function name matching for identity tracking across renames (Levenshtein ratio scoring) |
| **Gemini 2.0 Flash** (`google-genai`) | Runtime LLM for fast-path and deep-analysis review generation; JSON output mode enforced at API level |
| **Upstash Redis** | AST snapshot cache keyed by `(sha, filepath)`, job state storage, result persistence; HTTP client works without persistent TCP connections |
| **PyGithub** | GitHub API wrapper for fetching file contents at specific SHAs, posting PR comments, creating check runs |
| **asyncio + ThreadPoolExecutor** | Parallel file parsing — tree-sitter releases the GIL so threads run genuinely in parallel; dedicated pool isolated from I/O threads |
| **Pydantic v2** | Data validation at every layer boundary: API requests, LLM output, internal pipeline structs |
| **ngrok** | Local tunnel exposing the FastAPI server for GitHub webhook delivery during development |

---

## Development Approach with AI

### AI tools, services, and models — and their purposes

| Tool / Model | Purpose |
|---|---|
| **Claude Sonnet** (claude.ai) | Primary development agent — architecture design, all code generation, debugging, integration guidance, and documentation |
| **Gemini 2.0 Flash** (Google AI Studio) | Runtime LLM embedded in the product — generates PR review narratives from structured heuristic evidence at inference time |
| **Claude Artifacts** | Iterative frontend prototyping — generated and refined the vanilla HTML/CSS/JS prototype before the Next.js migration, allowing rapid visual iteration without a build step |

### AI agents — roles and skills

| Agent | Role | Skills applied |
|---|---|---|
| **Architect** | Designed the layered pipeline (parse → heuristics → triage → LLM → output) and identified identity tracking and map-reduce as required components before any code was written | System design, trade-off analysis, static analysis domain knowledge |
| **Builder** | Wrote all backend Python modules with inline technical rationale comments explaining every non-obvious decision | Python, FastAPI, asyncio, tree-sitter API, Pydantic, Redis patterns |
| **Frontend builder** | Built the vanilla HTML prototype, then proposed and scaffolded the Next.js migration with full component structure and typed API client | TypeScript, React, Next.js App Router, Tailwind, SWR, NextAuth |
| **Reviewer** | Audited import chains, caught the `github`/PyGithub package collision, identified the `google.generativeai` deprecation before production, diagnosed and fixed Pydantic `Optional` field errors | Dependency auditing, static analysis, runtime error diagnosis |
| **Documentation writer** | Authored the integration guide, inline code comments, and this README with technical detail drawn from the actual source files rather than generic descriptions | Technical writing, accuracy verification against live code |

### Key prompts used

- *"Propose the top useful heuristics I can apply using information gotten from the tree-sitter parser"* — produced the six-heuristic framework (H1–H6) that became the core of the structural analysis layer.
- *"What tech stack and architecture would you propose?"* — produced the full layered architecture with identity tracking, triage routing, and map-reduce LLM as distinct design decisions, each with explicit written rationale.
- *"Build it and leave comprehensive explanations on all major technical choices"* — established the pattern of inline docstrings justifying every non-obvious decision rather than only describing what the code does.
- *"The frontend is currently deployed on Vercel. Explain the exact specific steps to connect the frontend and backend"* — generated the `INTEGRATION.md` covering the Vercel proxy rewrite pattern, environment variable setup, and the reasoning behind each choice.
- *"Propose how user management should be added"* — produced the NextAuth.js + GitHub OAuth proposal fitted specifically to the existing Next.js stack and component structure rather than a generic authentication tutorial.

### Key review points and decisions made

| Review point | Decision made |
|---|---|
| `github/` package directory shadowed PyGithub at import time | Renamed internal package `github/` → `gh/`. Any package sharing a name with an installed dependency causes unpredictable import behaviour. |
| `google.generativeai` was deprecated with no further bug fixes | Migrated to `google.genai`. Client pattern changed from module-level `configure()` + `GenerativeModel()` to `genai.Client(api_key=...)` — cleaner, no global state, actively maintained. |
| Pydantic `ValidationError` on `AnalysisResultResponse` for in-progress jobs | Changed `files_analyzed`, `cache_hits`, `cache_misses` from required `int` to `Optional[int] = None`. Fields that only exist on completed jobs must be optional for the schema to be valid at every lifecycle stage. |
| Single-pass LLM on large PRs degraded accuracy at the end of long contexts | Introduced map-reduce: one call per function parallelised via `asyncio.gather`, one synthesis call. Every individual call stays under 500 tokens of input. |
| Naive set-diff on function names treated all renames as deletion + addition | Added `rapidfuzz` identity tracking before diffing. Functions are paired by name and signature similarity first, eliminating false-positive orphan signals and inflated risk scores. |
| Heuristic layer emitting verdict strings fed to the LLM | Changed to structured evidence bundles. The LLM receives facts (delta values, counts, lists), not pre-written conclusions. The model interprets evidence rather than repackaging verdicts. |
| Frontend hardcoded to `localhost:5000` | Introduced `vercel.json` proxy rewrites. The browser makes same-origin requests to `/api/*`; Vercel forwards them to the backend — eliminating CORS entirely and decoupling the frontend deploy from the backend URL. |

---

## Installation

### Prerequisites

- Python 3.11+
- Node.js 18+
- An [Upstash Redis](https://upstash.com) database (free tier sufficient)
- A GitHub Personal Access Token with `repo` scope (or a GitHub App for production)
- A [Gemini API key](https://aistudio.google.com/app/apikey)
- [ngrok](https://ngrok.com) for local webhook delivery in development

### Backend

```bash
git clone https://github.com/your-org/spull.git
cd spull/backend

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# Fill in: GITHUB_TOKEN, GEMINI_API_KEY, UPSTASH_REDIS_REST_URL, UPSTASH_REDIS_REST_TOKEN, GITHUB_WEBHOOK_SECRET

uvicorn main:app --reload --port 8000
```

### Frontend

```bash
cd spull/frontend

npm install

cp .env.example .env.local
# Fill in: GITHUB_OAUTH_CLIENT_ID, GITHUB_OAUTH_CLIENT_SECRET, AUTH_SECRET, NEXT_PUBLIC_API_SERVICE

npm run dev
# Open http://localhost:3000
```

### Expose backend for webhook delivery (development)

```bash
ngrok http 8000
# Copy the HTTPS URL e.g. https://a1b2c3d4.ngrok-free.app
# Set as GitHub webhook URL:  https://a1b2c3d4.ngrok-free.app/webhook
# Update vercel.json destination to match, then: vercel --prod
```

### Verify

```bash
# Health check
curl http://localhost:8000/health
# → {"status":"healthy","service":"c-code-review"}

# Manual trigger
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"owner":"your-org","repo":"your-repo","pr_number":1}'
# → {"job_id":"manual-...","status":"pending","message":"..."}

# Poll result
curl http://localhost:8000/api/status/JOB_ID_HERE
```

---

## Usage

**Automatic via webhook:** Open any PR in a repository where the GitHub App is installed. SPull fires automatically and posts a review comment within 3–15 seconds. Nothing else required.

**Manual via dashboard:** Enter owner / repo / PR number in the Quick Analyze panel, click Start Analysis. The job page updates in real time via SWR polling.

**Manual via API:**
```bash
# Trigger
curl -X POST https://your-backend/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"owner":"your-org","repo":"your-repo","pr_number":42}'

# Poll until completed
curl https://your-backend/api/status/JOB_ID

# Fetch full result
curl https://your-backend/api/result/JOB_ID
```

---

## Project Structure

```
spull/
│
├── backend/
│   ├── main.py                  FastAPI entry point, lifespan hooks, router registration
│   ├── requirements.txt
│   ├── .env.example
│   │
│   ├── core/                    Pure analysis logic — no I/O, no external service calls
│   │   ├── parser.py            tree-sitter wrapper; extracts FunctionInfo structs from C source
│   │   ├── heuristics.py        Six structural heuristics + rapidfuzz identity tracking
│   │   └── triage.py            Risk scoring (0–100) and route decision (skip / fast / deep)
│   │
│   ├── llm/
│   │   ├── schemas.py           Pydantic models for LLM I/O (PRAnalysis, FunctionAnalysis)
│   │   └── client.py            GeminiClient — fast-path (single call) and deep (map-reduce)
│   │
│   ├── workers/
│   │   ├── pool.py              Dedicated ThreadPoolExecutor for parallel file parsing
│   │   └── pipeline.py          Main orchestrator — fetch → cache → parse → heuristics → triage → LLM
│   │
│   ├── gh/                      GitHub integration (gh/ not github/ to avoid shadowing PyGithub)
│   │   ├── client.py            Async PyGithub wrapper — file content, PR comments, check runs
│   │   ├── diff_parser.py       Unified diff parser; maps changed lines to function boundaries
│   │   └── webhook.py           FastAPI router — receives, verifies, and queues webhook events
│   │
│   ├── api/
│   │   ├── routes.py            REST endpoints: /analyze, /status/{id}, /result/{id}, /cache/stats
│   │   └── schemas.py           Pydantic models for API request and response contracts
│   │
│   └── cache/
│       └── redis.py             Upstash Redis — AST cache, job state, result persistence
│
└── frontend/
    ├── app/
    │   ├── layout.tsx           Root layout — fonts, SessionProvider, Sidebar + Header shell
    │   ├── page.tsx             Dashboard — stats cards, recent jobs, quick analyze
    │   ├── jobs/                Job list and individual job detail pages
    │   └── api/auth/            NextAuth route handler
    │
    ├── components/
    │   ├── dashboard/           StatsCards, RecentJobs, QuickAnalyze
    │   ├── jobs/                JobStatusBadge, RiskBadge, function analysis display
    │   └── layout/              Sidebar, Header, UserMenu
    │
    ├── lib/
    │   ├── api.ts               Typed fetch client — all backend calls centralised here
    │   ├── auth.ts              NextAuth config — GitHub OAuth, JWT callbacks, session types
    │   └── utils.ts             cn() helper (clsx + tailwind-merge)
    │
    ├── middleware.ts             Route protection — redirects unauthenticated users to /login
    └── vercel.json              Proxy rewrites — /api/* → backend URL, eliminates CORS
```

---

## Reflection

### What worked

**Parsing before diffing** was the right foundational decision. Operating on ASTs instead of text lines meant every downstream layer worked with semantic units — functions, call graphs, control flow — rather than line numbers and `+`/`-` characters. The quality of analysis is qualitatively better than any text-diff approach could produce.

**Structured evidence in LLM prompts rather than raw code** proved its value immediately. Feeding the model `complexity_delta: +8, malloc/free imbalance: +1, calls_added: ["memcpy"]` rather than 200 lines of C produced more accurate, more specific, and more consistent output. The model explains findings; the heuristics discover them.

**The triage layer as a cost gate** worked exactly as designed. Trivial PRs (renames, whitespace, comment-only changes) were skipped with no LLM call. Most real PRs hit the fast path at ~3 seconds. Only genuinely complex diffs triggered deep analysis. API costs stayed proportional to actual risk.

**Inline technical rationale in code comments** was unconventional but paid off. Every non-obvious decision — why threads not processes, why `compare_digest` not `==`, why the package was renamed — is explained at the point of decision. Debugging was faster because the reasoning was always co-located with the code.

### What failed

**The `github/` package naming collision** was a silent failure mode. The backend imported PyGithub as `from github import Github`, but our own `github/` directory shadowed it when running from the project root. It didn't fail at import time with a clear error — it imported our blank `__init__.py` successfully and only crashed later when calling `.get_pull()` on a non-existent attribute.

**`google.generativeai` deprecation** was not caught until runtime. The old SDK imported cleanly and appeared to work; the deprecation only surfaced as a warning during integration testing rather than a hard failure. Dependency lifecycle auditing at requirements-pin time would have caught this earlier.

**The `AnalysisResultResponse` schema** was designed around the completed state only. Fields like `files_analyzed`, `cache_hits`, and `cache_misses` were defined as required integers. The schema was correct for a finished job but crashed with a Pydantic `ValidationError` when the status endpoint tried to return an in-progress job that hadn't populated those fields yet.

### Changes made and rationale

| Change | Rationale |
|---|---|
| `github/` → `gh/` | Any package you own that shares a name with an installed library will cause unpredictable import behaviour — silent at import time, crashing at call time. Rename early. |
| `google.generativeai` → `google.genai` | Deprecated SDK, no further bug fixes. New SDK removes global state (`configure()` → `Client(api_key=...)`), actively maintained, enforces JSON output mode at the API level. |
| Heuristics emit evidence bundles, not verdict strings | Verdict strings tell the LLM what to conclude. Evidence gives the LLM facts to reason from. The latter produces more grounded output with fewer hallucinated details. |
| Added `rapidfuzz` identity matching before diffing | Without it, any renamed function appears as a deletion + addition, cascading into false-positive orphan signals, inflated risk scores, and broken call graph diffs. |
| `Optional[int] = None` on lifecycle-conditional fields | Pydantic schemas must be valid at every stage of a job's lifecycle, not just the terminal state. Fields that don't exist yet must be optional or every intermediate status response crashes. |
| Vercel proxy rewrite instead of CORS headers | Eliminates the browser preflight round-trip, removes the need to maintain an `ALLOWED_ORIGINS` list on the backend, and decouples the frontend deploy URL from the backend URL — change the backend host without touching the frontend. |
