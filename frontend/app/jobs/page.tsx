"use client";

import { useState } from "react";
import useSWR from "swr";
import { JobList } from "@/components/jobs/job-list";
import { fetcher } from "@/lib/api";
import type { JobStatus, AnalysisResult } from "@/lib/api";
import { Loader2, Filter } from "lucide-react";

// Mock data for demo
const mockJobs: (JobStatus & Partial<AnalysisResult>)[] = [
  {
    job_id: "job-001",
    status: "completed",
    created_at: new Date(Date.now() - 1000 * 60 * 5).toISOString(),
    owner: "torvalds",
    repo: "linux",
    pr_number: 1234,
    overall_risk: "low",
  },
  {
    job_id: "job-002",
    status: "processing",
    created_at: new Date(Date.now() - 1000 * 60 * 2).toISOString(),
    owner: "redis",
    repo: "redis",
    pr_number: 567,
  },
  {
    job_id: "job-003",
    status: "completed",
    created_at: new Date(Date.now() - 1000 * 60 * 30).toISOString(),
    owner: "curl",
    repo: "curl",
    pr_number: 890,
    overall_risk: "high",
  },
  {
    job_id: "job-004",
    status: "failed",
    created_at: new Date(Date.now() - 1000 * 60 * 60).toISOString(),
    owner: "git",
    repo: "git",
    pr_number: 111,
  },
  {
    job_id: "job-005",
    status: "completed",
    created_at: new Date(Date.now() - 1000 * 60 * 120).toISOString(),
    owner: "nginx",
    repo: "nginx",
    pr_number: 222,
    overall_risk: "medium",
  },
  {
    job_id: "job-006",
    status: "pending",
    created_at: new Date(Date.now() - 1000 * 30).toISOString(),
    owner: "openssl",
    repo: "openssl",
    pr_number: 333,
  },
  {
    job_id: "job-007",
    status: "completed",
    created_at: new Date(Date.now() - 1000 * 60 * 180).toISOString(),
    owner: "ffmpeg",
    repo: "FFmpeg",
    pr_number: 444,
    overall_risk: "critical",
  },
];

type StatusFilter = "all" | "pending" | "processing" | "completed" | "failed";

export default function JobsPage() {
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  
  // In production, fetch from /api/jobs
  const jobs = mockJobs;
  const isLoading = false;

  const filteredJobs = statusFilter === "all"
    ? jobs
    : jobs.filter((job) => job.status === statusFilter);

  const statusCounts = {
    all: jobs.length,
    pending: jobs.filter((j) => j.status === "pending").length,
    processing: jobs.filter((j) => j.status === "processing").length,
    completed: jobs.filter((j) => j.status === "completed").length,
    failed: jobs.filter((j) => j.status === "failed").length,
  };

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Filters */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm text-muted-foreground">Filter:</span>
        </div>
        
        <div className="flex gap-2">
          {(["all", "pending", "processing", "completed", "failed"] as const).map((status) => (
            <button
              key={status}
              onClick={() => setStatusFilter(status)}
              className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                statusFilter === status
                  ? "bg-secondary text-foreground"
                  : "text-muted-foreground hover:bg-secondary/50 hover:text-foreground"
              }`}
            >
              {status.charAt(0).toUpperCase() + status.slice(1)}
              <span className="ml-1.5 text-muted-foreground">
                ({statusCounts[status]})
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* Job List */}
      <JobList jobs={filteredJobs} />
    </div>
  );
}
