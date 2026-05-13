"use client";

import Link from "next/link";
import { formatDistanceToNow } from "date-fns";
import { JobStatusBadge } from "@/components/jobs/job-status-badge";
import { RiskBadge } from "@/components/jobs/risk-badge";
import { GitPullRequest, ArrowRight } from "lucide-react";
import type { JobStatus, AnalysisResult } from "@/lib/api";

interface RecentJobsProps {
  jobs: (JobStatus & Partial<AnalysisResult>)[];
}

export function RecentJobs({ jobs }: RecentJobsProps) {
  if (jobs.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-card p-6">
        <h2 className="text-lg font-semibold text-foreground">Recent Jobs</h2>
        <div className="mt-8 flex flex-col items-center justify-center text-center">
          <div className="rounded-full bg-secondary p-3">
            <GitPullRequest className="h-6 w-6 text-muted-foreground" />
          </div>
          <p className="mt-4 text-sm text-muted-foreground">
            No jobs yet. Trigger your first analysis below.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="flex items-center justify-between border-b border-border px-6 py-4">
        <h2 className="text-lg font-semibold text-foreground">Recent Jobs</h2>
        <Link
          href="/jobs"
          className="flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          View all
          <ArrowRight className="h-4 w-4" />
        </Link>
      </div>
      
      <div className="divide-y divide-border">
        {jobs.slice(0, 5).map((job) => (
          <Link
            key={job.job_id}
            href={`/jobs/${job.job_id}`}
            className="flex items-center justify-between px-6 py-4 transition-colors hover:bg-secondary/30"
          >
            <div className="flex items-center gap-4">
              <div className="flex h-10 w-10 items-center justify-center rounded-md bg-secondary">
                <GitPullRequest className="h-5 w-5 text-muted-foreground" />
              </div>
              <div>
                <p className="font-medium text-foreground">
                  {job.owner}/{job.repo} #{job.pr_number}
                </p>
                <p className="text-sm text-muted-foreground">
                  {formatDistanceToNow(new Date(job.created_at), { addSuffix: true })}
                </p>
              </div>
            </div>
            
            <div className="flex items-center gap-3">
              {job.overall_risk && <RiskBadge level={job.overall_risk} size="sm" />}
              <JobStatusBadge status={job.status} size="sm" />
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
