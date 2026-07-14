<!-- C-Code-Review frontend/components/, AGENTS.md. -->

# frontend/components/

Shared UI components.

| Path | What it is |
|---|---|
| `dashboard/` | Dashboard widgets: search, quick-analyze form, PR picker. |
| `jobs/` | Job list/card and job-detail/result rendering (including the Mermaid diagram view). |
| `layout/` | Nav shell, page layout chrome. |

## Conventions
- A new dashboard widget or job view is its own component under the matching subdirectory, composed
  into the page — not grown inline in a page file.
- Components read data via props/hooks backed by `lib/api.ts`; they don't call `fetch` directly.
