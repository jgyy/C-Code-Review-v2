<!-- C-Code-Review frontend/lib/, AGENTS.md. -->

# frontend/lib/

| File | What it is |
|---|---|
| `api.ts` | Typed backend API client. Shared `request()` helper attaches the signed-in user's GitHub access token as `Authorization: Bearer` on every call — this is the only place fetch options/headers should be assembled. |
| `auth.ts` | NextAuth configuration (GitHub OAuth provider, session/token handling). |
| `utils.ts` | Small shared formatting/helper functions. |

## Conventions
- Add a new backend endpoint call as a new method on the `api` object in `api.ts`, not as an
  inline `fetch` elsewhere — that is what keeps auth headers and error handling consistent.
- Keep response types here in sync with `backend/api/schemas.py`.
