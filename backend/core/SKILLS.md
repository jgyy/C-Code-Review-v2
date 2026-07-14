<!-- C-Code-Review backend/core/, SKILLS.md. -->

# Skills: backend/core/

| Task | Where |
|---|---|
| Change C-to-AST extraction | `parser.py` |
| Add a new risk heuristic | its own scoring function in `heuristics.py`, wired into `triage.py`'s weighting — don't inline scoring in `triage.py` |
| Change how per-PR risk is scored or which functions go to the LLM | `triage.py` |
| Add a dependency on the network or an LLM call | don't — this package must stay pure/testable without external services |
