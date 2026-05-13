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

SYSTEM_PROMPT_FAST_PATH = """You are an expert C code reviewer with deep knowledge of:
- Memory safety (malloc/free, buffer overflows, use-after-free)
- Undefined behavior (signed overflow, null pointer dereference, strict aliasing)
- Security vulnerabilities (injection, format strings, integer overflow)
- Performance patterns and anti-patterns

You are reviewing a pull request that has been pre-analyzed by static analysis tools.
You will receive structured evidence about the changes, including:
- Function-level complexity metrics
- Memory operation changes (malloc/free counts)
- Call graph modifications
- Signature changes

Your task is to:
1. Assess the overall risk of the changes
2. Identify specific concerns for each modified function
3. Provide actionable recommendations

Focus on HIGH-SIGNAL issues:
- Memory leaks (malloc without corresponding free)
- Double-free risks
- Buffer overflow potential
- API contract violations (changed signatures)
- Recursive call risks

DO NOT:
- Comment on style/formatting
- Suggest documentation changes
- Make assumptions about code you haven't seen

Respond in JSON format matching the provided schema."""


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

### Code Snippets (High-Risk Functions)

{code_snippets_text}

---

Based on the evidence above, provide your analysis in the following JSON format:
```json
{{
  "headline": "One-line summary",
  "risk_level": "low|medium|high|critical",
  "risk_score": 0-100,
  "summary": "2-3 sentence summary",
  "insights": ["key observation 1", "key observation 2"],
  "recommendations": ["action item 1", "action item 2"],
  "function_analyses": [
    {{
      "name": "function_name",
      "risk_level": "low|medium|high|critical",
      "risk_signals": ["signal 1", "signal 2"],
      "suggestion": "what to do",
      "potential_bugs": ["possible bug"],
      "security_concerns": ["security issue"]
    }}
  ],
  "memory_safety_issues": ["issue 1"],
  "security_concerns": ["concern 1"],
  "potential_bugs": ["bug 1"]
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

def build_fast_path_prompt(context: dict) -> str:
    """Build the user prompt for fast-path analysis."""
    
    # Format function evidence
    func_lines = []
    for fe in context.get("function_evidences", []):
        func_lines.append(f"#### `{fe.get('name', 'unknown')}`")
        func_lines.append(f"- Change type: {fe.get('change_type', 'unknown')}")
        func_lines.append(f"- Complexity: {fe.get('complexity_before', 0)} → {fe.get('complexity_after', 0)}")
        
        if fe.get("malloc_free_imbalance", 0) != 0:
            func_lines.append(f"- **Memory imbalance:** {fe.get('malloc_free_imbalance')} (potential leak/double-free)")
        
        if fe.get("return_type_changed"):
            func_lines.append("- **Return type changed**")
        
        if fe.get("calls_added"):
            func_lines.append(f"- New calls: {', '.join(fe.get('calls_added', []))}")
        
        if fe.get("calls_removed"):
            func_lines.append(f"- Removed calls: {', '.join(fe.get('calls_removed', []))}")
        
        func_lines.append("")
    
    function_evidence_text = "\n".join(func_lines) if func_lines else "No function changes detected."
    
    # Format code snippets
    snippets = context.get("code_snippets", {})
    snippet_lines = []
    for name, code in snippets.items():
        snippet_lines.append(f"#### `{name}`")
        snippet_lines.append("```c")
        # Truncate very long functions
        if len(code) > 2000:
            code = code[:2000] + "\n// ... (truncated)"
        snippet_lines.append(code)
        snippet_lines.append("```")
        snippet_lines.append("")
    
    code_snippets_text = "\n".join(snippet_lines) if snippet_lines else "No high-risk code snippets."
    
    return USER_PROMPT_FAST_PATH.format(
        repo_name=context.get("repo_name", "unknown"),
        pr_number=context.get("pr_number", 0),
        overall_risk_score=context.get("overall_risk_score", 0),
        overall_risk_level=context.get("overall_risk_level", "unknown"),
        triage_reasoning=context.get("triage_reasoning", "No reasoning provided"),
        function_evidence_text=function_evidence_text,
        code_snippets_text=code_snippets_text,
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
