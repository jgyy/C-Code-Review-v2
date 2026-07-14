<!-- C-Code-Review backend/llm/, AGENTS.md. -->

# backend/llm/

LLM client for turning triage output into a structured, function-level review.

| File | What it is |
|---|---|
| `client.py` | Gemini/Claude client: one bounded LLM call per PR, retry with exponential backoff, risk-based model selection, per-function result caching, Mermaid diagram generation. |
| `prompts.py` | Prompt templates for the fast-path review and the Mermaid diagram. |
| `schemas.py` | Pydantic schemas the LLM's structured output is parsed into. |

## Conventions
- Exactly one LLM call per PR for the main review; unselected functions get a static-analysis-only
  result synthesized from triage signals (see `_fallback_analysis` / the static path in
  `client.py`) — don't add a per-function LLM call.
- Never log full prompts or full LLM responses at `info` level — they can contain the PR's source
  code and are unbounded in size. Use `debug` with lengths/counts only.
- Cache per-function results by a hash of before+after source text (see `RESULT_TTL`), not by PR
  or job ID, so identical functions across PRs are never re-analyzed.
- When adding a new AI-generated structured field (beyond the review JSON and Mermaid diagram),
  validate it the same way the Mermaid diagram is validated/retried — never pass AI output straight
  through to the client or to a shell/action.
