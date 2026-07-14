<!-- C-Code-Review backend/github_utils/, AGENTS.md. -->

# backend/github_utils/

GitHub integration: PyGithub wrapper, diff parsing, webhook handling.

| File | What it is |
|---|---|
| `client.py` | `GitHubClient`: PR info/files, PR listing, comment posting. Supports both a server-wide token/App-installation auth (`_get_github`, for the automated review pipeline) and per-user OAuth token auth (for anything acting on behalf of the logged-in user). |
| `diff_parser.py` | Diff parsing helpers shared by the pipeline. |
| `webhook.py` | GitHub webhook handler; enqueues the same job pipeline the manual `/api/analyze` trigger uses. |

## Conventions
- **Authorization boundary:** any method that lists or reads data scoped to a specific user (their
  repos, their PRs, PRs in a repo they're browsing) must take a `user_token` and authenticate with
  `Github(auth=Auth.Token(user_token))`, so GitHub itself enforces access — never resolve access
  via a caller-supplied `installation_id` or similar identifier. Reserve `_get_github`
  (server token / App installation) for the automated pipeline path (fetching PR diffs to review,
  posting the review comment), which acts as the app, not as a specific user.
- Prefer the Search API (`search_pull_requests`) over iterating every repo when scoping to "the
  current user's PRs" — one call instead of N.
