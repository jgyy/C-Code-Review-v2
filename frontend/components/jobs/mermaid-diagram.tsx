"use client";

import { useEffect, useId, useState } from "react";
import { AlertTriangle, Code2 } from "lucide-react";
import { cn } from "@/lib/utils";

// Elements/attributes to strip as a defense-in-depth pass over mermaid's
// output before it's injected via dangerouslySetInnerHTML. This is a manual
// DOM walk rather than DOMPurify: DOMPurify's sanitize() reparses the whole
// string and — because mermaid renders node labels as HTML wrapped in an SVG
// <foreignObject> — it either strips foreignObject outright (every profile
// blocks it by default as a known XSS vector) or, even when explicitly
// allowed via ADD_TAGS, mishandles the SVG/HTML namespace boundary and empties
// out the HTML children anyway. Since mermaid (with securityLevel: "strict")
// already HTML-escapes any label text derived from the LLM, the only
// remaining risk is the template markup itself — so a targeted walk that
// removes genuinely dangerous elements/attributes is both safer (doesn't
// silently corrupt legitimate content) and correct here.
const DANGEROUS_TAGS = new Set(["script", "iframe", "object", "embed", "link", "meta"]);
const DANGEROUS_URI_ATTRS = new Set(["href", "xlink:href", "src", "action", "formaction"]);

function sanitizeMermaidSvg(svgString: string): string {
  const doc = new DOMParser().parseFromString(svgString, "image/svg+xml");
  if (doc.querySelector("parsererror")) {
    throw new Error("Diagram SVG failed to parse");
  }

  const walk = (node: Element) => {
    // Remove dangerous elements outright.
    if (DANGEROUS_TAGS.has(node.tagName.toLowerCase())) {
      node.remove();
      return;
    }

    // Strip event-handler attributes (onclick, onerror, ...) and
    // javascript:-scheme URIs on any element.
    for (const attr of Array.from(node.attributes)) {
      const name = attr.name.toLowerCase();
      if (name.startsWith("on")) {
        node.removeAttribute(attr.name);
      } else if (DANGEROUS_URI_ATTRS.has(name) && /^\s*javascript:/i.test(attr.value)) {
        node.removeAttribute(attr.name);
      }
    }

    // Recurse into children (copy to array first — DANGEROUS_TAGS removal
    // above mutates the live children collection while iterating).
    for (const child of Array.from(node.children)) {
      walk(child);
    }
  };

  walk(doc.documentElement);
  return new XMLSerializer().serializeToString(doc.documentElement);
}

/**
 * Renders a Mermaid flowchart string produced by the LLM analysis.
 *
 * The backend already validates/repairs the diagram syntax before it ever
 * reaches the frontend (see llm/client.py _ensure_valid_mermaid), but
 * mermaid.render() can still throw on edge cases our validator doesn't
 * catch — so this always has a "show raw source" fallback rather than
 * breaking the rest of the job page.
 */
export function MermaidDiagram({ source }: { source: string }) {
  const id = useId().replace(/:/g, "-");
  const [svg, setSvg] = useState<string | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function render() {
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({
          startOnLoad: false,
          theme: "dark",
          securityLevel: "strict",
        });
        const { svg } = await mermaid.render(`mermaid-${id}`, source);
        const clean = sanitizeMermaidSvg(svg);
        if (!cancelled) setSvg(clean);
      } catch (err) {
        if (!cancelled) {
          setRenderError(err instanceof Error ? err.message : "Failed to render diagram");
        }
      }
    }

    render();
    return () => {
      cancelled = true;
    };
  }, [id, source]);

  if (renderError) {
    return (
      <div className="rounded-lg border border-yellow-400/30 bg-yellow-400/5 p-4">
        <div className="flex items-center gap-2 text-xs text-yellow-400">
          <AlertTriangle className="h-3.5 w-3.5" />
          Diagram couldn't be rendered ({renderError}) — showing raw source instead
        </div>
        <pre className="mt-3 overflow-x-auto rounded-md bg-secondary p-3 text-xs text-muted-foreground">
          <code>{source}</code>
        </pre>
      </div>
    );
  }

  return (
    <div className={cn("overflow-x-auto rounded-lg border border-border bg-card p-4", !svg && "py-8")}>
      {svg ? (
        <div dangerouslySetInnerHTML={{ __html: svg }} />
      ) : (
        <div className="flex items-center justify-center gap-2 text-xs text-muted-foreground">
          <Code2 className="h-3.5 w-3.5 animate-pulse" />
          Rendering diagram…
        </div>
      )}
    </div>
  );
}
