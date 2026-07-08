"use client";

import { useState } from "react";
import useSWR from "swr";
import { StatsCards } from "@/components/dashboard/stats-cards";
import { RecentJobs } from "@/components/dashboard/recent-jobs";
import { QuickAnalyze } from "@/components/dashboard/quick-analyze";
import {
  RecentRepositories,
  type RecentRepository,
} from "@/components/dashboard/recent-repositories";
import { fetcher } from "@/lib/api";
import type { CacheStats, JobStatus, AnalysisResult } from "@/lib/api";
import { Loader2 } from "lucide-react";

export default function DashboardPage() {
  const [selectedRepository, setSelectedRepository] =
    useState<RecentRepository | null>(null);

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
  const jobsByCreatedAt = [...jobs].sort(
    (a, b) =>
      new Date(b.created_at ?? 0).getTime() -
      new Date(a.created_at ?? 0).getTime()
  );
  const recentRepositories = Array.from(
    jobsByCreatedAt.reduce((repositories, job) => {
      if (!job.owner || !job.repo) return repositories;

      const key = `${job.owner}/${job.repo}`;
      if (!repositories.has(key)) {
        repositories.set(key, {
          owner: job.owner,
          repo: job.repo,
          lastPrNumber: job.pr_number,
          lastAnalyzedAt: job.created_at,
        });
      }

      return repositories;
    }, new Map<string, RecentRepository>()).values()
  ).slice(0, 5);

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

  // Compute cache hit rate from jobs that have both cache_hits and cache_misses recorded.
  // The /api/cache/stats endpoint only returns total_keys, not a hit rate, so we derive
  // it from completed job results which do carry per-job cache_hits/cache_misses.
  const jobsWithCacheData = jobs.filter(
    (j) => j.cache_hits != null && j.cache_misses != null
  );
  const totalHits = jobsWithCacheData.reduce((s, j) => s + (j.cache_hits ?? 0), 0);
  const totalRequests = jobsWithCacheData.reduce(
    (s, j) => s + (j.cache_hits ?? 0) + (j.cache_misses ?? 0),
    0
  );
  const cacheHitRate = totalRequests > 0 ? (totalHits / totalRequests) * 100 : 0;

  const stats = {
    totalJobs: jobsData?.total ?? 0,
    successRate:
      jobs.length > 0
        ? (jobs.filter((j) => j.status === "completed").length / jobs.length) * 100
        : 0,
    avgAnalysisTime,
    cacheHitRate,
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
        <div className="space-y-6">
          <RecentJobs jobs={jobs} />
          <RecentRepositories
            repositories={recentRepositories}
            onSelect={(repository) => setSelectedRepository({ ...repository })}
          />
        </div>
        <QuickAnalyze selectedRepository={selectedRepository} />
      </div>
    </div>
  );
}
