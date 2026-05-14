"use client";

import { useState } from "react";
import useSWR from "swr";
import { JobList } from "@/components/jobs/job-list";
import { fetcher } from "@/lib/api";
import type { JobStatus, AnalysisResult } from "@/lib/api";
import { Loader2, Filter } from "lucide-react";

type StatusFilter = "all" | "pending" | "processing" | "completed" | "failed";

export default function JobsPage() {
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [page, setPage] = useState(0);
  const JOBS_PER_PAGE = 20;

  // Fetch jobs from API
  const { data: jobsData, isLoading } = useSWR<{ jobs: JobStatus[]; total: number }>(
    `/api/jobs?limit=${JOBS_PER_PAGE}&offset=${page * JOBS_PER_PAGE}`,
    fetcher,
    {
      refreshInterval: 5000, // Refresh every 5s
    }
  );

  const jobs: (JobStatus & Partial<AnalysisResult>)[] = jobsData?.jobs ?? [];
  const totalJobs = jobsData?.total ?? 0;

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

  const totalPages = Math.ceil(totalJobs / JOBS_PER_PAGE);

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
              onClick={() => {
                setStatusFilter(status);
                setPage(0);
              }}
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

      {/* Pagination */}
      <div className="flex items-center justify-between border-t pt-4">
        <div className="text-sm text-muted-foreground">
          Showing {page * JOBS_PER_PAGE + 1} to {Math.min((page + 1) * JOBS_PER_PAGE, totalJobs)} of {totalJobs}
        </div>

        <div className="flex gap-2">
          <button
            onClick={() => setPage(Math.max(0, page - 1))}
            disabled={page === 0}
            className="rounded-md px-3 py-1.5 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Previous
          </button>
          <span className="flex items-center px-3 py-1.5 text-sm">
            Page {page + 1} of {totalPages}
          </span>
          <button
            onClick={() => setPage(Math.min(totalPages - 1, page + 1))}
            disabled={page >= totalPages - 1}
            className="rounded-md px-3 py-1.5 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}

