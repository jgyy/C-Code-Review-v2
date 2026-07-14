<!-- C-Code-Review backend/github_utils/, SKILLS.md. -->

# Skills: backend/github_utils/

| Task | Where |
|---|---|
| Add a method that acts as a specific user (their repos/PRs) | `client.py`, authenticate with `Github(auth=Auth.Token(user_token))` — never resolve access via a caller-supplied `installation_id` |
| Add a method for the automated review pipeline (fetch diff, post comment) | `client.py`'s `_get_github` (server token / App installation) path |
| Search a user's PRs across repos | prefer `search_pull_requests` (Search API) over iterating every repo |
| Change diff parsing | `diff_parser.py` |
| Change webhook handling | `webhook.py` — must enqueue the same job pipeline as the manual `/api/analyze` trigger |
