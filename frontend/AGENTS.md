<!-- C-Code-Review frontend/, AGENTS.md. Next.js dashboard. -->

# frontend/

Next.js dashboard. GitHub OAuth login (NextAuth), search/quick-analyze, job history, PR analysis
result view. Dev: `pnpm dev`.

| Path | What it is |
|---|---|
| `app/` | Next.js App Router routes: `(auth)` for sign-in, `(app)` for the authenticated dashboard/search/job pages (see `app/AGENTS.md`). |
| `components/` | UI components: dashboard widgets, job cards, layout shell (see `components/AGENTS.md`). |
| `lib/` | API client, auth config, shared utils (see `lib/AGENTS.md`). |
| `middleware.ts` | Route protection / auth redirect middleware. |

## Conventions
- All backend calls go through `lib/api.ts`'s shared `request()` helper so the `Authorization`
  bearer header stays consistent — never `fetch()` the backend directly from a component or page.
- Backend response shapes come from `lib/api.ts`'s types, which should track `backend/api/schemas.py`
  — update both sides in the same change when the API contract changes.
