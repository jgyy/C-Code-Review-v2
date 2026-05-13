# C Code Review System - Setup Guide

A Python backend service that provides intelligent C code review on GitHub PRs using AST analysis and LLM insights.

## Architecture Overview

```
backend/
├── main.py                 # FastAPI entry point
├── pyproject.toml          # Dependencies
├── core/
│   ├── parser.py           # Tree-sitter C parsing
│   ├── heuristics.py       # Identity matching, structural metrics
│   └── triage.py           # Risk scoring and routing
├── workers/
│   ├── pool.py             # Parallel processing
│   └── pipeline.py         # Main orchestration
├── llm/
│   ├── client.py           # Gemini API client
│   ├── prompts.py          # Prompt templates
│   └── schemas.py          # Data models
├── github/
│   ├── client.py           # PyGithub wrapper
│   ├── webhook.py          # Webhook handler
│   └── diff_parser.py      # Diff parsing utilities
├── cache/
│   └── redis.py            # Upstash Redis client
└── api/
    ├── routes.py           # REST endpoints
    └── schemas.py          # API models
```

## Prerequisites

- Python 3.11+
- Upstash Redis account (for caching and job queue)
- Google Cloud account with Gemini API access
- GitHub account (for GitHub App setup)

## Environment Variables

Create a `.env` file or set these environment variables:

```bash
# Upstash Redis (required)
UPSTASH_REDIS_REST_URL=https://your-instance.upstash.io
UPSTASH_REDIS_REST_TOKEN=your-token

# Gemini API (required for LLM analysis)
GEMINI_API_KEY=your-gemini-api-key

# GitHub (choose one authentication method)

# Option 1: Personal Access Token (for testing)
GITHUB_TOKEN=ghp_your_personal_access_token

# Option 2: GitHub App (for production)
GITHUB_APP_ID=123456
GITHUB_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n..."
GITHUB_WEBHOOK_SECRET=your-webhook-secret
```

## Local Development

1. **Install dependencies:**
   ```bash
   cd backend
   pip install -e .
   ```

2. **Run the server:**
   ```bash
   uvicorn main:app --reload --port 8000
   ```

3. **Test the API:**
   ```bash
   # Health check
   curl http://localhost:8000/health

   # Manual analysis (requires GITHUB_TOKEN)
   curl -X POST http://localhost:8000/analyze \
     -H "Content-Type: application/json" \
     -d '{"owner": "your-org", "repo": "your-repo", "pr_number": 123}'

   # Check job status
   curl http://localhost:8000/status/job-id-here

   # Get analysis result
   curl http://localhost:8000/result/job-id-here
   ```

## GitHub App Setup

For production use with webhooks, create a GitHub App:

### 1. Create the App

1. Go to **GitHub Settings > Developer settings > GitHub Apps > New GitHub App**
2. Fill in the details:
   - **Name:** C Code Reviewer (or your preferred name)
   - **Homepage URL:** Your deployment URL
   - **Webhook URL:** `https://your-domain.com/webhook`
   - **Webhook secret:** Generate a secure random string

### 2. Configure Permissions

Under "Repository permissions":
- **Contents:** Read (to fetch file contents)
- **Pull requests:** Read & Write (to read PR info and post comments)
- **Checks:** Read & Write (optional, for status checks)

### 3. Subscribe to Events

Under "Subscribe to events":
- Check **Pull request**

### 4. Generate Private Key

1. After creating the app, scroll to "Private keys"
2. Click "Generate a private key"
3. Download the `.pem` file
4. Convert to a single-line string for the environment variable:
   ```bash
   cat your-key.pem | awk 'NF {sub(/\r/, ""); printf "%s\\n", $0}'
   ```

### 5. Install the App

1. Go to your app's page
2. Click "Install App"
3. Select the repositories you want to enable

### 6. Note the IDs

- **App ID:** Found on the app's settings page
- **Installation ID:** Found in the URL after installing (or via API)

## API Endpoints

### POST /webhook
GitHub webhook receiver. Handles `pull_request` events.

### POST /analyze
Manually trigger PR analysis.

**Request:**
```json
{
  "owner": "organization",
  "repo": "repository",
  "pr_number": 123,
  "installation_id": 12345678  // optional, for GitHub App auth
}
```

**Response:**
```json
{
  "job_id": "manual-org-repo-123-abc12345",
  "status": "pending",
  "message": "Analysis queued for organization/repository#123"
}
```

### GET /status/{job_id}
Check job status.

**Response:**
```json
{
  "job_id": "manual-org-repo-123-abc12345",
  "status": "completed",
  "files_analyzed": 3,
  "functions_analyzed": 12,
  "cache_hits": 2,
  "cache_misses": 4
}
```

### GET /result/{job_id}
Get full analysis result.

**Response:**
```json
{
  "job_id": "manual-org-repo-123-abc12345",
  "status": "completed",
  "headline": "Medium-risk changes to memory management",
  "risk_level": "medium",
  "risk_score": 45,
  "summary": "This PR modifies 3 functions with memory allocation changes...",
  "insights": ["New malloc in process_data without corresponding free"],
  "recommendations": ["Add free() call before function returns"],
  "function_analyses": [...],
  "memory_safety_issues": ["Potential leak in process_data()"],
  "security_concerns": [],
  "potential_bugs": []
}
```

### GET /cache/stats
Get cache statistics.

### GET /health
Health check endpoint.

## How It Works

### 1. Ingestion
When a PR webhook arrives or manual analysis is triggered:
- Verify webhook signature (if applicable)
- Queue job in Redis
- Return job ID immediately

### 2. Parsing
For each changed C/H file:
- Check Redis cache for existing AST at `(sha, filepath)`
- Parse cache misses using tree-sitter
- Store new ASTs in cache (24h TTL)

### 3. Heuristics
Compute structural metrics:
- **Identity tracking:** Match functions across renames using rapidfuzz
- **Complexity delta:** McCabe complexity changes
- **Memory ops:** malloc/free balance changes
- **Call graph:** Added/removed function calls
- **Signature changes:** Parameter and return type modifications

### 4. Triage
Score the evidence and decide routing:
- **Skip:** Trivial changes (renames, formatting)
- **Fast path:** Low-medium risk, single LLM call
- **Deep analysis:** High risk, map-reduce over functions

### 5. LLM Analysis
Generate insights using Gemini:
- Fast path: Single prompt with evidence bundle
- Deep path: Per-function analysis (map) + synthesis (reduce)

### 6. Output
Post results as a PR comment with:
- Risk level and score
- Key insights
- Per-function findings
- Actionable recommendations

## Caching Strategy

AST snapshots are cached by `(commit_sha, filepath)`:
- Key format: `ast:{sha}:{filepath_hash}`
- TTL: 24 hours
- Benefits: Files unchanged across PRs skip re-parsing

Job data is cached temporarily:
- Key format: `job:{job_id}`, `result:{job_id}`
- TTL: 1 hour for jobs, 7 days for results

## Customization

### Adjusting Risk Thresholds

Edit `backend/core/triage.py`:
```python
WEIGHTS = {
    "memory_imbalance": 30,      # Weight for malloc/free imbalance
    "complexity_increase_high": 20,  # High complexity delta
    # ... adjust as needed
}
```

### Modifying LLM Prompts

Edit `backend/llm/prompts.py` to customize:
- System prompts for different analysis modes
- User prompt templates with evidence formatting
- Output JSON schemas

### Adding Language Support

The parser uses tree-sitter-language-pack. To add languages:
1. Import the grammar in `core/parser.py`
2. Add file extension filters in `workers/pipeline.py`
3. Update heuristics for language-specific patterns

## Troubleshooting

### "Redis not configured" warning
Ensure `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN` are set.

### "API key not configured" in analysis
Set `GEMINI_API_KEY` for LLM analysis. Without it, only static analysis runs.

### GitHub webhook signature failures
Verify `GITHUB_WEBHOOK_SECRET` matches the secret in your GitHub App settings.

### Rate limiting
- GitHub: Use a GitHub App for higher limits
- Gemini: Check your quota at console.cloud.google.com
