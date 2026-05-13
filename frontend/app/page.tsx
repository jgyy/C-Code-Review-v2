"use client";

import useSWR from "swr";
import { StatsCards } from "@/components/dashboard/stats-cards";
import { RecentJobs } from "@/components/dashboard/recent-jobs";
import { QuickAnalyze } from "@/components/dashboard/quick-analyze";
import { fetcher } from "@/lib/api";
import type { CacheStats, JobStatus, AnalysisResult } from "@/lib/api";
import { Loader2 } from "lucide-react";

// Mock data for demo - replace with real API calls
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
];

export default function DashboardPage() {
  // Fetch cache stats
  const { data: cacheStats, isLoading: cacheLoading } = useSWR<CacheStats>(
    "/api/cache/stats",
    fetcher,
    {
      refreshInterval: 30000, // Refresh every 30s
      fallbackData: {
        total_entries: 1247,
        memory_usage_bytes: 52428800,
        hit_count: 8934,
        miss_count: 2156,
        hit_rate: 0.806,
      },
    }
  );

  // In production, fetch from /api/jobs
  const jobs = mockJobs;

  // Calculate stats from jobs and cache
  const stats = {
    totalJobs: 1523,
    successRate: 94.2,
    avgAnalysisTime: 12.4,
    cacheHitRate: (cacheStats?.hit_rate ?? 0) * 100,
  };

  if (cacheLoading) {
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
