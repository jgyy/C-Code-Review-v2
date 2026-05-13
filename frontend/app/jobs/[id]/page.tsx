"use client";

import { use } from "react";
import Link from "next/link";
import useSWR from "swr";
import { format, formatDistanceToNow } from "date-fns";
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
  Shield,
  Bug,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";

// Mock data for demo
const mockResult: AnalysisResult = {
  job_id: "job-001",
  owner: "torvalds",
  repo: "linux",
  pr_number: 1234,
  status: "completed",
  created_at: new Date(Date.now() - 1000 * 60 * 10).toISOString(),
  completed_at: new Date(Date.now() - 1000 * 60 * 5).toISOString(),
  triage_decision: "deep_analysis",
  risk_score: 35,
  headline: "Memory safety concerns in buffer handling",
  summary:
    "This PR introduces changes to the memory management subsystem. The analysis detected potential buffer overflow risks in the new allocation routines and recommends additional bounds checking.",
  overall_risk: "medium",
  files_analyzed: 12,
  cache_hits: 8,
  cache_misses: 4,
  function_analyses: [
    {
      name: "alloc_buffer",
      risk_level: "high",
      summary: "Buffer allocation without proper size validation",
      issues: [
        "No upper bound check on requested size",
        "Potential integer overflow in size calculation",
      ],
      recommendations: [
        "Add size_t overflow check before allocation",
        "Implement maximum allocation limit",
      ],
      line_start: 145,
      line_end: 178,
    },
    {
      name: "copy_to_user",
      risk_level: "medium",
      summary: "User-space copy with unchecked length",
      issues: ["Length parameter not validated against buffer size"],
      recommendations: ["Verify length does not exceed allocated buffer"],
      line_start: 234,
      line_end: 256,
    },
    {
      name: "init_subsystem",
      risk_level: "low",
      summary: "Initialization routine looks safe",
      issues: [],
      recommendations: [],
      line_start: 45,
      line_end: 89,
    },
  ],
  memory_safety_issues: [
    "Potential buffer overflow in alloc_buffer at line 156",
    "Missing null check after kmalloc at line 167",
  ],
  security_concerns: [
    "User-controlled size passed to allocator without validation",
  ],
  potential_bugs: [
    "Return value of copy_to_user not checked",
    "Memory leak on error path at line 172",
  ],
};

function FunctionAnalysisCard({ analysis }: { analysis: FunctionAnalysis }) {
  const [isExpanded, setIsExpanded] = useState(false);

  return (
    <div className="rounded-lg border border-border bg-secondary/30">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex w-full items-center justify-between px-4 py-3 text-left"
      >
        <div className="flex items-center gap-3">
          {isExpanded ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground" />
          )}
          <code className="font-mono text-sm text-foreground">
            {analysis.name}()
          </code>
          {analysis.line_start && (
            <span className="text-xs text-muted-foreground">
              L{analysis.line_start}-{analysis.line_end}
            </span>
          )}
        </div>
        <RiskBadge level={analysis.risk_level} size="sm" />
      </button>

      {isExpanded && (
        <div className="border-t border-border px-4 py-3 space-y-3">
          <p className="text-sm text-muted-foreground">{analysis.summary}</p>

          {analysis.issues.length > 0 && (
            <div>
              <h5 className="text-xs font-medium uppercase text-muted-foreground">
                Issues
              </h5>
              <ul className="mt-1 space-y-1">
                {analysis.issues.map((issue, i) => (
                  <li
                    key={i}
                    className="flex items-start gap-2 text-sm text-foreground"
                  >
                    <span className="mt-1.5 h-1 w-1 rounded-full bg-status-failed" />
                    {issue}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {analysis.recommendations.length > 0 && (
            <div>
              <h5 className="text-xs font-medium uppercase text-muted-foreground">
                Recommendations
              </h5>
              <ul className="mt-1 space-y-1">
                {analysis.recommendations.map((rec, i) => (
                  <li
                    key={i}
                    className="flex items-start gap-2 text-sm text-foreground"
                  >
                    <span className="mt-1.5 h-1 w-1 rounded-full bg-status-completed" />
                    {rec}
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
  color,
}: {
  title: string;
  icon: React.ComponentType<{ className?: string }>;
  issues: string[];
  color: string;
}) {
  if (issues.length === 0) return null;

  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="flex items-center gap-2">
        <Icon className={cn("h-5 w-5", color)} />
        <h3 className="font-medium text-foreground">{title}</h3>
        <span className="rounded-full bg-secondary px-2 py-0.5 text-xs text-muted-foreground">
          {issues.length}
        </span>
      </div>
      <ul className="mt-3 space-y-2">
        {issues.map((issue, i) => (
          <li key={i} className="flex items-start gap-2 text-sm text-foreground">
            <span className={cn("mt-1.5 h-1.5 w-1.5 rounded-full", color.replace("text-", "bg-"))} />
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

  // In production, fetch from /api/result/{id}
  // const { data: result, isLoading, error } = useSWR<AnalysisResult>(
  //   `/api/result/${id}`,
  //   fetcher,
  //   { refreshInterval: result?.status === "processing" ? 3000 : 0 }
  // );
  const result = mockResult;
  const isLoading = false;

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
          The requested job could not be found.
        </p>
        <Link
          href="/jobs"
          className="mt-4 text-sm text-ring hover:underline"
        >
          Back to jobs
        </Link>
      </div>
    );
  }

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
            {result.owner}/{result.repo} #{result.pr_number}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Job ID: {result.job_id}
          </p>
        </div>

        <div className="flex items-center gap-3">
          <JobStatusBadge status={result.status} />
          {result.overall_risk && <RiskBadge level={result.overall_risk} />}
          <a
            href={`https://github.com/${result.owner}/${result.repo}/pull/${result.pr_number}`}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 rounded-md bg-secondary px-3 py-1.5 text-sm text-foreground transition-colors hover:bg-secondary/80"
          >
            <ExternalLink className="h-4 w-4" />
            View PR
          </a>
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
            {result.completed_at
              ? `${Math.round(
                  (new Date(result.completed_at).getTime() -
                    new Date(result.created_at).getTime()) /
                    1000
                )}s`
              : "In progress..."}
          </p>
        </div>

        <div className="rounded-lg border border-border bg-card p-4">
          <div className="flex items-center gap-2 text-muted-foreground">
            <Database className="h-4 w-4" />
            <span className="text-sm">Cache Performance</span>
          </div>
          <p className="mt-1 text-lg font-medium text-foreground">
            {result.cache_hits}/{result.cache_hits + result.cache_misses} hits
          </p>
        </div>

        <div className="rounded-lg border border-border bg-card p-4">
          <div className="flex items-center gap-2 text-muted-foreground">
            <span className="text-sm">Files Analyzed</span>
          </div>
          <p className="mt-1 text-lg font-medium text-foreground">
            {result.files_analyzed}
          </p>
        </div>

        <div className="rounded-lg border border-border bg-card p-4">
          <div className="flex items-center gap-2 text-muted-foreground">
            <span className="text-sm">Risk Score</span>
          </div>
          <p className="mt-1 text-lg font-medium text-foreground">
            {result.risk_score}/100
          </p>
        </div>
      </div>

      {/* Summary */}
      {result.headline && (
        <div className="rounded-lg border border-border bg-card p-6">
          <h2 className="text-lg font-semibold text-foreground">
            {result.headline}
          </h2>
          {result.summary && (
            <p className="mt-2 text-muted-foreground">{result.summary}</p>
          )}
        </div>
      )}

      {/* Issues Grid */}
      <div className="grid gap-4 lg:grid-cols-3">
        <IssueSection
          title="Memory Safety"
          icon={AlertTriangle}
          issues={result.memory_safety_issues}
          color="text-status-failed"
        />
        <IssueSection
          title="Security Concerns"
          icon={Shield}
          issues={result.security_concerns}
          color="text-risk-high"
        />
        <IssueSection
          title="Potential Bugs"
          icon={Bug}
          issues={result.potential_bugs}
          color="text-status-pending"
        />
      </div>

      {/* Function Analyses */}
      {result.function_analyses.length > 0 && (
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
