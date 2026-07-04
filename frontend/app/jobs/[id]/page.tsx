"use client";

import { use, useState, useCallback, useEffect } from "react";
import Link from "next/link";
import useSWR from "swr";
import { isValid } from "date-fns";
import { JobStatusBadge } from "@/components/jobs/job-status-badge";
import { RiskBadge } from "@/components/jobs/risk-badge";
import { MermaidDiagram } from "@/components/jobs/mermaid-diagram";
import { fetcher } from "@/lib/api";
import type { AnalysisResult, FunctionAnalysis, JobStage } from "@/lib/api";
import {
  Loader2, ArrowLeft, ExternalLink, Clock, Database,
  AlertTriangle, Lightbulb, Sparkles, Shield, Bug,
  ChevronDown, ChevronRight, ChevronLeft, Search, X,
  GitPullRequest, FileCode2, Microscope, Gauge, Sparkle, Check,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ─── helpers ────────────────────────────────────────────────────────────────

function safeDuration(createdAt?: string, completedAt?: string) {
  if (!createdAt || !completedAt) return "—";
  const s = new Date(createdAt), e = new Date(completedAt);
  if (!isValid(s) || !isValid(e) || s.getFullYear() < 2020) return "—";
  const sec = Math.round((e.getTime() - s.getTime()) / 1000);
  return sec < 0 ? "—" : `${sec}s`;
}

/** How long a job can sit in pending/processing before we flag it as possibly stuck. */
const STALE_JOB_THRESHOLD_SEC = 120;

/** Ticking "Ns elapsed" counter for a still-running job, based on its start time. */
function useElapsedSeconds(sinceIso?: string): number | null {
  const [now, setNow] = useState<number | null>(null);

  useEffect(() => {
    if (!sinceIso) return;
    setNow(Date.now());
    const interval = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(interval);
  }, [sinceIso]);

  if (!sinceIso || now === null) return null;
  const start = new Date(sinceIso);
  if (!isValid(start) || start.getFullYear() < 2020) return null;
  return Math.max(0, Math.round((now - start.getTime()) / 1000));
}

// ─── pipeline stepper ───────────────────────────────────────────────────────

const PIPELINE_STAGES: Array<{
  key: JobStage;
  label: string;
  detail: string;
  icon: React.ComponentType<{ className?: string }>;
}> = [
  { key: "fetching_pr",        label: "Fetching PR",        detail: "Reading changed files from GitHub",       icon: GitPullRequest },
  { key: "parsing_files",      label: "Parsing files",      detail: "Building ASTs with tree-sitter",           icon: FileCode2 },
  { key: "computing_evidence", label: "Computing evidence", detail: "Diffing functions before/after",           icon: Microscope },
  { key: "triage",             label: "Triage",             detail: "Scoring risk, routing to the right depth", icon: Gauge },
  { key: "llm_analysis",       label: "AI analysis",        detail: "Generating the review",                    icon: Sparkle },
];

function PipelineStepper({ status, stage }: { status: string; stage?: JobStage }) {
  // "pending" means the job hasn't been picked up yet — treat it as
  // "about to start stage 0" rather than showing nothing.
  const activeIndex = stage
    ? PIPELINE_STAGES.findIndex((s) => s.key === stage)
    : status === "pending" ? 0 : -1;

  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <div className="flex items-center gap-2 mb-5">
        <Loader2 className="h-4 w-4 animate-spin text-ring" />
        <h2 className="text-sm font-semibold text-foreground">Analysis in progress</h2>
      </div>
      <ol className="space-y-1">
        {PIPELINE_STAGES.map((s, i) => {
          const isDone    = activeIndex >= 0 && i < activeIndex;
          const isActive  = i === activeIndex;
          const isPending = activeIndex >= 0 ? i > activeIndex : true;
          const Icon = s.icon;
          return (
            <li key={s.key} className="flex items-center gap-3 rounded-md px-2 py-2.5">
              <div
                className={cn(
                  "flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full border transition-colors",
                  isDone    && "border-emerald-400/40 bg-emerald-400/10 text-emerald-400",
                  isActive  && "border-ring/40 bg-ring/10 text-ring",
                  isPending && "border-border bg-secondary text-muted-foreground/50",
                )}
              >
                {isDone ? <Check className="h-3.5 w-3.5" /> : <Icon className="h-3.5 w-3.5" />}
              </div>
              <div className="min-w-0">
                <p className={cn(
                  "text-sm font-medium",
                  isDone && "text-muted-foreground",
                  isActive && "text-foreground",
                  isPending && "text-muted-foreground/50",
                )}>
                  {s.label}
                </p>
                <p className={cn(
                  "text-xs",
                  isActive ? "text-muted-foreground" : "text-muted-foreground/40",
                )}>
                  {isActive ? s.detail : isDone ? "Done" : s.detail}
                </p>
              </div>
              {isActive && (
                <Loader2 className="ml-auto h-4 w-4 flex-shrink-0 animate-spin text-ring" />
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

const RISK_ORDER: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };

const RISK_BORDER: Record<string, string> = {
  critical: "border-l-red-500",
  high:     "border-l-orange-400",
  medium:   "border-l-yellow-400",
  low:      "border-l-blue-400",
};

const RISK_BG: Record<string, string> = {
  critical: "bg-red-500/5",
  high:     "bg-orange-400/5",
  medium:   "bg-yellow-400/5",
  low:      "bg-blue-400/5",
};

// ─── risk-signal links ───────────────────────────────────────────────────────

const SIGNAL_ANCHORS: Array<{ pattern: RegExp; anchor: string }> = [
  { pattern: /malloc.*free|free.*malloc|memory.*imbalance|unmatched malloc|memory leak/i, anchor: "malloc-free-imbalance" },
  { pattern: /double.?free/i,                              anchor: "double-free" },
  { pattern: /use.after.free/i,                            anchor: "use-after-free" },
  { pattern: /buffer overflow|out.of.bounds|bounds check/i, anchor: "buffer-overflow" },
  { pattern: /complexity increase|cyclomatic/i,            anchor: "complexity-increase" },
  { pattern: /signature change|return type changed|param.*changed|parameter count/i, anchor: "signature-change" },
  { pattern: /pointer.*density|pointer operation/i,        anchor: "pointer-density" },
  { pattern: /recursion introduced|recursion added/i,      anchor: "recursion-added" },
  { pattern: /recursion removed/i,                         anchor: "recursion-removed" },
  { pattern: /new memory op/i,                             anchor: "new-memory-ops" },
  { pattern: /orphan|lost all caller/i,                    anchor: "orphan-function" },
  { pattern: /nesting depth|depth increase/i,              anchor: "depth-increase" },
  { pattern: /new loop|loop.*added/i,                      anchor: "new-loops" },
  { pattern: /large change/i,                              anchor: "large-change" },
  { pattern: /parse error/i,                               anchor: "parse-errors" },
  { pattern: /format string/i,                             anchor: "format-string" },
  { pattern: /integer overflow|size.*overflow/i,           anchor: "integer-overflow" },
  { pattern: /unchecked return|return value.*check/i,      anchor: "unchecked-return" },
  { pattern: /null pointer|null check|dereference/i,       anchor: "null-pointer" },
];

function anchorFor(signal: string) {
  return SIGNAL_ANCHORS.find(({ pattern }) => pattern.test(signal))?.anchor ?? null;
}

function SignalLink({ signal }: { signal: string }) {
  const anchor = anchorFor(signal);
  if (!anchor) return <span>{signal}</span>;
  return (
    <Link
      href={`/reference#${anchor}`}
      className="underline decoration-dotted underline-offset-2 hover:text-ring transition-colors"
      title="View explanation"
    >
      {signal}
    </Link>
  );
}

// ─── function card ───────────────────────────────────────────────────────────

function FunctionCard({
  analysis,
  isExpanded,
  onToggle,
}: {
  analysis: FunctionAnalysis;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const riskSignals      = analysis.risk_signals      ?? [];
  const potentialBugs    = analysis.potential_bugs    ?? [];
  const securityConcerns = analysis.security_concerns ?? [];

  const hasDetails =
    riskSignals.length > 0 || !!analysis.suggestion ||
    potentialBugs.length > 0 || securityConcerns.length > 0;

  const rl = analysis.risk_level;

  return (
    <div
      className={cn(
        "flex flex-col rounded-lg border border-border border-l-4 overflow-hidden transition-shadow",
        "bg-card hover:shadow-md",
        RISK_BORDER[rl] ?? "border-l-border",
        RISK_BG[rl] ?? "",
      )}
    >
      {/* header */}
      <button
        onClick={hasDetails ? onToggle : undefined}
        className={cn(
          "flex w-full items-center justify-between gap-3 px-4 py-3 text-left",
          hasDetails ? "cursor-pointer" : "cursor-default",
        )}
      >
        <div className="flex items-center gap-2 min-w-0">
          {hasDetails ? (
            isExpanded
              ? <ChevronDown  className="h-3.5 w-3.5 flex-shrink-0 text-muted-foreground" />
              : <ChevronRight className="h-3.5 w-3.5 flex-shrink-0 text-muted-foreground" />
          ) : (
            <span className="h-3.5 w-3.5 flex-shrink-0" />
          )}
          <code className="font-mono text-xs font-semibold text-foreground truncate">
            {analysis.name}()
          </code>
        </div>
        <RiskBadge level={rl} size="sm" />
      </button>

      {/* collapsed summary — always visible when there's a suggestion */}
      {!isExpanded && analysis.suggestion && (
        <p className="px-4 pb-3 text-[11px] text-muted-foreground leading-relaxed line-clamp-2">
          {analysis.suggestion}
        </p>
      )}

      {/* expanded body */}
      {isExpanded && hasDetails && (
        <div className="border-t border-border/60 divide-y divide-border/40">
          {analysis.suggestion && (
            <p className="px-4 py-3 text-xs text-muted-foreground italic leading-relaxed">
              {analysis.suggestion}
            </p>
          )}

          {riskSignals.length > 0 && (
            <div className="px-4 py-3">
              <p className="mb-2 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
                Risk Signals
              </p>
              <ul className="space-y-1.5">
                {riskSignals.map((s, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs text-foreground">
                    <span className="mt-1.5 h-1 w-1 flex-shrink-0 rounded-full bg-yellow-400" />
                    <SignalLink signal={s} />
                  </li>
                ))}
              </ul>
            </div>
          )}

          {potentialBugs.length > 0 && (
            <div className="px-4 py-3">
              <p className="mb-2 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
                Potential Bugs
              </p>
              <ul className="space-y-1.5">
                {potentialBugs.map((b, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs text-foreground">
                    <span className="mt-1.5 h-1 w-1 flex-shrink-0 rounded-full bg-status-failed" />
                    {b}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {securityConcerns.length > 0 && (
            <div className="px-4 py-3">
              <p className="mb-2 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
                Security
              </p>
              <ul className="space-y-1.5">
                {securityConcerns.map((c, i) => (
                  <li key={i} className="flex items-start gap-2 text-xs text-foreground">
                    <span className="mt-1.5 h-1 w-1 flex-shrink-0 rounded-full bg-orange-400" />
                    {c}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── function grid with search + pagination ──────────────────────────────────

const PAGE_SIZE = 16;

function FunctionGrid({ analyses }: { analyses: FunctionAnalysis[] }) {
  const [query,        setQuery]        = useState("");
  const [page,         setPage]         = useState(0);
  // Set of expanded function names — only clicked cards open
  const [expandedSet,  setExpandedSet]  = useState<Set<string>>(new Set());

  const toggle = useCallback((name: string) => {
    setExpandedSet((prev) => {
      const next = new Set(prev);
      next.has(name) ? next.delete(name) : next.add(name);
      return next;
    });
  }, []);

  const sorted  = [...analyses].sort(
    (a, b) => (RISK_ORDER[a.risk_level] ?? 4) - (RISK_ORDER[b.risk_level] ?? 4)
  );

  const q = query.trim().toLowerCase();
  const filtered = q
    ? sorted.filter((a) => a.name.toLowerCase().includes(q))
    : sorted;

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage   = Math.min(page, totalPages - 1);
  const slice      = filtered.slice(safePage * PAGE_SIZE, (safePage + 1) * PAGE_SIZE);

  const handleQuery = (v: string) => {
    setQuery(v);
    setPage(0);
  };

  const riskCounts = {
    critical: filtered.filter((a) => a.risk_level === "critical").length,
    high:     filtered.filter((a) => a.risk_level === "high").length,
    medium:   filtered.filter((a) => a.risk_level === "medium").length,
    low:      filtered.filter((a) => a.risk_level === "low").length,
  };

  return (
    <div className="space-y-4">
      {/* toolbar: search + risk summary chips */}
      <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center">
        {/* search */}
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
          <input
            type="text"
            value={query}
            onChange={(e) => handleQuery(e.target.value)}
            placeholder="Search functions…"
            className={cn(
              "w-full rounded-md border border-border bg-card pl-8 pr-8 py-2",
              "text-xs text-foreground placeholder:text-muted-foreground/50",
              "focus:outline-none focus:ring-1 focus:ring-ring focus:border-ring transition-colors",
            )}
          />
          {query && (
            <button
              onClick={() => handleQuery("")}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>

        {/* risk breakdown chips */}
        <div className="flex items-center gap-2 flex-wrap">
          {(["critical","high","medium","low"] as const).map((r) =>
            riskCounts[r] > 0 ? (
              <span
                key={r}
                className={cn(
                  "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[11px] font-medium",
                  r === "critical" && "border-red-500/30    bg-red-500/10    text-red-400",
                  r === "high"     && "border-orange-400/30 bg-orange-400/10 text-orange-400",
                  r === "medium"   && "border-yellow-400/30 bg-yellow-400/10 text-yellow-400",
                  r === "low"      && "border-blue-400/30   bg-blue-400/10   text-blue-400",
                )}
              >
                <span className={cn(
                  "h-1.5 w-1.5 rounded-full",
                  r === "critical" && "bg-red-500",
                  r === "high"     && "bg-orange-400",
                  r === "medium"   && "bg-yellow-400",
                  r === "low"      && "bg-blue-400",
                )} />
                {riskCounts[r]} {r}
              </span>
            ) : null
          )}
          {q && (
            <span className="text-xs text-muted-foreground">
              {filtered.length} match{filtered.length !== 1 ? "es" : ""}
            </span>
          )}
        </div>
      </div>

      {/* grid */}
      {filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-border bg-card py-12 text-center">
          <Search className="h-8 w-8 text-muted-foreground/30 mb-3" />
          <p className="text-sm text-muted-foreground">No functions match <strong>{query}</strong></p>
          <button onClick={() => handleQuery("")} className="mt-2 text-xs text-ring hover:underline">
            Clear search
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {slice.map((analysis) => (
            <FunctionCard
              key={analysis.name}
              analysis={analysis}
              isExpanded={expandedSet.has(analysis.name)}
              onToggle={() => toggle(analysis.name)}
            />
          ))}
        </div>
      )}

      {/* pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between border-t border-border pt-3">
          <span className="text-xs text-muted-foreground">
            {safePage * PAGE_SIZE + 1}–{Math.min((safePage + 1) * PAGE_SIZE, filtered.length)} of {filtered.length}
          </span>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={safePage === 0}
              className="rounded p-1.5 text-muted-foreground hover:bg-secondary hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="px-3 text-xs text-muted-foreground tabular-nums">
              {safePage + 1} / {totalPages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={safePage >= totalPages - 1}
              className="rounded p-1.5 text-muted-foreground hover:bg-secondary hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── issue section ───────────────────────────────────────────────────────────

function IssueSection({
  title, icon: Icon, issues, iconClassName, dotClassName,
}: {
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  issues: string[];
  iconClassName: string;
  dotClassName: string;
}) {
  if (!issues?.length) return null;
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center gap-2 mb-3">
        <Icon className={cn("h-4 w-4", iconClassName)} />
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        <span className="ml-auto rounded-full bg-secondary px-2 py-0.5 text-[11px] text-muted-foreground">
          {issues.length}
        </span>
      </div>
      <ul className="space-y-2">
        {issues.map((issue, i) => (
          <li key={i} className="flex items-start gap-2 text-xs text-foreground leading-relaxed">
            <span className={cn("mt-1.5 h-1.5 w-1.5 flex-shrink-0 rounded-full", dotClassName)} />
            {issue}
          </li>
        ))}
      </ul>
    </div>
  );
}

// ─── stat card ───────────────────────────────────────────────────────────────

function StatCard({ label, value, icon: Icon }: {
  label: string;
  value: string;
  icon?: React.ComponentType<{ className?: string }>;
}) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center gap-2 text-muted-foreground mb-1">
        {Icon && <Icon className="h-3.5 w-3.5" />}
        <span className="text-xs">{label}</span>
      </div>
      <p className="text-xl font-semibold text-foreground tabular-nums">{value}</p>
    </div>
  );
}

// SWR's polling effect depends on this function BY REFERENCE (see swr's
// useSWR internals: the interval useEffect's deps array includes
// `refreshInterval` itself). Defining it inline in the component body — as
// this used to do — creates a new function every render, which tears down
// and reschedules the poll's setTimeout on every single re-render. This page
// re-renders once a second on its own (the elapsed-time ticker below), which
// meant the poll's setTimeout was reset every ~1s and could never survive
// long enough to reach its own 3s mark — i.e. it silently never fired,
// exactly matching "stuck in progress until I hard refresh". Hoisting this
// to module scope gives it a permanently stable reference.
function jobRefreshInterval(data?: AnalysisResult) {
  return data?.status === "processing" || data?.status === "pending" ? 3000 : 0;
}

// ─── page ────────────────────────────────────────────────────────────────────

export default function JobDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);

  const { data: result, isLoading, error, mutate } = useSWR<AnalysisResult>(
    `/api/result/${id}`,
    fetcher,
    {
      refreshInterval: jobRefreshInterval,
      // Belt-and-suspenders on top of SWR's built-in focus revalidation:
      // browsers throttle/pause timers in backgrounded tabs (e.g. while you
      // switch over to view the PR on GitHub), so the interval above can
      // silently stop firing. Explicitly refetch on focus/reconnect so
      // switching back to the tab always shows the latest state instead of
      // requiring a hard refresh.
      revalidateOnFocus: true,
      revalidateOnReconnect: true,
    },
  );

  // Extra safety net for the same background-tab-throttling issue: force an
  // immediate refetch whenever the tab becomes visible again, rather than
  // waiting on the timer or trusting focus-event timing alone.
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible") mutate();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [mutate]);

  // Must run on every render (before any early return) to satisfy the Rules
  // of Hooks — hook order can't change based on loading/error state.
  const isTerminal = result
    ? result.status === "completed" || result.status === "failed"
    : true;
  const elapsedSec = useElapsedSeconds(
    isTerminal ? undefined : result?.started_at ?? result?.created_at
  );

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!result) {
    return (
      <div className="flex h-64 flex-col items-center justify-center text-center">
        <p className="text-lg font-medium text-foreground">Job not found</p>
        <p className="mt-1 text-sm text-muted-foreground">
          {error ? `Error: ${(error as any)?.message}` : "The requested job could not be found."}
        </p>
        <Link href="/jobs" className="mt-4 text-sm text-ring hover:underline">Back to jobs</Link>
      </div>
    );
  }

  const riskLevel  = result.risk_level ?? result.overall_risk;

  const cacheLabel = result.cache_hits != null && result.cache_misses != null
    ? `${result.cache_hits} / ${result.cache_hits + result.cache_misses}`
    : "—";

  const isStale = !isTerminal && elapsedSec != null && elapsedSec > STALE_JOB_THRESHOLD_SEC;

  return (
    <div className="space-y-6">

      {/* ── header ── */}
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <Link
            href="/jobs"
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors mb-2"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            All jobs
          </Link>
          <h1 className="text-xl font-semibold text-foreground truncate">
            {result.owner && result.repo
              ? `${result.owner} / ${result.repo} #${result.pr_number}`
              : result.job_id}
          </h1>
          <p className="mt-0.5 text-xs text-muted-foreground font-mono">{result.job_id}</p>
        </div>

        <div className="flex flex-shrink-0 items-center gap-2">
          <JobStatusBadge status={result.status} />
          {riskLevel && <RiskBadge level={riskLevel} />}
          {result.owner && result.repo && result.pr_number && (
            <a
              href={`https://github.com/${result.owner}/${result.repo}/pull/${result.pr_number}`}
              target="_blank" rel="noopener noreferrer"
              className="flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-1.5 text-xs text-foreground hover:bg-secondary transition-colors"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              GitHub PR
            </a>
          )}
        </div>
      </div>

      {/* ── stat row ── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard
          label="Duration"
          value={
            isTerminal
              ? safeDuration(result.created_at, result.completed_at)
              : elapsedSec != null
                ? `${elapsedSec}s elapsed`
                : "In progress…"
          }
          icon={Clock}
        />
        <StatCard
          label="AST Cache"
          value={cacheLabel}
          icon={Database}
        />
        <StatCard
          label="Files Analyzed"
          value={result.files_analyzed != null ? String(result.files_analyzed) : "—"}
        />
        <StatCard
          label="Risk Score"
          value={result.risk_score != null ? `${result.risk_score} / 100` : "—"}
        />
      </div>

      {/* ── notices ── */}
      {isStale && (
        <div className="flex items-start gap-3 rounded-lg border border-yellow-400/30 bg-yellow-400/5 px-4 py-3 text-sm text-yellow-400">
          <AlertTriangle className="h-4 w-4 flex-shrink-0 mt-0.5" />
          <div>
            <p className="font-medium">Taking longer than expected</p>
            <p className="mt-0.5 text-xs text-yellow-400/80">
              This job has been {result.status} for over {STALE_JOB_THRESHOLD_SEC}s. It may be
              stuck — check the backend logs, or{" "}
              <Link href="/dashboard" className="underline decoration-dotted underline-offset-2">
                start a new analysis
              </Link>{" "}
              instead of waiting further.
            </p>
          </div>
        </div>
      )}
      {result.skipped_reason && (
        <div className="rounded-lg border border-border bg-card px-4 py-3 text-sm text-muted-foreground">
          <span className="font-medium text-foreground">Skipped: </span>
          {result.skipped_reason}
        </div>
      )}
      {result.error && (
        <div className="rounded-lg border border-red-500/20 bg-red-500/5 px-4 py-3 text-sm text-red-400">
          <span className="font-medium">Error: </span>{result.error}
        </div>
      )}

      {/* ── live pipeline progress (replaces blank space while running) ── */}
      {!isTerminal && (
        <PipelineStepper status={result.status} stage={result.stage} />
      )}

      {/* ── summary ── */}
      {result.headline && (
        <div className="rounded-lg border border-border bg-card px-6 py-5">
          <h2 className="text-base font-semibold text-foreground leading-snug">
            {result.headline}
          </h2>
          {result.summary && (
            <p className="mt-2 text-sm text-muted-foreground leading-relaxed">{result.summary}</p>
          )}
        </div>
      )}

      {/* ── change-impact diagram ── */}
      {result.mermaid_diagram && (
        <div>
          <h2 className="mb-3 text-sm font-semibold text-foreground">Change Impact</h2>
          <MermaidDiagram source={result.mermaid_diagram} />
        </div>
      )}

      {/* ── findings grid ── */}
      {(result.insights?.length > 0 ||
        result.recommendations?.length > 0 ||
        result.memory_safety_issues?.length > 0 ||
        result.security_concerns?.length > 0 ||
        result.potential_bugs?.length > 0) && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <IssueSection title="Insights"          icon={Lightbulb}      issues={result.insights}              iconClassName="text-indigo-400"  dotClassName="bg-indigo-400" />
          <IssueSection title="Recommendations"   icon={Sparkles}       issues={result.recommendations}       iconClassName="text-emerald-400" dotClassName="bg-emerald-400" />
          <IssueSection title="Memory Safety"      icon={AlertTriangle}  issues={result.memory_safety_issues}  iconClassName="text-red-400"     dotClassName="bg-red-400" />
          <IssueSection title="Security Concerns"  icon={Shield}         issues={result.security_concerns}     iconClassName="text-orange-400"  dotClassName="bg-orange-400" />
          <IssueSection title="Potential Bugs"     icon={Bug}            issues={result.potential_bugs}        iconClassName="text-yellow-400"  dotClassName="bg-yellow-400" />
        </div>
      )}

      {/* ── function analyses ── */}
      {result.function_analyses?.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-foreground">
              Function Analysis
              <span className="ml-2 rounded-full bg-secondary px-2 py-0.5 text-xs font-normal text-muted-foreground">
                {result.function_analyses.length}
              </span>
            </h2>
            <Link
              href="/reference"
              className="text-xs text-muted-foreground hover:text-foreground transition-colors underline decoration-dotted underline-offset-2"
            >
              Signal reference →
            </Link>
          </div>
          <FunctionGrid analyses={result.function_analyses} />
        </div>
      )}

    </div>
  );
}