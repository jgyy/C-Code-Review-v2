<!-- C-Code-Review backend/core/, AGENTS.md. -->

# backend/core/

The structural-analysis engine. No network calls, no LLM calls — pure parsing and scoring.

| File | What it is |
|---|---|
| `parser.py` | C source to AST (tree-sitter-based); per-function extraction from both sides of a diff. |
| `heuristics.py` | The weighted risk heuristics: memory imbalance, cyclomatic complexity delta, call-graph shift, orphaned functions, signature changes, and more. |
| `triage.py` | Combines heuristic outputs into a 0-100 risk score per function and per PR; selects the top-N functions to send to the LLM. |

## Conventions
- A new heuristic goes in `heuristics.py` as its own scoring function, wired into `triage.py`'s
  weighting — don't inline scoring logic in `triage.py` itself.
- Keep this package LLM- and network-free; it must be usable and testable without any external
  service.
