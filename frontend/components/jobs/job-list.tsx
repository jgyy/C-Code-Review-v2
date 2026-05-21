"use client";

import Link from "next/link";
import { formatDistanceToNow, format, isValid } from "date-fns";
import { JobStatusBadge } from "./job-status-badge";
import { RiskBadge } from "./risk-badge";
import { GitPullRequest, ExternalLink } from "lucide-react";
import type { JobStatus, AnalysisResult } from "@/lib/api";

interface JobListProps {
  jobs: (JobStatus & Partial<AnalysisResult>)[];
}

function safeFormatDistance(dateStr?: string): string {
  if (!dateStr) return "—";
  const d = new Date(dateStr);
  if (!isValid(d) || d.getFullYear() < 2020) return "—";
  return formatDistanceToNow(d, { addSuffix: true });
}

function safeFormat(dateStr?: string): string {
  if (!dateStr) return "";
  const d = new Date(dateStr);
  if (!isValid(d) || d.getFullYear() < 2020) return "";
  return format(d, "MMM d, HH:mm");
}

export function JobList({ jobs }: JobListProps) {
  if (jobs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-lg border border-border bg-card p-12 text-center">
        <div className="rounded-full bg-secondary p-4">
          <GitPullRequest className="h-8 w-8 text-muted-foreground" />
        </div>
        <h3 className="mt-4 text-lg font-medium text-foreground">No jobs found</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          Jobs will appear here when PRs are analyzed via webhook or manual trigger.
        </p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-card">
      {/* Table Header */}
      <div className="grid grid-cols-12 gap-4 border-b border-border px-6 py-3 text-sm font-medium text-muted-foreground">
        <div className="col-span-4">Repository / PR</div>
        <div className="col-span-2">Status</div>
        <div className="col-span-2">Risk</div>
        <div className="col-span-2">Created</div>
        <div className="col-span-2 text-right">Actions</div>
      </div>

      {/* Table Body */}
      <div className="divide-y divide-border">
        {jobs.map((job) => {
          // Derive repo label from whatever fields are available
          const owner = job.owner;
          const repo = job.repo;
          const prNumber = job.pr_number;
          const hasRepoInfo = owner && repo;

          return (
            <div
              key={job.job_id}
              className="grid grid-cols-12 items-center gap-4 px-6 py-4 transition-colors hover:bg-secondary/30"
            >
              {/* Repository / PR */}
              <div className="col-span-4 flex items-center gap-3">
                <div className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-md bg-secondary">
                  <GitPullRequest className="h-4 w-4 text-muted-foreground" />
                </div>
                <div className="min-w-0">
                  {hasRepoInfo ? (
                    <>
                      <p className="truncate font-medium text-foreground">
                        {owner}/{repo}
                      </p>
                      <p className="text-sm text-muted-foreground">
                        PR #{prNumber}
                      </p>
                    </>
                  ) : (
                    <p className="truncate font-mono text-xs text-muted-foreground">
                      {job.job_id}
                    </p>
                  )}
                </div>
              </div>

              {/* Status */}
              <div className="col-span-2">
                <JobStatusBadge status={job.status} size="sm" />
              </div>

              {/* Risk */}
              <div className="col-span-2">
                {job.overall_risk ? (
                  <RiskBadge level={job.overall_risk} size="sm" />
                ) : (
                  <span className="text-sm text-muted-foreground">—</span>
                )}
              </div>

              {/* Created */}
              <div className="col-span-2">
                <p className="text-sm text-foreground">
                  {safeFormatDistance(job.created_at)}
                </p>
                <p className="text-xs text-muted-foreground">
                  {safeFormat(job.created_at)}
                </p>
              </div>

              {/* Actions */}
              <div className="col-span-2 flex justify-end gap-2">
                <Link
                  href={`/jobs/${job.job_id}`}
                  className="rounded-md px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
                >
                  View
                </Link>
                {hasRepoInfo && prNumber && (
                  <a
                    href={`https://github.com/${owner}/${repo}/pull/${prNumber}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1 rounded-md px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
                  >
                    <ExternalLink className="h-3.5 w-3.5" />
                    PR
                  </a>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}