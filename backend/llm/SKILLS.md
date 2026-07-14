<!-- C-Code-Review backend/llm/, SKILLS.md. -->

# Skills: backend/llm/

| Task | Where |
|---|---|
| Change model selection or retry behavior | `client.py` — risk-based selection (CRITICAL PRs get the stronger model) lives here, don't special-case per endpoint |
| Change the fallback for unselected functions | `_fallback_analysis` / the static path in `client.py` — never add a per-function LLM call |
| Change or add a prompt | `prompts.py` |
| Add/change the LLM's structured output shape | `schemas.py`; validate and retry new AI-generated fields the same way the Mermaid diagram is |
| Change result caching | `client.py`'s `RESULT_TTL` — keyed by hash of before/after source text, not PR or job ID |
| Log prompts or responses | `debug` level only, lengths/counts, never full text at `info` |
