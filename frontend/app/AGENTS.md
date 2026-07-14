<!-- C-Code-Review frontend/app/, AGENTS.md. -->

# frontend/app/

Next.js App Router routes.

| Path | What it is |
|---|---|
| `(auth)/` | Sign-in / GitHub OAuth flow pages. |
| `(app)/` | Authenticated dashboard: repo/PR search, quick-analyze, job list, job detail/result view. |

## Conventions
- Route groups `(auth)` and `(app)` split unauthenticated vs authenticated layouts — a new
  authenticated page goes under `(app)`, not top-level.
- Pages fetch data via `lib/api.ts`, never by constructing backend URLs inline.
