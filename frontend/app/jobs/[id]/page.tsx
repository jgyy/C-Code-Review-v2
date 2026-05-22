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
} from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";

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

// Matches backend FunctionAnalysisOutput exactly
function FunctionAnalysisCard({ analysis }: { analysis: FunctionAnalysis }) {
  const [isExpanded, setIsExpanded] = useState(false);

  const riskSignals = analysis.risk_signals ?? [];
  const potentialBugs = analysis.potential_bugs ?? [];
  const securityConcerns = analysis.security_concerns ?? [];

  const hasDetails =
    riskSignals.length > 0 ||
    !!analysis.suggestion ||
    potentialBugs.length > 0 ||
    securityConcerns.length > 0;

  return (
    <div className="rounded-lg border border-border bg-secondary/30">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex w-full items-center justify-between px-4 py-3 text-left"
        disabled={!hasDetails}
      >
        <div className="flex items-center gap-3">
          {hasDetails ? (
            isExpanded ? (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronRight className="h-4 w-4 text-muted-foreground" />
            )
          ) : (
            <span className="h-4 w-4" />
          )}
          <code className="font-mono text-sm text-foreground">{analysis.name}()</code>
        </div>
        <RiskBadge level={analysis.risk_level} size="sm" />
      </button>

      {isExpanded && hasDetails && (
        <div className="border-t border-border px-4 py-3 space-y-3">
          {analysis.suggestion && (
            <p className="text-sm text-muted-foreground">{analysis.suggestion}</p>
          )}

          {riskSignals.length > 0 && (
            <div>
              <h5 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Risk Signals
              </h5>
              <ul className="mt-1 space-y-1">
                {riskSignals.map((signal, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-foreground">
                    <span className="mt-1.5 h-1 w-1 flex-shrink-0 rounded-full bg-status-pending" />
                    {signal}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {potentialBugs.length > 0 && (
            <div>
              <h5 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Potential Bugs
              </h5>
              <ul className="mt-1 space-y-1">
                {potentialBugs.map((bug, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-foreground">
                    <span className="mt-1.5 h-1 w-1 flex-shrink-0 rounded-full bg-status-failed" />
                    {bug}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {securityConcerns.length > 0 && (
            <div>
              <h5 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Security Concerns
              </h5>
              <ul className="mt-1 space-y-1">
                {securityConcerns.map((concern, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-foreground">
                    <span className="mt-1.5 h-1 w-1 flex-shrink-0 rounded-full bg-risk-high" />
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
  const riskLevel = result.risk_level ?? result.overall_risk;

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

      {/* Function Analyses */}
      {result.function_analyses && result.function_analyses.length > 0 && (
        <div>
          <h2 className="mb-4 text-lg font-semibold text-foreground">
            Function Analysis ({result.function_analyses.length})
          </h2>
          <div className="space-y-2">
            {result.function_analyses.map((analysis, i) => (
              <FunctionAnalysisCard key={i} analysis={analysis} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}