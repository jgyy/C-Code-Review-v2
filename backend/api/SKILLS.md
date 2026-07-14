<!-- C-Code-Review backend/api/, SKILLS.md. -->

# Skills: backend/api/

| Task | Where |
|---|---|
| Add a new endpoint | `routes.py` — validate input, delegate to `core/`/`llm/`/`workers/`/`cache/`, shape response |
| Add/change a request or response model | `schemas.py` |
| Add an endpoint that acts as the logged-in user | call `require_github_token(authorization)` and pass the token down; never accept a client-supplied `installation_id` |
| Log request/response data for debugging | use `debug` level with sizes/counts only, never full bodies at `info` |
