# C-Code-Review

## Overview

### Problem

- **Who is affected?** Developers and teams writing C, especially pull request reviewers.
- **What is the issue?** Manually reading text diffs in pull requests is inefficient and difficult. Especially if there are many files and the changes are scattered. Pull request descriptions written by collaboraters may be unreliable or non descriptive. Pull request reviewers are left wondering what logic was changed and whether accepting the changes will introduce new risks. 

### Outcome

- Automated structural analysis of C pull requests using AST diffing — detects memory imbalance, cyclomatic complexity changes, call graph shifts, orphaned functions, and signature changes and more.
- A risk score (0–100) computed from six weighted heuristics, routing the PR to an LLM that generates a grounded, function-level code review from structured evidence — not raw diffs.
- Review posted automatically as a GitHub PR comment with a risk badge, per-function breakdown, memory safety issues, and actionable recommendations.
- Results displayed in a dashboard with job history and cache statistics.

---

## Demo

### GitHub OAuth Login
<img width="1501" height="778" alt="image" src="https://github.com/user-attachments/assets/ba89bdb9-90f7-4076-abea-338bb6573d2c" />

<img width="1124" height="772" alt="image" src="https://github.com/user-attachments/assets/0d5941e0-522f-4626-bd2b-e009194b91f5" />

### Dashboard
<img width="1494" height="774" alt="image" src="https://github.com/user-attachments/assets/f7aa2d35-c835-403f-b1c9-f8a21641a9f3" />

### PR Analysis
<img width="1655" height="792" alt="Screenshot 2026-06-14 at 4 33 07 PM" src="https://github.com/user-attachments/assets/e2522eef-4dc6-459c-900c-d787df3e3a8d" />


### User Flow

1. **Log in** — authenticate via GitHub OAuth on the dashboard.
2. **Trigger analysis** — enter the repository owner, repo name, and PR number in the Quick Analyze panel and click Start Analysis.
3. **Wait for results** — the pipeline fetches both sides of every `.c` file, parses them into ASTs with tree-sitter, runs six structural heuristics, scores risk, and sends structured evidence to Gemini for review generation.
4. **View the GitHub PR comment** — a formatted review is posted automatically to the pull request with a risk badge, per-function findings, memory safety issues, and recommendations.
5. **View full results in the dashboard** — click the job to see all heuristic evidence, the LLM narrative, and cache statistics.

The comment posted on the PR includes:
- A one-sentence **headline** summarising the most important finding
- A **risk badge** (low / medium / high / critical) with a numeric score out of 100
- A **summary** paragraph explaining what changed and why it matters
- **Per-function breakdown** listing risk signals, memory issues, and a concrete suggestion for each changed function
- **Memory safety issues**, **security concerns**, and **potential bugs** as distinct labelled lists
- **Recommendations** the author can act on before merging

If the author pushes a new commit addressing the findings, analysis fires again automatically on the `synchronize` webhook event — the second run is faster because unchanged files hit the AST cache.

---

## Technology Stack

### Frontend

| Technology | Purpose |
|---|---|
| Next.js 16 (App Router) | React framework, file-based routing, server and client components |
| TypeScript | Type safety across API contracts and component props |
| Tailwind CSS 4 | Utility-first styling with custom dark theme |
| NextAuth.js (v4) | GitHub OAuth authentication, JWT sessions, route protection via middleware |
| SWR | Data fetching with automatic revalidation (10 s job polling, 30 s cache stats) |
| Radix UI | Accessible, unstyled UI primitives |
| Lucide React | Icon set |
| date-fns | Timestamp formatting |

**Deployed on Vercel** — API calls proxied to the backend via `vercel.json` rewrites, eliminating CORS.

### Backend

| Technology | Purpose |
|---|---|
| FastAPI | Async Python API framework |
| Mangum | AWS Lambda ASGI adapter — wraps FastAPI for Lambda compatibility |
| tree-sitter + tree-sitter-c | Deterministic C parser; produces full ASTs from both sides of every changed file |
| Gemini 2.5 Flash Lite | LLM for review generation; receives structured evidence, returns JSON |
| Upstash Redis | AST cache (keyed by SHA + filepath), job state, result persistence |
| PyGithub | GitHub API — file fetching, PR comment posting |
| rapidfuzz | Fuzzy function name matching for identity tracking across renames |
| Pydantic v2 | Data validation at every layer boundary |
| boto3 | Invokes the worker Lambda asynchronously from the API Lambda (included in `requirements.txt`) |

**Deployed on AWS Lambda** (Serverless Framework) in `ap-southeast-1` — two functions: an API handler (29 s timeout) and an async worker (900 s timeout).

---

## Architecture

```mermaid
flowchart LR
    PR["PR opened / updated"] --> WH["GitHub webhook"]
    WH --> API["FastAPI API handler"]
    API --> FETCH["Fetch both sides of every changed .c/.h file (PyGithub)"]
    FETCH --> CACHE{"Cached AST for this SHA?"}
    CACHE -->|hit| EVID
    CACHE -->|miss| PARSE["Parse to AST (tree-sitter)"]
    PARSE --> STORE["Cache AST by SHA + filepath (Redis)"]
    STORE --> EVID
    EVID["Identity tracking (rapidfuzz) + six structural heuristics"] --> TRIAGE{"Risk score (0-100)"}
    TRIAGE -->|low risk| LLM1["Single LLM call"]
    TRIAGE -->|high risk / large PR| LLM2["Map-reduce: one call per function + synthesis"]
    LLM1 --> REVIEW["Structured review JSON"]
    LLM2 --> REVIEW
    REVIEW --> DIAG["Mermaid call-graph diagram (validated, auto-fix retry)"]
    REVIEW --> COMMENT["Posted as GitHub PR comment"]
    DIAG --> COMMENT
    REVIEW --> DASH["Dashboard: job history, evidence, cache stats"]
```

The heuristic layer never hands the LLM a conclusion — only structured evidence (deltas, counts, function-level facts) — so the model explains findings grounded in the AST diff rather than re-describing the raw text diff.

---

## Installation

### Prerequisites

- Python 3.11–3.13 (as of this writing, `pydantic-core`/tree-sitter wheels don't yet support 3.14 — if `python3 -V` reports 3.14, install an older interpreter, e.g. `python3.12`, and use it below)
- Node.js 18+ and pnpm (see [Installing pnpm](#installing-pnpm) if you don't have it)
- An [Upstash Redis](https://upstash.com) database
- A [Gemini API key](https://aistudio.google.com/app/apikey)
- A [GitHub App](https://docs.github.com/en/apps/creating-github-apps) with:
  - Permissions: `contents: read`, `pull_requests: write`, `checks: write`
  - Webhook URL pointed at your backend (if using webhooks)
  - A generated private key

### Clone

```bash
git clone https://github.com/ainichew/C-Code-Review-v2.git
cd C-Code-Review-v2
```

### Backend

```bash
cd backend
python3.12 -m venv .venv          # use a 3.11–3.13 interpreter; see Prerequisites
source .venv/bin/activate.fish    # bash/zsh: .venv/bin/activate | Windows: .venv\Scripts\activate
python --version                  # sanity check: must print the interpreter above, not your system default
pip install -r requirements.txt
```

> **fish shell users:** `.venv/bin/activate` is a bash script and fails silently under `source` in fish (`case... not inside of switch block`) — every command afterwards then runs against your system Python instead of the venv. Use `.venv/bin/activate.fish`.
>
> If `python --version` inside the activated venv still shows your system Python (e.g. 3.14), the venv's `python` symlink was created pointing at the wrong interpreter — a known issue with some `uv`-managed Python installs. Delete `.venv` and re-run `python3.12 -m venv .venv`.

Create a `.env` file:

```bash
UPSTASH_REDIS_REST_URL=https://your-instance.upstash.io
UPSTASH_REDIS_REST_TOKEN=your-token
GEMINI_API_KEY=your-gemini-api-key
GITHUB_APP_ID=123456
GITHUB_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n..."
GITHUB_WEBHOOK_SECRET=your-webhook-secret
```

Run locally:

```bash
uvicorn main:app --reload --port 8000
```

Run tests (no API keys or Redis needed — `core/` is pure analysis, no I/O):

```bash
pip install -r requirements-dev.txt
pytest
```

### Installing pnpm

If `pnpm -v` fails, install it via Node's Corepack (bundled with Node 16.13+) or npm:

```bash
corepack enable && corepack prepare pnpm@latest --activate   # preferred
# or, if corepack is unavailable:
npm install -g pnpm
```

### Frontend

```bash
cd frontend
pnpm install
```

Create a `.env.local` file:

```bash
GITHUB_OAUTH_CLIENT_ID=your-client-id
GITHUB_OAUTH_CLIENT_SECRET=your-client-secret
NEXTAUTH_SECRET=your-secret
NEXTAUTH_URL=your-url
NEXT_PUBLIC_API_SERVICE=http://localhost:8000   # points to local backend
```

Run locally:

```bash
pnpm dev
# Open http://localhost:3000
```

### Deploy

**Frontend (Vercel):**
- Connect the repo to Vercel, set the root directory to `frontend/`.
- Add the environment variables above in the Vercel dashboard.
- `vercel.json` rewrites `/api/*` requests to the backend Lambda URL.

**Backend (AWS Lambda):**

```bash
cd backend
serverless deploy
```

The Serverless Framework (`serverless.yml`) deploys two Lambda functions:
- `api` — HTTP handler via API Gateway (29 s timeout, 512 MB).
- `worker` — async analysis worker invoked by the API function (900 s timeout, 512 MB).

Environment variables are loaded via `serverless-dotenv-plugin` from the `.env` file. tree-sitter binaries are provided as a Lambda Layer.

---

## Usage

Enter a repository owner, repo name, and PR number in the **Quick Analyze** panel on the dashboard. Click **Start Analysis**. The job appears in the dashboard. Once done, the review is posted as a comment on the GitHub PR and the full results (heuristic evidence, LLM narrative, cache stats) are viewable in the dashboard.


---

## Reflection

### What worked

**Parsing before diffing** was the right foundational decision. Operating on ASTs instead of text lines meant every downstream layer worked with semantic units — functions, call graphs, control flow — rather than line numbers and `+`/`-` characters.

**Structured evidence in LLM prompts rather than raw code** proved its value immediately. Feeding the model `complexity_delta: +8, malloc/free imbalance: +1, calls_added: ["memcpy"]` rather than 200 lines of C produced more accurate, more specific, and more consistent output. The model explains findings; the heuristics discover them.

**The triage layer as a cost gate** worked exactly as designed. Trivial PRs (renames, whitespace, comment-only changes) were skipped with no LLM call. Most real PRs hit the fast path in a single call. Only genuinely complex diffs triggered the map-reduce deep-analysis path, keeping API costs proportional to actual risk.

### What failed

**A package naming collision with PyGithub** was a silent failure mode early on — an internal module shadowed the installed `github` package. It didn't fail at import time with a clear error; it imported successfully and only crashed later when calling a PyGithub method that didn't exist on our own module. Renaming the internal module resolved it — any internal package sharing a name with an installed dependency is worth auditing for early.

**Naive set-diff on function names** initially treated every renamed function as a deletion + addition, cascading into false-positive orphan signals and inflated risk scores. Adding `rapidfuzz` identity tracking — pairing functions by name and signature similarity before diffing — eliminated this.

### Changes made and rationale

| Change | Rationale |
|---|---|
| Heuristics emit evidence bundles, not verdict strings | Verdict strings tell the LLM what to conclude. Evidence gives the LLM facts to reason from. The latter produces more grounded output with fewer hallucinated details. |
| Added `rapidfuzz` identity matching before diffing | Without it, any renamed function appears as a deletion + addition, cascading into false-positive orphan signals, inflated risk scores, and broken call graph diffs. |
| Map-reduce for high-risk/large PRs | A single-pass LLM call degraded accuracy near the end of long contexts on large diffs. Splitting into one call per function (parallelised) plus one synthesis call keeps every individual prompt small and accurate regardless of PR size. |
| Vercel proxy rewrite instead of CORS headers | Eliminates the browser preflight round-trip, removes the need to maintain an allow-list on the backend, and decouples the frontend deploy URL from the backend URL. |

---

## Project Structure

```
C-Code-Review-v2/
├── frontend/
│   ├── app/                     Next.js App Router pages (dashboard, jobs, login)
│   ├── components/              Reusable UI (dashboard widgets, job display, layout)
│   ├── lib/                     Shared utilities (typed API client, auth config)
│   ├── types/                   TypeScript type definitions
│   ├── middleware.ts            Route protection — redirects unauthenticated users
│   └── vercel.json              Proxy rewrites to backend, CORS headers
│
└── backend/
    ├── main.py                  FastAPI entry point + Mangum Lambda handler
    ├── worker.py                Async Lambda worker for long-running analysis
    ├── serverless.yml           AWS Lambda deployment config
    ├── core/                    Pure analysis — parser, heuristics, triage (no I/O)
    ├── llm/                     Gemini client, prompt templates, Pydantic schemas
    ├── github_utils/            GitHub API wrapper — file fetching, PR comments, webhooks
    ├── workers/                 Pipeline orchestrator + thread pool for parallel parsing
    ├── api/                     REST endpoints and request/response schemas
    └── cache/                   Upstash Redis client — AST cache, job state, results
```
