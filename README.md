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
<img width="1487" height="774" alt="image" src="https://github.com/user-attachments/assets/202a34fb-f21b-4087-bb4f-5f77056abe07" />

### User Flow

1. **Log in** — authenticate via GitHub OAuth on the dashboard.
2. **Trigger analysis** — enter the repository owner, repo name, and PR number in the Quick Analyze panel and click Start Analysis.
3. **Wait for results** — the pipeline fetches both sides of every `.c` file, parses them into ASTs with tree-sitter, runs six structural heuristics, scores risk, and sends structured evidence to Gemini for review generation.
4. **View the GitHub PR comment** — a formatted review is posted automatically to the pull request with a risk badge, per-function findings, memory safety issues, and recommendations.
5. **View full results in the dashboard** — click the job to see all heuristic evidence, the LLM narrative, and cache statistics.

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
| boto3 | Invokes the worker Lambda asynchronously from the API Lambda |

**Deployed on AWS Lambda** (Serverless Framework) in `ap-southeast-1` — two functions: an API handler (29 s timeout) and an async worker (900 s timeout).

---

## Installation

### Prerequisites

- Python 3.11+
- Node.js 18+ / pnpm
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
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

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
