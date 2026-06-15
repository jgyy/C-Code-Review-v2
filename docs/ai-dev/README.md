## Development Approach with AI

### AI tools, services, and models — and their purposes

| Tool / Model | Purpose |
|---|---|
| **Claude Sonnet** (claude.ai) | Primary development agent — architecture design, all code generation, debugging, integration guidance, and documentation |
| **Gemini 2.0 Flash** (Google AI Studio) | Runtime LLM embedded in the product — generates PR review narratives from structured heuristic evidence at inference time |
| **Claude Artifacts** | Iterative frontend prototyping — generated and refined the vanilla HTML/CSS/JS prototype before the Next.js migration, allowing rapid visual iteration without a build step |

### AI agents — roles and skills

| Agent | Role | Skills applied |
|---|---|---|
| **Architect** | Designed the layered pipeline (parse → heuristics → triage → LLM → output) and identified identity tracking before any code was written | System design, trade-off analysis, static analysis domain knowledge |
| **Builder** | Wrote all backend Python modules with inline technical rationale comments explaining every non-obvious decision | Python, FastAPI, asyncio, tree-sitter API, Pydantic, Redis patterns |
| **Frontend builder** | Built the vanilla HTML prototype, then proposed and scaffolded the Next.js migration with full component structure and typed API client | TypeScript, React, Next.js App Router, Tailwind, SWR, NextAuth |
| **Reviewer** | Audited import chains, caught the `github`/PyGithub package collision, identified the `google.generativeai` deprecation before production, diagnosed and fixed Pydantic `Optional` field errors | Dependency auditing, static analysis, runtime error diagnosis |
| **Documentation writer** | Authored the integration guide, inline code comments, and this README with technical detail drawn from the actual source files rather than generic descriptions | Technical writing, accuracy verification against live code |

### Key prompts used

- *"Propose the top useful heuristics I can apply using information gotten from the tree-sitter parser"* — produced the six-heuristic framework (H1–H6) that became the core of the structural analysis layer.
- *"What tech stack and architecture would you propose?"* — produced the full layered architecture with identity tracking, triage routing, and map-reduce LLM as distinct design decisions, each with explicit written rationale.
- *"Build it and leave comprehensive explanations on all major technical choices"* — established the pattern of inline docstrings justifying every non-obvious decision rather than only describing what the code does.
- *"The frontend is currently deployed on Vercel. Explain the exact specific steps to connect the frontend and backend"* — generated the `INTEGRATION.md` covering the Vercel proxy rewrite pattern, environment variable setup, and the reasoning behind each choice.
- *"Propose how user management should be added"* — produced the NextAuth.js + GitHub OAuth proposal fitted specifically to the existing Next.js stack and component structure rather than a generic authentication tutorial.

### Key review points and decisions made

| Review point | Decision made |
|---|---|
| Pydantic `ValidationError` on `AnalysisResultResponse` for in-progress jobs | Changed `files_analyzed`, `cache_hits`, `cache_misses` from required `int` to `Optional[int] = None`. Fields that only exist on completed jobs must be optional for the schema to be valid at every lifecycle stage. |
| Naive set-diff on function names treated all renames as deletion + addition | Added `rapidfuzz` identity tracking before diffing. Functions are paired by name and signature similarity first, eliminating false-positive orphan signals and inflated risk scores. |
| Heuristic layer emitting verdict strings fed to the LLM | Changed to structured evidence bundles. The LLM receives facts (delta values, counts, lists), not pre-written conclusions. The model interprets evidence rather than repackaging verdicts. |

---

## Reflection

### What worked

**Parsing before diffing** was the right foundational decision. Operating on ASTs instead of text lines meant every downstream layer worked with semantic units — functions, call graphs, control flow — rather than line numbers and `+`/`-` characters. The quality of analysis is qualitatively better than any text-diff approach could produce.

**Structured evidence in LLM prompts rather than raw code** proved its value immediately. Feeding the model `complexity_delta: +8, malloc/free imbalance: +1, calls_added: ["memcpy"]` rather than 200 lines of C produced more accurate, more specific, and more consistent output. The model explains findings; the heuristics discover them.

**The triage layer as a cost gate** worked exactly as designed. Trivial PRs (renames, whitespace, comment-only changes) were skipped with no LLM call. Most real PRs hit the fast path at ~3 seconds. Only genuinely complex diffs triggered deep analysis. API costs stayed proportional to actual risk.

**Inline technical rationale in code comments** was unconventional but paid off. Every non-obvious decision — why threads not processes, why `compare_digest` not `==`, why the package was renamed — is explained at the point of decision. Debugging was faster because the reasoning was always co-located with the code.

### What failed

**The `github/` package naming collision** was a silent failure mode. The backend imported PyGithub as `from github import Github`, but our own `github/` directory shadowed it when running from the project root. It didn't fail at import time with a clear error — it imported our blank `__init__.py` successfully and only crashed later when calling `.get_pull()` on a non-existent attribute.

**`google.generativeai` deprecation** was not caught until runtime. The old SDK imported cleanly and appeared to work; the deprecation only surfaced as a warning during integration testing rather than a hard failure. Dependency lifecycle auditing at requirements-pin time would have caught this earlier.

**The `AnalysisResultResponse` schema** was designed around the completed state only. Fields like `files_analyzed`, `cache_hits`, and `cache_misses` were defined as required integers. The schema was correct for a finished job but crashed with a Pydantic `ValidationError` when the status endpoint tried to return an in-progress job that hadn't populated those fields yet.

### Changes made and rationaled

| Change | Rationale |
|---|---|
| Heuristics emit evidence bundles, not verdict strings | Verdict strings tell the LLM what to conclude. Evidence gives the LLM facts to reason from. The latter produces more grounded output with fewer hallucinated details. |
| Added `rapidfuzz` identity matching before diffing | Without it, any renamed function appears as a deletion + addition, cascading into false-positive orphan signals, inflated risk scores, and broken call graph diffs. |
| `Optional[int] = None` on lifecycle-conditional fields | Pydantic schemas must be valid at every stage of a job's lifecycle, not just the terminal state. Fields that don't exist yet must be optional or every intermediate status response crashes. |
| Vercel proxy rewrite instead of CORS headers | Eliminates the browser preflight round-trip, removes the need to maintain an `ALLOWED_ORIGINS` list on the backend, and decouples the frontend deploy URL from the backend URL — change the backend host without touching the frontend. |
