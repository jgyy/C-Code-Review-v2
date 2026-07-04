"""
llm/prompts.py — System and user prompt templates

Prompt engineering for C code review. The prompts are designed to:
1. Ground the LLM in C-specific risks (memory safety, UB, security)
2. Provide structured evidence to reduce hallucination
3. Request structured output for reliable parsing

Prompt structure:
- System prompt: Role, expertise, output format
- User prompt: Evidence bundle + code snippets
"""

from __future__ import annotations


# ---------------------------------------------------------------------------
# System Prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_FAST_PATH = """You are an expert C code reviewer with deep knowledge of memory safety, undefined behavior, and security vulnerabilities in C.

You will receive pre-analyzed evidence from static analysis tools (complexity metrics, memory op counts, call graph changes, code snippets) for a pull request.

## Output rules — read carefully before writing a single word

### Specificity (most important rule)
Every finding MUST name the exact function, variable, or line it refers to.
NEVER write a generic finding that could apply to any codebase.

BAD:  "Check for null pointer dereferences"
GOOD: "parse_input() dereferences `buf` at the realloc() call site before checking the return value"

BAD:  "Memory leak detected"
GOOD: "alloc_node() calls malloc() but has no free() on the early-return error path at complexity branch 3"

BAD:  "Consider adding error handling"
GOOD: "read_packet() ignores the return value of recv(); a -1 return (EAGAIN/connection reset) is treated as 0 bytes"

### Deduplication (second most important rule)
The output has five distinct buckets: insights, recommendations, memory_safety_issues, security_concerns, potential_bugs.
Each finding belongs in EXACTLY ONE bucket. Never repeat the same finding across buckets.
- memory_safety_issues: malloc/free imbalance, use-after-free, double-free, buffer overrun — concrete instances only
- security_concerns: attacker-controlled input reaching dangerous sinks, format string bugs, integer overflow in size calculations
- potential_bugs: logic errors, unchecked return values, wrong conditions — not already listed above
- insights: non-obvious structural observations about the change (e.g. "this PR removes the only caller of cleanup_ctx()")
- recommendations: one concrete action per finding already listed; no new findings here, just what to do about them

### Memory findings — one mention maximum
If a function has a malloc/free count mismatch but NO other risk factors (no complexity spike, no new callers, no
signature change), put it in `memory_safety_issues` ONCE and nowhere else — not in `potential_bugs`, not in
`insights`, not in `recommendations`. A malloc/free imbalance in a trivial function is often a caller-owns-memory
pattern, not a true leak; say so if the function is simple.

### Deleted functions with live callers — highest priority signal
If `callers_lost` is non-empty for a deleted function, this is a dangling-reference risk: existing code calls a
function that no longer exists. Flag this as CRITICAL in the function's analysis and explain which callers are
now broken. This takes priority over all memory findings.

### Caller chain awareness
If `caller_chain` is non-empty, consider the blast radius: a bug in the analysed function propagates to every
function in the chain. A high-complexity change deep in a call chain is riskier than the same change in a leaf.

### Top feature entry points
If `top_feature_entry_points` is provided, the first entry is the most likely new feature root added by this PR.
Mention it by name in the `insights` field if it is itself changed or calls changed functions.

### Completeness
Only emit a bucket entry if you have a specific, concrete finding for it. Empty arrays are correct and preferred over vague filler.

### Function analyses
For each function in the evidence, `risk_signals` must be short phrases extracted directly from the evidence (e.g. "malloc/free imbalance: +2 malloc, 0 free"). `suggestion` must be one sentence naming the exact fix.

Focus on (in priority order):
1. Deleted functions with live callers (dangling references)
2. Unchecked return values, buffer overflows, API contract violations
3. Recursion risks, logic errors introduced by the change
4. Memory leaks / double-free (mention once, concisely)
Ignore: style, documentation, naming, malloc/free counts in trivial functions.

Respond in JSON format matching the provided schema."""


# A dedicated, JSON-free prompt for the Mermaid diagram. Kept as a SEPARATE
# call from the main analysis (see llm/client.py _generate_mermaid_diagram)
# rather than a field embedded in the structured-JSON response: a multi-line
# diagram string with quotes/newlines is exactly the kind of value that
# breaks strict JSON parsing when a model doesn't escape it perfectly, and a
# single parse failure there was taking down the ENTIRE PR analysis, not
# just the diagram. Isolating it means a bad diagram degrades gracefully to
# "no diagram" without touching the rest of the review.
SYSTEM_PROMPT_MERMAID = """You output ONLY raw Mermaid flowchart source. No markdown code fences, no JSON, no explanation — just the diagram, or the exact text NONE if there is nothing meaningful to draw.

Syntax rules — follow EXACTLY, this will be rejected and regenerated if it doesn't parse:
- First line is exactly: flowchart TD
- Every node reference is a short bare identifier: letters, digits, underscores only (e.g. parse_input, n1).
  NEVER put spaces, parens, or dots in a node id.
- Give a node a label only on its first appearance, using square brackets: parse_input["parse_input()"].
  Every later reference to that same node uses ONLY the bare id, no brackets: parse_input --> alloc_node
- One edge per line, arrows are exactly -->. Optional edge label: parse_input -->|frees| free_node
- To mark a changed/risky node: after all edges, add a line like: class parse_input,alloc_node risky
  then define classDef risky fill:#f66,stroke:#900 as the LAST line.
- No markdown code fences, no comments, no HTML tags, no semicolons, no subgraphs.
- Keep it to 5-12 nodes — only functions actually named in the evidence you're given.
- If there is nothing meaningful to diagram (e.g. a single isolated function with no callers/callees), respond
  with exactly: NONE"""

USER_PROMPT_MERMAID = """## Call-graph evidence for this PR

{function_evidence_text}

---

Draw a Mermaid flowchart of this PR's call-graph impact: the changed functions and their direct callers/callees.
Respond with ONLY the diagram source (or NONE), per the rules in your system prompt."""


SYSTEM_PROMPT_DEEP_MAP = """You are an expert C code reviewer analyzing a single function.

You will receive:
- The function's before/after code (if available)
- Structural evidence (complexity, memory ops, call graph changes)

Analyze this function for:
1. Memory safety issues (leaks, double-free, use-after-free)
2. Undefined behavior risks
3. Security vulnerabilities
4. Logic bugs introduced by the changes

Be specific and cite line numbers when possible.
Respond in JSON format."""


SYSTEM_PROMPT_DEEP_REDUCE = """You are synthesizing individual function analyses into a PR-level review.

You have already analyzed each function individually. Now:
1. Identify cross-function issues (e.g., function A allocates, function B should free)
2. Assess the overall coherence of the changes
3. Prioritize the most critical findings
4. Provide a high-level summary suitable for a PR comment

Focus on the STORY of the PR:
- What is being changed and why (infer from the changes)
- What could go wrong
- What the author should verify

Respond in JSON format."""


# ---------------------------------------------------------------------------
# User Prompt Templates
# ---------------------------------------------------------------------------

USER_PROMPT_FAST_PATH = """## Pull Request Analysis

**Repository:** {repo_name}
**PR Number:** #{pr_number}

### Triage Summary
- **Risk Score:** {overall_risk_score}/100
- **Risk Level:** {overall_risk_level}
- **Reasoning:** {triage_reasoning}

### Function Changes

{function_evidence_text}

{top_feature_text}### Code Snippets (High-Risk Functions and Their New Callees)

{code_snippets_text}

---

Analyze the evidence and respond with this exact JSON structure.
CRITICAL: every string must name a specific function/variable. No generic advice. No duplicate findings across fields.
```json
{{
  "headline": "One concrete sentence naming the highest-risk change and why",
  "risk_level": "low|medium|high|critical",
  "risk_score": 0-100,
  "summary": "2-3 sentences describing what changed and the specific risk it introduces. Name functions.",
  "insights": ["Non-obvious structural observation naming specific functions — omit if nothing genuine to say"],
  "recommendations": ["One action per finding already listed above, naming the function and exact fix needed"],
  "function_analyses": [
    {{
      "name": "exact_function_name",
      "risk_level": "low|medium|high|critical",
      "risk_signals": ["Short phrase from evidence, e.g. 'malloc/free imbalance: +2 malloc 0 free'"],
      "suggestion": "One sentence: exact fix for this function",
      "potential_bugs": ["Specific bug in this function not already in risk_signals"],
      "security_concerns": ["Specific security issue in this function"]
    }}
  ],
  "memory_safety_issues": ["Concrete instance: function name + specific allocation/free mismatch or overflow — omit if only signal is a trivial count mismatch"],
  "security_concerns": ["Concrete instance: function name + attacker-controlled path or dangerous sink"],
  "potential_bugs": ["Concrete instance: function name + specific logic error or unchecked return value"]
}}
```"""


USER_PROMPT_DEEP_MAP = """## Function Analysis: `{function_name}`

**File:** {filepath}
**Change Type:** {change_type}

### Evidence
- **Complexity:** {complexity_before} → {complexity_after} (delta: {complexity_delta})
- **AST Depth:** {depth_before} → {depth_after} (delta: {depth_delta})
- **Memory Ops Before:** {memory_ops_before}
- **Memory Ops After:** {memory_ops_after}
- **Malloc/Free Imbalance:** {malloc_free_imbalance}
- **Pointer Density Change:** {pointer_density_delta:.2%}
- **Calls Added:** {calls_added}
- **Calls Removed:** {calls_removed}
- **Recursion:** {recursion_info}
- **Signature Changed:** {signature_info}

### Code Before
```c
{code_before}
```

### Code After
```c
{code_after}
```

---

Analyze this function and respond in JSON:
```json
{{
  "name": "{function_name}",
  "risk_level": "low|medium|high|critical",
  "risk_signals": ["signal 1", "signal 2"],
  "suggestion": "recommendation",
  "potential_bugs": ["bug description"],
  "security_concerns": ["security issue"]
}}
```"""


USER_PROMPT_DEEP_REDUCE = """## PR Synthesis

You have analyzed {total_functions} functions across {total_files} files.
High-risk functions: {high_risk_count}

### Individual Function Analyses

{function_analyses_text}

### Files Changed
{file_list}

### Detected Patterns
{patterns_text}

---

Synthesize the above into a coherent PR review. Focus on:
1. The overall narrative of what's changing
2. Cross-function dependencies (does function A's change affect function B?)
3. The most critical issues that need attention
4. Clear, actionable recommendations

Respond in JSON:
```json
{{
  "headline": "One-line summary of the PR",
  "risk_level": "low|medium|high|critical",
  "risk_score": 0-100,
  "summary": "2-3 sentence narrative",
  "insights": ["key insight 1", "key insight 2"],
  "recommendations": ["action 1", "action 2"],
  "cross_function_concerns": ["concern spanning multiple functions"],
  "memory_safety_issues": ["memory issue"],
  "security_concerns": ["security issue"],
  "potential_bugs": ["potential bug"]
}}
```"""


# ---------------------------------------------------------------------------
# Prompt Builders
# ---------------------------------------------------------------------------

def _format_function_evidence(context: dict) -> str:
    """Shared function-evidence formatting, used by both the main analysis
    prompt and the standalone Mermaid diagram prompt."""
    func_lines = []
    for fe in context.get("function_evidences", []):
        func_lines.append(f"#### `{fe.get('name', 'unknown')}`")
        func_lines.append(f"- Change type: {fe.get('change_type', 'unknown')}")
        func_lines.append(f"- Complexity: {fe.get('complexity_before', 0)} → {fe.get('complexity_after', 0)}")

        # Fix 5c: only emit memory imbalance line for non-trivial cases.
        # Suppress if imbalance is exactly ±1 and complexity is low — this is
        # almost always a caller-owns-memory pattern, not a real leak.
        imbalance = fe.get("malloc_free_imbalance", 0)
        complexity_after = fe.get("complexity_after", fe.get("complexity_before", 0))
        if imbalance != 0 and not (abs(imbalance) == 1 and complexity_after < 5):
            # No bold — memory is one signal among many, not the headline
            func_lines.append(
                f"- Memory imbalance: {imbalance:+d} (malloc minus free delta)"
            )

        if fe.get("return_type_changed"):
            func_lines.append("- **Return type changed**")

        if fe.get("calls_added"):
            func_lines.append(f"- New calls: {', '.join(fe.get('calls_added', []))}")

        if fe.get("calls_removed"):
            func_lines.append(f"- Removed calls: {', '.join(fe.get('calls_removed', []))}")

        # Fix 3b: callers_lost is the most dangerous deletion signal
        callers_lost = fe.get("callers_lost", [])
        if callers_lost:
            func_lines.append(
                f"- **CALLERS LOST (dangling reference risk):** {', '.join(callers_lost[:5])}"
                + (" ..." if len(callers_lost) > 5 else "")
            )

        # Fix 2: caller chain (blast radius)
        caller_chain = fe.get("caller_chain", [])
        if caller_chain:
            func_lines.append(f"- Called by: {', '.join(caller_chain[:5])}"
                              + (" ..." if len(caller_chain) > 5 else ""))

        func_lines.append("")

    return "\n".join(func_lines) if func_lines else "No function changes detected."


def build_mermaid_prompt(context: dict) -> str:
    """Build the standalone user prompt for the Mermaid diagram call."""
    return USER_PROMPT_MERMAID.format(
        function_evidence_text=_format_function_evidence(context),
    )


def build_fast_path_prompt(context: dict) -> str:
    """Build the user prompt for fast-path analysis."""

    function_evidence_text = _format_function_evidence(context)

    # Format primary code snippets (the changed functions themselves)
    snippets = context.get("code_snippets", {})
    snippet_lines = []
    for name, code in snippets.items():
        snippet_lines.append(f"#### `{name}` (changed function)")
        snippet_lines.append("```c")
        if len(code) > 2000:
            code = code[:2000] + "\n// ... (truncated)"
        snippet_lines.append(code)
        snippet_lines.append("```")
        snippet_lines.append("")

    # Fix 1: callee snippets — functions newly called by high-risk functions
    for name, code in context.get("callee_snippets", {}).items():
        snippet_lines.append(f"#### `{name}` (callee — newly called)")
        snippet_lines.append("```c")
        if len(code) > 2000:
            code = code[:2000] + "\n// ... (truncated)"
        snippet_lines.append(code)
        snippet_lines.append("```")
        snippet_lines.append("")
    
    code_snippets_text = "\n".join(snippet_lines) if snippet_lines else "No high-risk code snippets."

    # Fix 4: top feature entry points
    top_features = context.get("top_feature_entry_points", [])
    if top_features:
        top_feat_lines = ["### Top Feature Entry Points (deepest new call chains)\n"]
        for feat in top_features:
            top_feat_lines.append(
                f"- `{feat['name']}`: call depth {feat['call_depth']}, "
                f"{feat['fraction_changed']:.0%} of reachable functions changed"
            )
        top_feature_text = "\n".join(top_feat_lines) + "\n"
    else:
        top_feature_text = ""
    
    return USER_PROMPT_FAST_PATH.format(
        repo_name=context.get("repo_name", "unknown"),
        pr_number=context.get("pr_number", 0),
        overall_risk_score=context.get("overall_risk_score", 0),
        overall_risk_level=context.get("overall_risk_level", "unknown"),
        triage_reasoning=context.get("triage_reasoning", "No reasoning provided"),
        function_evidence_text=function_evidence_text,
        code_snippets_text=code_snippets_text,
        top_feature_text=top_feature_text,
    )


def build_deep_map_prompt(func_input: dict) -> str:
    """Build the user prompt for deep analysis of a single function."""
    
    recursion_info = "Yes (recursive)" if func_input.get("is_recursive") else "No"
    if func_input.get("recursion_changed"):
        recursion_info += " (CHANGED)"
    
    signature_info = "No"
    if func_input.get("return_type_changed"):
        signature_info = "Yes (return type changed)"
    if func_input.get("params_before") != func_input.get("params_after"):
        signature_info = "Yes (parameters changed)"
    
    return USER_PROMPT_DEEP_MAP.format(
        function_name=func_input.get("name", "unknown"),
        filepath=func_input.get("filepath", "unknown"),
        change_type=func_input.get("change_type", "unknown"),
        complexity_before=func_input.get("complexity_before", 0),
        complexity_after=func_input.get("complexity_after", 0),
        complexity_delta=func_input.get("complexity_delta", 0),
        depth_before=func_input.get("depth_before", 0),
        depth_after=func_input.get("depth_after", 0),
        depth_delta=func_input.get("depth_delta", 0),
        memory_ops_before=func_input.get("memory_ops_before", {}),
        memory_ops_after=func_input.get("memory_ops_after", {}),
        malloc_free_imbalance=func_input.get("malloc_free_imbalance", 0),
        pointer_density_delta=func_input.get("pointer_density_delta", 0),
        calls_added=", ".join(func_input.get("calls_added", [])) or "None",
        calls_removed=", ".join(func_input.get("calls_removed", [])) or "None",
        recursion_info=recursion_info,
        signature_info=signature_info,
        code_before=func_input.get("code_before", "// Not available"),
        code_after=func_input.get("code_after", "// Not available"),
    )


def build_deep_reduce_prompt(context: dict) -> str:
    """Build the user prompt for synthesizing function analyses."""
    
    # Format function analyses
    analysis_lines = []
    for fa in context.get("function_analyses", []):
        analysis_lines.append(f"#### `{fa.get('name', 'unknown')}` - {fa.get('risk_level', 'unknown').upper()}")
        for signal in fa.get("risk_signals", []):
            analysis_lines.append(f"- {signal}")
        if fa.get("suggestion"):
            analysis_lines.append(f"- **Suggestion:** {fa.get('suggestion')}")
        analysis_lines.append("")
    
    function_analyses_text = "\n".join(analysis_lines) if analysis_lines else "No function analyses."
    
    file_list = "\n".join(f"- {f}" for f in context.get("file_paths", [])) or "No files."
    
    patterns = context.get("patterns", [])
    patterns_text = "\n".join(f"- {p}" for p in patterns) if patterns else "No patterns detected."
    
    return USER_PROMPT_DEEP_REDUCE.format(
        total_functions=context.get("total_functions", 0),
        total_files=len(context.get("file_paths", [])),
        high_risk_count=context.get("high_risk_count", 0),
        function_analyses_text=function_analyses_text,
        file_list=file_list,
        patterns_text=patterns_text,
    )