"use client";

import useSWR from "swr";
import { StatsCards } from "@/components/dashboard/stats-cards";
import { RecentJobs } from "@/components/dashboard/recent-jobs";
import { QuickAnalyze } from "@/components/dashboard/quick-analyze";
import { fetcher } from "@/lib/api";
import type { CacheStats, JobStatus, AnalysisResult } from "@/lib/api";
import { Loader2 } from "lucide-react";

export default function DashboardPage() {
  const { data: cacheStats, isLoading: cacheLoading } = useSWR<CacheStats>(
    `/api/cache/stats`,
    fetcher,
    { refreshInterval: 30000, revalidateOnFocus: false, shouldRetryOnError: false }
  );

  const { data: jobsData, isLoading: jobsLoading } = useSWR<{ jobs: JobStatus[]; total: number }>(
    `/api/jobs?limit=5`,
    fetcher,
    { refreshInterval: 10000, revalidateOnFocus: false, shouldRetryOnError: false }
  );

  const jobs: (JobStatus & Partial<AnalysisResult>)[] = jobsData?.jobs ?? [];

  // Derive avg analysis time from jobs that have both timestamps
  const completedWithTimes = jobs.filter(
    (j) => j.status === "completed" && j.created_at && j.completed_at
  );
  const avgAnalysisTime =
    completedWithTimes.length > 0
      ? completedWithTimes.reduce((sum, j) => {
          const secs =
            (new Date(j.completed_at!).getTime() - new Date(j.created_at!).getTime()) / 1000;
          return sum + secs;
        }, 0) / completedWithTimes.length
      : 0;

  const stats = {
    totalJobs: jobsData?.total ?? 0,
    successRate:
      jobs.length > 0
        ? (jobs.filter((j) => j.status === "completed").length / jobs.length) * 100
        : 0,
    avgAnalysisTime,
    cacheHitRate: 0, // CacheStats from backend doesn't include hit_rate; show 0 until backend exposes it
  };

  const isLoading = cacheLoading || jobsLoading;

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <StatsCards stats={stats} />

      <div className="grid gap-6 lg:grid-cols-2">
        <RecentJobs jobs={jobs} />
        <QuickAnalyze />
      </div>
    </div>
  );
}