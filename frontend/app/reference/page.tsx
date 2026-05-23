export const metadata = {
  title: "Risk Signal Reference — C Code Review",
  description: "Explanation of every risk signal produced by the C code review static analyser.",
};

interface Section {
  id: string;
  title: string;
  severity: "critical" | "high" | "medium" | "low";
  body: React.ReactNode;
}

const SEVERITY_STYLES: Record<string, string> = {
  critical: "border-l-4 border-red-500 bg-red-500/5",
  high:     "border-l-4 border-orange-500 bg-orange-500/5",
  medium:   "border-l-4 border-yellow-500 bg-yellow-500/5",
  low:      "border-l-4 border-blue-500 bg-blue-500/5",
};

const SEVERITY_BADGE: Record<string, string> = {
  critical: "bg-red-500/20 text-red-400",
  high:     "bg-orange-500/20 text-orange-400",
  medium:   "bg-yellow-500/20 text-yellow-400",
  low:      "bg-blue-500/20 text-blue-400",
};

function Code({ children }: { children: string }) {
  return (
    <code className="rounded bg-secondary px-1 py-0.5 font-mono text-xs text-foreground">
      {children}
    </code>
  );
}

function Pre({ children }: { children: string }) {
  return (
    <pre className="mt-2 overflow-x-auto rounded-md bg-secondary p-3 text-xs font-mono text-foreground leading-relaxed whitespace-pre">
      {children.trim()}
    </pre>
  );
}

const SECTIONS: Section[] = [
  // -------------------------------------------------------------------------
  {
    id: "malloc-free-imbalance",
    title: "Malloc / Free Imbalance — Memory Leak or Double-Free",
    severity: "critical",
    body: (
      <>
        <p>
          The analyser counts <Code>malloc</Code>, <Code>calloc</Code>, <Code>realloc</Code> calls
          and <Code>free</Code> calls within a single function body and flags when the counts
          diverge. A positive imbalance (more allocations than frees) means memory allocated inside
          this function is not released on all code paths — a{" "}
          <strong>memory leak</strong>. A negative imbalance (more frees than allocations) suggests
          a potential <strong>double-free</strong>, which is undefined behaviour and commonly
          exploitable.
        </p>
        <p className="mt-2 text-sm text-muted-foreground">
          Note: intra-function counting is a heuristic. A function that allocates and returns the
          pointer for the caller to free is correct, but will still trigger this signal. The signal
          is high-value when both alloc and free are present in the same function and counts do not
          match.
        </p>
        <Pre>{`// BAD — malloc with no free on the error path
char *build_msg(const char *prefix, size_t len) {
    char *buf = malloc(len + 1);
    if (!buf) return NULL;
    if (len > MAX_LEN) return NULL;  // leak: buf never freed here
    snprintf(buf, len + 1, "%s...", prefix);
    return buf;
}`}</Pre>
        <p className="mt-2 text-sm">
          <strong>Fix:</strong> add <Code>free(buf); return NULL;</Code> on every early-return
          error path, or use <Code>goto err</Code> / cleanup label patterns.
        </p>
      </>
    ),
  },

  // -------------------------------------------------------------------------
  {
    id: "double-free",
    title: "Double-Free Risk",
    severity: "critical",
    body: (
      <>
        <p>
          A double-free occurs when <Code>free()</Code> is called on a pointer that has already
          been freed. The C standard declares this undefined behaviour. In practice it corrupts the
          heap allocator's internal free-list, leading to crashes or, with a crafted input sequence,
          arbitrary code execution via heap exploitation techniques (e.g. tcache poisoning in
          glibc).
        </p>
        <Pre>{`void cleanup(ctx_t *ctx) {
    free(ctx->buf);
    if (ctx->error) {
        free(ctx->buf);  // double-free if ctx->error is set
    }
    free(ctx);
}`}</Pre>
        <p className="mt-2 text-sm">
          <strong>Fix:</strong> set the pointer to <Code>NULL</Code> immediately after every{" "}
          <Code>free()</Code> call. A second <Code>free(NULL)</Code> is a safe no-op per the C
          standard.
        </p>
      </>
    ),
  },

  // -------------------------------------------------------------------------
  {
    id: "use-after-free",
    title: "Use-After-Free",
    severity: "critical",
    body: (
      <>
        <p>
          Reading or writing through a pointer after the memory it points to has been freed is
          undefined behaviour. The freed region may be reallocated by a subsequent{" "}
          <Code>malloc</Code> call, so a write becomes a corruption of a live object; a read
          returns attacker-influenced data. This is one of the most commonly exploited memory
          safety bugs in C.
        </p>
        <Pre>{`node_t *n = list->head;
free(n);
printf("%s\n", n->name);  // use-after-free: n->name is in freed memory`}</Pre>
        <p className="mt-2 text-sm">
          <strong>Fix:</strong> set pointers to <Code>NULL</Code> after freeing; do not cache raw
          pointers across calls that may free them.
        </p>
      </>
    ),
  },

  // -------------------------------------------------------------------------
  {
    id: "buffer-overflow",
    title: "Buffer Overflow / Out-of-Bounds Write",
    severity: "critical",
    body: (
      <>
        <p>
          Writing past the end of a stack or heap buffer overwrites adjacent memory. On the stack
          this typically corrupts a saved return address (enabling control-flow hijacking); on the
          heap it corrupts allocator metadata or a neighbouring object. This signal fires when the
          analyser detects size calculations involving user-controlled values or large{" "}
          <Code>complexity_delta</Code> in functions that use array subscript or pointer arithmetic.
        </p>
        <Pre>{`void copy_input(char *dst, const char *src) {
    // strcpy has no length limit — overflows dst if src is longer
    strcpy(dst, src);
}`}</Pre>
        <p className="mt-2 text-sm">
          <strong>Fix:</strong> always pass explicit lengths —{" "}
          <Code>strncpy</Code>, <Code>strlcpy</Code>, <Code>snprintf</Code>, or{" "}
          <Code>memcpy</Code> with a validated bound. Validate the bound before use.
        </p>
      </>
    ),
  },

  // -------------------------------------------------------------------------
  {
    id: "null-pointer",
    title: "Null Pointer Dereference",
    severity: "high",
    body: (
      <>
        <p>
          Dereferencing a <Code>NULL</Code> pointer is undefined behaviour. On most platforms it
          crashes the process (SIGSEGV), but in embedded or kernel contexts it may silently
          read/write address 0. This signal fires when a function receives a pointer parameter or
          calls a function that may return <Code>NULL</Code> (e.g. <Code>malloc</Code>,{" "}
          <Code>fopen</Code>) and uses the result without a null check.
        </p>
        <Pre>{`FILE *f = fopen(path, "r");
fread(buf, 1, n, f);  // crash if fopen returned NULL`}</Pre>
        <p className="mt-2 text-sm">
          <strong>Fix:</strong> check every pointer that can be <Code>NULL</Code> before
          dereferencing. Treat <Code>malloc</Code> returning <Code>NULL</Code> as a genuine
          error path, not a theoretical one.
        </p>
      </>
    ),
  },

  // -------------------------------------------------------------------------
  {
    id: "unchecked-return",
    title: "Unchecked Return Value",
    severity: "high",
    body: (
      <>
        <p>
          Many C standard library and POSIX functions signal failure via their return value (
          <Code>-1</Code>, <Code>NULL</Code>, <Code>EOF</Code>, etc.). Ignoring the return value
          means the program proceeds with invalid state — an unwritten buffer, a closed descriptor,
          a failed allocation — which typically causes a crash or silent data corruption downstream,
          far from the original failure site.
        </p>
        <Pre>{`write(fd, buf, len);     // partial write or EPIPE ignored
recv(sock, buf, len, 0); // -1 on error treated as 0 bytes`}</Pre>
        <p className="mt-2 text-sm">
          <strong>Fix:</strong> check return values and handle the failure case explicitly. For{" "}
          <Code>write</Code> / <Code>send</Code>, loop until all bytes are sent or an error is
          confirmed.
        </p>
      </>
    ),
  },

  // -------------------------------------------------------------------------
  {
    id: "format-string",
    title: "Format String Vulnerability",
    severity: "critical",
    body: (
      <>
        <p>
          Passing user-controlled input as the format argument to <Code>printf</Code>,{" "}
          <Code>sprintf</Code>, <Code>fprintf</Code>, or similar functions allows an attacker to
          read from or write to arbitrary memory addresses using format specifiers like{" "}
          <Code>%x</Code>, <Code>%s</Code>, and <Code>%n</Code>. This is a classic code-execution
          primitive.
        </p>
        <Pre>{`// BAD — user_input is the format string
printf(user_input);

// GOOD
printf("%s", user_input);`}</Pre>
      </>
    ),
  },

  // -------------------------------------------------------------------------
  {
    id: "integer-overflow",
    title: "Integer Overflow in Size Calculation",
    severity: "high",
    body: (
      <>
        <p>
          When an integer used to compute an allocation size overflows (wraps around), the resulting
          allocation is smaller than expected, and subsequent writes overflow the buffer. This is
          common in code like <Code>malloc(count * elem_size)</Code> where both values are
          attacker-controlled. Signed integer overflow is additionally undefined behaviour in C,
          giving the compiler licence to eliminate overflow checks.
        </p>
        <Pre>{`// If count is 0x80000001 and elem_size is 2:
// count * elem_size = 2 (32-bit overflow), malloc(2) is tiny
void *p = malloc(count * elem_size);`}</Pre>
        <p className="mt-2 text-sm">
          <strong>Fix:</strong> use <Code>size_t</Code> arithmetic, check for overflow before
          multiplying (e.g. <Code>if (count &gt; SIZE_MAX / elem_size) return ERR</Code>), or use{" "}
          <Code>reallocarray()</Code> which does the check internally.
        </p>
      </>
    ),
  },

  // -------------------------------------------------------------------------
  {
    id: "complexity-increase",
    title: "High Complexity Increase",
    severity: "medium",
    body: (
      <>
        <p>
          McCabe cyclomatic complexity counts the number of independent paths through a function:
          1 (base) + 1 per <Code>if</Code> / <Code>for</Code> / <Code>while</Code> /{" "}
          <Code>case</Code> / ternary. A delta above +10 means the function grew by at least 10
          new decision points in this PR. High complexity correlates strongly with defect density —
          more paths means more paths to test and more opportunities for an error path to be missed.
        </p>
        <p className="mt-2 text-sm text-muted-foreground">
          Industry thresholds: 1–5 low risk, 6–10 moderate, 11–15 high, 16+ very high. The signal
          fires at delta &gt;5 (medium) and delta &gt;10 (high).
        </p>
        <p className="mt-2 text-sm">
          <strong>Fix:</strong> extract cohesive sub-operations into named helper functions.
          Simplify compound boolean conditions. Prefer early returns over deeply nested{" "}
          <Code>if/else</Code> chains.
        </p>
      </>
    ),
  },

  // -------------------------------------------------------------------------
  {
    id: "signature-change",
    title: "Signature Change (Return Type or Parameters)",
    severity: "medium",
    body: (
      <>
        <p>
          A change to a function's return type or parameter list breaks the implicit contract
          between the function and all its callers. In C, if a header is not updated in sync, the
          compiler may silently generate incorrect calling convention code (wrong argument registers,
          wrong return-value handling). If the function is in a shared library, existing binaries
          calling the old ABI will misbehave without a link error.
        </p>
        <p className="mt-2 text-sm">
          <strong>Fix:</strong> grep all call sites for the changed function, update all of them,
          and verify the header declaration matches the new definition. Treat ABI changes as
          breaking changes requiring a major version bump in versioned libraries.
        </p>
      </>
    ),
  },

  // -------------------------------------------------------------------------
  {
    id: "new-memory-ops",
    title: "New Memory Operations Introduced",
    severity: "medium",
    body: (
      <>
        <p>
          This function did not previously perform any dynamic memory allocation or deallocation.
          This PR introduces <Code>malloc</Code>, <Code>calloc</Code>, <Code>realloc</Code>, or{" "}
          <Code>free</Code> calls. This is significant because it changes the function's ownership
          semantics — callers may now be responsible for freeing memory that was previously
          stack-allocated or statically allocated.
        </p>
        <p className="mt-2 text-sm">
          <strong>Fix:</strong> document ownership explicitly in comments. Ensure all error paths
          free newly allocated memory. Update callers to handle the new allocation semantics.
        </p>
      </>
    ),
  },

  // -------------------------------------------------------------------------
  {
    id: "pointer-density",
    title: "Pointer Operation Density Increase",
    severity: "medium",
    body: (
      <>
        <p>
          The analyser counts pointer-related AST nodes: dereferences (<Code>*p</Code>), address-of
          (<Code>&amp;x</Code>), arrow access (<Code>p-&gt;field</Code>), and subscript expressions
          (<Code>arr[i]</Code>). A significant increase in density indicates the function became
          substantially more pointer-heavy, which increases the surface area for null dereferences,
          out-of-bounds accesses, and aliasing bugs.
        </p>
        <p className="mt-2 text-sm">
          <strong>Fix:</strong> introduce local non-pointer variables for values that are read
          multiple times. Add null checks at the top of the function for all pointer parameters.
        </p>
      </>
    ),
  },

  // -------------------------------------------------------------------------
  {
    id: "recursion-added",
    title: "Recursion Introduced",
    severity: "medium",
    body: (
      <>
        <p>
          The function now calls itself (directly or as detected by the call graph). Recursion in C
          carries stack-overflow risk when the input depth is unbounded or attacker-controlled.
          Each recursive call consumes stack frame space; on systems with fixed stack sizes (common
          in embedded and kernel contexts) this can silently corrupt the stack.
        </p>
        <Pre>{`// Unbounded recursion on attacker-controlled linked list
void traverse(node_t *n) {
    if (!n) return;
    process(n);
    traverse(n->next);  // stack overflow if list is circular or very long
}`}</Pre>
        <p className="mt-2 text-sm">
          <strong>Fix:</strong> add a depth counter or maximum-depth guard. Prefer an explicit
          stack (heap-allocated) over recursion for tree/graph traversal. Verify the recursion
          always terminates on all inputs.
        </p>
      </>
    ),
  },

  // -------------------------------------------------------------------------
  {
    id: "recursion-removed",
    title: "Recursion Removed",
    severity: "low",
    body: (
      <>
        <p>
          A function that previously called itself no longer does. This is generally a positive
          change (eliminating stack-overflow risk) but warrants review to ensure the iterative
          replacement is semantically equivalent — particularly around edge cases like empty input,
          single-element input, and error paths that previously relied on the recursive unwinding
          for cleanup.
        </p>
      </>
    ),
  },

  // -------------------------------------------------------------------------
  {
    id: "orphan-function",
    title: "Orphaned Function (Lost All Callers)",
    severity: "medium",
    body: (
      <>
        <p>
          The call graph analysis shows that this function had callers before this PR but has none
          after. It is now dead code. Dead code is not directly a bug, but it adds maintenance
          burden, can cause confusion, and if it is a cleanup or resource-release function (e.g.{" "}
          <Code>free_ctx()</Code>) that callers were supposed to call, the orphaning indicates a
          resource leak in the callers rather than in this function itself.
        </p>
        <p className="mt-2 text-sm">
          <strong>Fix:</strong> if the function is genuinely unused, remove it. If it should be
          called, identify which caller dropped the call and restore it.
        </p>
      </>
    ),
  },

  // -------------------------------------------------------------------------
  {
    id: "depth-increase",
    title: "Nesting Depth Increase",
    severity: "low",
    body: (
      <>
        <p>
          The maximum AST nesting depth increased by more than 3 levels. Deep nesting typically
          results from accumulated <Code>if/else</Code> or loop bodies and makes control flow hard
          to reason about. Each additional nesting level multiplies the number of paths through the
          function, increasing the probability of an error path being untested or incorrect.
        </p>
        <p className="mt-2 text-sm">
          <strong>Fix:</strong> use guard clauses (early returns) to invert conditionals and reduce
          nesting. Extract inner loops or conditional bodies into named helper functions.
        </p>
      </>
    ),
  },

  // -------------------------------------------------------------------------
  {
    id: "new-loops",
    title: "New Loops Added",
    severity: "low",
    body: (
      <>
        <p>
          One or more <Code>for</Code>, <Code>while</Code>, or <Code>do-while</Code> loops were
          added to this function. Each loop introduces a risk of: (a) infinite loop if the
          termination condition is never met, (b) off-by-one error in the bound, and (c) buffer
          overrun if the loop index is used to subscript an array whose bound is not enforced.
        </p>
        <p className="mt-2 text-sm">
          <strong>Fix:</strong> verify loop bounds against the sizes of all arrays indexed inside
          the loop. Ensure the loop invariant guarantees termination. Check for off-by-one: should
          the condition be <Code>&lt;</Code> or <Code>&lt;=</Code>?
        </p>
      </>
    ),
  },

  // -------------------------------------------------------------------------
  {
    id: "large-change",
    title: "Large Change (50+ Lines)",
    severity: "low",
    body: (
      <>
        <p>
          This function changed by more than 50 lines in this PR. Large diffs are harder to review
          thoroughly and more likely to contain mistakes that a reviewer misses. This signal is
          informational — it does not indicate a specific bug, but flags the function as needing
          extra scrutiny relative to small targeted changes.
        </p>
        <p className="mt-2 text-sm">
          <strong>Fix:</strong> where possible, split large refactors into smaller commits or PRs.
          Ensure test coverage exists for the changed function.
        </p>
      </>
    ),
  },

  // -------------------------------------------------------------------------
  {
    id: "parse-errors",
    title: "Parse Errors in Modified File",
    severity: "medium",
    body: (
      <>
        <p>
          The tree-sitter parser produced <Code>ERROR</Code> nodes when parsing this file after the
          change. This means the file contains syntax that the parser could not understand —
          typically incomplete code (missing header includes stripped by the diff), non-standard
          GCC extensions, or a genuine syntax error introduced by the PR. Analysis of functions in
          files with parse errors is less reliable because the AST may be incomplete.
        </p>
        <p className="mt-2 text-sm">
          <strong>Fix:</strong> compile the file locally (<Code>gcc -Wall -Wextra -c file.c</Code>)
          to confirm there are no genuine syntax errors. If the parse error is due to missing
          headers, this is a known limitation of diff-based analysis.
        </p>
      </>
    ),
  },
];

export default function ReferencePage() {
  return (
    <div className="mx-auto max-w-3xl space-y-8 py-2">
      <div>
        <h1 className="text-2xl font-semibold text-foreground">Risk Signal Reference</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Every signal the static analyser emits, explained with the underlying C semantics and a
          concrete fix. Signals in function cards link directly to the relevant section.
        </p>
      </div>

      {/* Quick-nav */}
      <nav className="rounded-lg border border-border bg-card p-4">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Jump to
        </p>
        <ul className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1">
          {SECTIONS.map((s) => (
            <li key={s.id}>
              <a
                href={`#${s.id}`}
                className="text-sm text-muted-foreground hover:text-foreground transition-colors hover:underline"
              >
                {s.title}
              </a>
            </li>
          ))}
        </ul>
      </nav>

      {/* Sections */}
      {SECTIONS.map((s) => (
        <section
          key={s.id}
          id={s.id}
          className={`scroll-mt-6 rounded-lg p-5 ${SEVERITY_STYLES[s.severity]}`}
        >
          <div className="flex items-start justify-between gap-4 mb-3">
            <h2 className="text-base font-semibold text-foreground">{s.title}</h2>
            <span
              className={`flex-shrink-0 rounded-full px-2 py-0.5 text-xs font-medium capitalize ${SEVERITY_BADGE[s.severity]}`}
            >
              {s.severity}
            </span>
          </div>
          <div className="space-y-2 text-sm text-foreground leading-relaxed">{s.body}</div>
        </section>
      ))}
    </div>
  );
}