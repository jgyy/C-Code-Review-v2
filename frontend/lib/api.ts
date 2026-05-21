import { getSession } from "next-auth/react"
import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth"

export interface AnalyzeRequest {
  owner: string;
  repo: string;
  pr_number: number;
}

export interface JobStatus {
  job_id: string;
  status: "pending" | "processing" | "completed" | "failed";
  // These come from the job metadata stored at enqueue time
  owner?: string;
  repo?: string;
  pr_number?: number;
  // Timestamps — optional because the backend doesn't always write them
  created_at?: string;
  started_at?: string;
  completed_at?: string;
  error?: string;
  skipped_reason?: string;
  files_analyzed?: number;
  functions_analyzed?: number;
  cache_hits?: number;
  cache_misses?: number;
}

// Matches llm/schemas.py FunctionAnalysisOutput exactly
export interface FunctionAnalysis {
  name: string;
  risk_level: "low" | "medium" | "high" | "critical";
  risk_signals: string[];
  suggestion?: string;
  potential_bugs: string[];
  security_concerns: string[];
}

export interface AnalysisResult {
  job_id: string;
  owner?: string;
  repo?: string;
  pr_number?: number;
  status: "pending" | "processing" | "completed" | "failed";

  // Timestamps — optional; backend doesn't always persist these
  created_at?: string;
  completed_at?: string;

  // Risk
  risk_score?: number;
  risk_level?: "low" | "medium" | "high" | "critical";
  // Backend returns overall_risk as risk_level in AnalysisResultResponse
  overall_risk?: "low" | "medium" | "high" | "critical";

  // Analysis results
  headline?: string;
  summary?: string;

  // Per-file results
  files_analyzed?: number;
  cache_hits?: number;
  cache_misses?: number;

  // Function-level analysis
  function_analyses: FunctionAnalysis[];

  // Grouped issues
  insights: string[];
  recommendations: string[];
  memory_safety_issues: string[];
  security_concerns: string[];
  potential_bugs: string[];

  // For skipped jobs
  skipped_reason?: string;

  // Error info if failed
  error?: string;
}

export interface CacheStats {
  status: string;
  total_keys?: number;
  error?: string;
}

export interface HealthStatus {
  status: "healthy" | "degraded" | "unhealthy";
  redis_connected: boolean;
  github_configured: boolean;
  llm_configured: boolean;
}

const API_BASE = process.env.NEXT_PUBLIC_API_SERVICE

class APIError extends Error {
  constructor(message: string, public status: number, public body?: unknown) {
    super(message)
    this.name = "APIError"
  }
}

async function request<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  let accessToken: string | undefined

  if (typeof window === "undefined") {
    const session = await getServerSession(authOptions)
    accessToken = session?.accessToken
  } else {
    const session = await getSession()
    accessToken = session?.accessToken
  }

  const url = `${API_BASE}${endpoint}`
  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "ngrok-skip-browser-warning": "any-value",
      ...(accessToken && { Authorization: `Bearer ${accessToken}` }),
      ...options.headers,
    },
  })

  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new APIError(response.statusText, response.status, body)
  }

  return response.json()
}

export const api = {
  analyze: (data: AnalyzeRequest) =>
    request<{ job_id: string }>("/api/analyze", { method: "POST", body: JSON.stringify(data) }),
  // Backend router is mounted at /api in main.py, so all routes need /api/ prefix
  getStatus: (jobId: string) => request<JobStatus>(`/api/status/${jobId}`),
  getResult: (jobId: string) => request<AnalysisResult>(`/api/result/${jobId}`),
  getCacheStats: () => request<CacheStats>("/api/cache/stats"),
  clearCache: () => request<{ cleared: number }>("/api/cache/clear", { method: "POST" }),
  health: () => request<HealthStatus>("/health"),
  listJobs: (limit = 50, offset = 0) =>
    request<{ jobs: JobStatus[]; total: number }>(`/api/jobs?limit=${limit}&offset=${offset}`),
}

export const fetcher = <T>(endpoint: string): Promise<T> => request<T>(endpoint)