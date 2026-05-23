"use client";

import { use } from "react";
import Link from "next/link";
import useSWR from "swr";
import { formatDistanceToNow, isValid } from "date-fns";
import { JobStatusBadge } from "@/components/jobs/job-status-badge";
import { RiskBadge } from "@/components/jobs/risk-badge";
import { fetcher } from "@/lib/api";
import type { AnalysisResult, FunctionAnalysis } from "@/lib/api";
import {
  Loader2,
  ArrowLeft,
  ExternalLink,
  Clock,
  Database,
  AlertTriangle,
  Lightbulb,
  Sparkles,
  Shield,
  Bug,
  ChevronDown,
  ChevronRight,
  ChevronLeft,
} from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function safeFormatDistance(dateStr?: string): string {
  if (!dateStr) return "—";
  const d = new Date(dateStr);
  if (!isValid(d) || d.getFullYear() < 2020) return "—";
  return formatDistanceToNow(d, { addSuffix: true });
}

function safeDurationSeconds(createdAt?: string, completedAt?: string): string {
  if (!createdAt || !completedAt) return "—";
  const start = new Date(createdAt);
  const end = new Date(completedAt);
  if (!isValid(start) || !isValid(end) || start.getFullYear() < 2020) return "—";
  const secs = Math.round((end.getTime() - start.getTime()) / 1000);
  if (secs < 0) return "—";
  return `${secs}s`;
}

const RISK_ORDER: Record<string, number> = {
  critical: 0,
  high: 1,
  medium: 2,
  low: 3,
};

function sortByRisk(analyses: FunctionAnalysis[]): FunctionAnalysis[] {
  return [...analyses].sort(
    (a, b) =>
      (RISK_ORDER[a.risk_level] ?? 4) - (RISK_ORDER[b.risk_level] ?? 4)
  );
}

// ---------------------------------------------------------------------------
// Risk signal → reference page anchor mapping
//
// The reference page lives at /reference with section IDs matching these anchors.
// Matching is done by substring so partial signal text still links correctly.
// ---------------------------------------------------------------------------

const SIGNAL_ANCHORS: Array<{ pattern: RegExp; anchor: string }> = [
  { pattern: /malloc.*free|free.*malloc|memory.*imbalance|unmatched malloc|memory leak/i, anchor: "malloc-free-imbalance" },
  { pattern: /double.?free/i,                             anchor: "double-free" },
  { pattern: /use.after.free/i,                           anchor: "use-after-free" },
  { pattern: /buffer overflow|out.of.bounds|bounds check/i, anchor: "buffer-overflow" },
  { pattern: /complexity increase|cyclomatic/i,           anchor: "complexity-increase" },
  { pattern: /signature change|return type changed|param.*changed|parameter count/i, anchor: "signature-change" },
  { pattern: /pointer.*density|pointer operation/i,       anchor: "pointer-density" },
  { pattern: /recursion introduced|recursion added/i,     anchor: "recursion-added" },
  { pattern: /recursion removed/i,                        anchor: "recursion-removed" },
  { pattern: /new memory op/i,                            anchor: "new-memory-ops" },
  { pattern: /orphan|lost all caller/i,                   anchor: "orphan-function" },
  { pattern: /nesting depth|depth increase/i,             anchor: "depth-increase" },
  { pattern: /new loop|loop.*added/i,                     anchor: "new-loops" },
  { pattern: /large change/i,                             anchor: "large-change" },
  { pattern: /parse error/i,                              anchor: "parse-errors" },
  { pattern: /format string/i,                            anchor: "format-string" },
  { pattern: /integer overflow|size.*overflow/i,          anchor: "integer-overflow" },
  { pattern: /unchecked return|return value.*check/i,     anchor: "unchecked-return" },
  { pattern: /null pointer|null check|dereference/i,      anchor: "null-pointer" },
];

function anchorForSignal(signal: string): string | null {
  for (const { pattern, anchor } of SIGNAL_ANCHORS) {
    if (pattern.test(signal)) return anchor;
  }
  return null;
}

function SignalLink({ signal }: { signal: string }) {
  const anchor = anchorForSignal(signal);
  if (!anchor) {
    return <span>{signal}</span>;
  }
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

// ---------------------------------------------------------------------------
// Function card — compact for grid layout
// ---------------------------------------------------------------------------

function FunctionAnalysisCard({ analysis }: { analysis: FunctionAnalysis }) {
  const [isExpanded, setIsExpanded] = useState(false);

  const riskSignals    = analysis.risk_signals    ?? [];
  const potentialBugs  = analysis.potential_bugs  ?? [];
  const securityConcerns = analysis.security_concerns ?? [];

  const hasDetails =
    riskSignals.length > 0 ||
    !!analysis.suggestion ||
    potentialBugs.length > 0 ||
    securityConcerns.length > 0;

  return (
    <div className="flex flex-col rounded-lg border border-border bg-secondary/30 overflow-hidden">
      {/* Card header — always visible */}
      <button
        onClick={() => hasDetails && setIsExpanded((v) => !v)}
        className={cn(
          "flex w-full items-start justify-between px-3 py-3 text-left gap-2",
          hasDetails ? "cursor-pointer" : "cursor-default"
        )}
      >
        <div className="flex items-start gap-2 min-w-0">
          {hasDetails ? (
            isExpanded ? (
              <ChevronDown className="h-3.5 w-3.5 mt-0.5 flex-shrink-0 text-muted-foreground" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5 mt-0.5 flex-shrink-0 text-muted-foreground" />
            )
          ) : (
            <span className="h-3.5 w-3.5 flex-shrink-0" />
          )}
          <code className="font-mono text-xs text-foreground break-all leading-relaxed">
            {analysis.name}()
          </code>
        </div>
        <RiskBadge level={analysis.risk_level} size="sm" />
      </button>

      {/* Expanded details */}
      {isExpanded && hasDetails && (
        <div className="border-t border-border px-3 pb-3 pt-2 space-y-2.5">
          {analysis.suggestion && (
            <p className="text-xs text-muted-foreground italic leading-relaxed">
              {analysis.suggestion}
            </p>
          )}

          {riskSignals.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1">
                Risk Signals
              </p>
              <ul className="space-y-1">
                {riskSignals.map((signal, i) => (
                  <li key={i} className="flex items-start gap-1.5 text-xs text-foreground">
                    <span className="mt-1 h-1 w-1 flex-shrink-0 rounded-full bg-status-pending" />
                    <SignalLink signal={signal} />
                  </li>
                ))}
              </ul>
            </div>
          )}

          {potentialBugs.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1">
                Potential Bugs
              </p>
              <ul className="space-y-1">
                {potentialBugs.map((bug, i) => (
                  <li key={i} className="flex items-start gap-1.5 text-xs text-foreground">
                    <span className="mt-1 h-1 w-1 flex-shrink-0 rounded-full bg-status-failed" />
                    {bug}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {securityConcerns.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground mb-1">
                Security
              </p>
              <ul className="space-y-1">
                {securityConcerns.map((concern, i) => (
                  <li key={i} className="flex items-start gap-1.5 text-xs text-foreground">
                    <span className="mt-1 h-1 w-1 flex-shrink-0 rounded-full bg-orange-400" />
                    {concern}
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

// ---------------------------------------------------------------------------
// Paginated 4-column grid
// ---------------------------------------------------------------------------

const PAGE_SIZE = 16; // 4 columns × 4 rows

function FunctionGrid({ analyses }: { analyses: FunctionAnalysis[] }) {
  const [page, setPage] = useState(0);
  const sorted = sortByRisk(analyses);
  const totalPages = Math.ceil(sorted.length / PAGE_SIZE);
  const slice = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  return (
    <div className="space-y-4">
      {/* Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {slice.map((analysis, i) => (
          <FunctionAnalysisCard key={`${analysis.name}-${i}`} analysis={analysis} />
        ))}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between border-t border-border pt-3">
          <span className="text-xs text-muted-foreground">
            Showing {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, sorted.length)} of{" "}
            {sorted.length} functions
          </span>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="rounded p-1 text-muted-foreground hover:bg-secondary hover:text-foreground disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="px-2 text-xs text-muted-foreground">
              {page + 1} / {totalPages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              className="rounded p-1 text-muted-foreground hover:bg-secondary hover:text-foreground disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Issue section
// ---------------------------------------------------------------------------

function IssueSection({
  title,
  icon: Icon,
  issues,
  iconClassName,
  dotClassName,
}: {
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  issues: string[];
  iconClassName: string;
  dotClassName: string;
}) {
  if (!issues || issues.length === 0) return null;

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center gap-2">
        <Icon className={cn("h-5 w-5", iconClassName)} />
        <h3 className="font-medium text-foreground">{title}</h3>
        <span className="rounded-full bg-secondary px-2 py-0.5 text-xs text-muted-foreground">
          {issues.length}
        </span>
      </div>
      <ul className="mt-3 space-y-2">
        {issues.map((issue, i) => (
          <li key={i} className="flex items-start gap-2 text-sm text-foreground">
            <span className={cn("mt-1.5 h-1.5 w-1.5 flex-shrink-0 rounded-full", dotClassName)} />
            {issue}
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function JobDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);

  const { data: result, isLoading, error } = useSWR<AnalysisResult>(
    `/api/result/${id}`,
    fetcher,
    {
      refreshInterval: (data?: AnalysisResult) =>
        data?.status === "processing" || data?.status === "pending" ? 3000 : 0,
    }
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
          {error
            ? `Error: ${(error as any)?.message}`
            : "The requested job could not be found."}
        </p>
        <Link href="/jobs" className="mt-4 text-sm text-ring hover:underline">
          Back to jobs
        </Link>
      </div>
    );
  }

  const isTerminal = result.status === "completed" || result.status === "failed";
  const riskLevel  = result.risk_level ?? result.overall_risk;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <Link
            href="/jobs"
            className="flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to jobs
          </Link>
          <h1 className="mt-2 text-2xl font-semibold text-foreground">
            {result.owner && result.repo
              ? `${result.owner}/${result.repo} #${result.pr_number}`
              : result.job_id}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">Job ID: {result.job_id}</p>
        </div>

        <div className="flex items-center gap-3">
          <JobStatusBadge status={result.status} />
          {riskLevel && <RiskBadge level={riskLevel} />}
          {result.owner && result.repo && result.pr_number && (
            <a
              href={`https://github.com/${result.owner}/${result.repo}/pull/${result.pr_number}`}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 rounded-md bg-secondary px-3 py-1.5 text-sm text-foreground transition-colors hover:bg-secondary/80"
            >
              <ExternalLink className="h-4 w-4" />
              View PR
            </a>
          )}
        </div>
      </div>

      {/* Meta Info */}
      <div className="grid gap-4 sm:grid-cols-4">
        <div className="rounded-lg border border-border bg-card p-4">
          <div className="flex items-center gap-2 text-muted-foreground">
            <Clock className="h-4 w-4" />
            <span className="text-sm">Duration</span>
          </div>
          <p className="mt-1 text-lg font-medium text-foreground">
            {isTerminal
              ? safeDurationSeconds(result.created_at, result.completed_at)
              : "In progress…"}
          </p>
        </div>

        <div className="rounded-lg border border-border bg-card p-4">
          <div className="flex items-center gap-2 text-muted-foreground">
            <Database className="h-4 w-4" />
            <span className="text-sm">Cache Performance</span>
          </div>
          <p className="mt-1 text-lg font-medium text-foreground">
            {result.cache_hits != null && result.cache_misses != null
              ? `${result.cache_hits}/${result.cache_hits + result.cache_misses} hits`
              : "—"}
          </p>
        </div>

        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-sm text-muted-foreground">Files Analyzed</p>
          <p className="mt-1 text-lg font-medium text-foreground">
            {result.files_analyzed ?? "—"}
          </p>
        </div>

        <div className="rounded-lg border border-border bg-card p-4">
          <p className="text-sm text-muted-foreground">Risk Score</p>
          <p className="mt-1 text-lg font-medium text-foreground">
            {result.risk_score != null ? `${result.risk_score}/100` : "—"}
          </p>
        </div>
      </div>

      {/* Skipped / failed notice */}
      {result.skipped_reason && (
        <div className="rounded-lg border border-border bg-card p-4 text-sm text-muted-foreground">
          <span className="font-medium text-foreground">Skipped: </span>
          {result.skipped_reason}
        </div>
      )}
      {result.error && (
        <div className="rounded-lg border border-status-failed/30 bg-status-failed/10 p-4 text-sm text-status-failed">
          <span className="font-medium">Error: </span>
          {result.error}
        </div>
      )}

      {/* Summary */}
      {result.headline && (
        <div className="rounded-lg border border-border bg-card p-6">
          <h2 className="text-lg font-semibold text-foreground">{result.headline}</h2>
          {result.summary && (
            <p className="mt-2 text-muted-foreground">{result.summary}</p>
          )}
        </div>
      )}

      {/* Issues Grid */}
      <div className="grid gap-4 lg:grid-cols-3">
        <IssueSection
          title="Insights"
          icon={Lightbulb}
          issues={result.insights}
          iconClassName="text-indigo-400"
          dotClassName="bg-indigo-400"
        />
        <IssueSection
          title="Recommendations"
          icon={Sparkles}
          issues={result.recommendations}
          iconClassName="text-emerald-400"
          dotClassName="bg-emerald-400"
        />
        <IssueSection
          title="Memory Safety"
          icon={AlertTriangle}
          issues={result.memory_safety_issues}
          iconClassName="text-status-failed"
          dotClassName="bg-status-failed"
        />
        <IssueSection
          title="Security Concerns"
          icon={Shield}
          issues={result.security_concerns}
          iconClassName="text-orange-400"
          dotClassName="bg-orange-400"
        />
        <IssueSection
          title="Potential Bugs"
          icon={Bug}
          issues={result.potential_bugs}
          iconClassName="text-status-pending"
          dotClassName="bg-status-pending"
        />
      </div>

      {/* Function Analyses — 4-column grid, risk-sorted, paginated */}
      {result.function_analyses && result.function_analyses.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-foreground">
              Function Analysis ({result.function_analyses.length})
            </h2>
            <Link
              href="/reference"
              className="text-xs text-muted-foreground hover:text-foreground transition-colors underline decoration-dotted underline-offset-2"
            >
              Risk signal reference →
            </Link>
          </div>
          <FunctionGrid analyses={result.function_analyses} />
        </div>
      )}
    </div>
  );
}