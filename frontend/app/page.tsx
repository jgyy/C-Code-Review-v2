"use client";

import useSWR from "swr";
import { StatsCards } from "@/components/dashboard/stats-cards";
import { RecentJobs } from "@/components/dashboard/recent-jobs";
import { QuickAnalyze } from "@/components/dashboard/quick-analyze";
import { fetcher, api } from "@/lib/api";
import type { CacheStats, JobStatus, AnalysisResult } from "@/lib/api";
import { Loader2 } from "lucide-react";

const API_BASE = process.env.NEXT_PUBLIC_API_SERVICE;

export default function DashboardPage() {
  // Fetch cache stats
  const { data: cacheStats, isLoading: cacheLoading } = useSWR<CacheStats>(
    `/api/cache/stats`,
    fetcher,
    {
      refreshInterval: 30000, // Refresh every 30s
        revalidateOnFocus: false,
  shouldRetryOnError: false,
    }
  );

  // Fetch recent jobs
  const { data: jobsData, isLoading: jobsLoading } = useSWR<{ jobs: JobStatus[]; total: number }>(
    `/api/jobs?limit=5`,
    fetcher,
    {
      refreshInterval: 10000, // Refresh every 10s
        revalidateOnFocus: false,
  shouldRetryOnError: false,
    }
  );

  const jobs: (JobStatus & Partial<AnalysisResult>)[] = jobsData?.jobs ?? [];

  // Calculate stats from jobs and cache
  const stats = {
    totalJobs: jobsData?.total ?? 0,
    successRate: jobs.length > 0
      ? Math.round((jobs.filter((j) => j.status === "completed").length / jobs.length) * 100)
      : 0,
    avgAnalysisTime: 12.4,
    cacheHitRate: cacheStats?.hit_rate ?? 0,
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

