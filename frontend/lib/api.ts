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
  created_at: string;
  started_at?: string;
  completed_at?: string;
  error?: string;
  progress?: {
    files_processed: number;
    total_files: number;
    current_file?: string;
  };
}

export interface FunctionAnalysis {
  name: string;
  risk_level: "low" | "medium" | "high" | "critical";
  summary: string;
  issues: string[];
  recommendations: string[];
  line_start?: number;
  line_end?: number;
}

export interface AnalysisResult {
  job_id: string;
  owner: string;
  repo: string;
  pr_number: number;
  status: "pending" | "processing" | "completed" | "failed";
  created_at: string;
  completed_at: string;
  
  // Triage info
  triage_decision: "skip" | "fast_path" | "deep_analysis";
  risk_score: number;
  
  // Analysis results
  headline?: string;
  summary?: string;
  overall_risk: "low" | "medium" | "high" | "critical";
  
  // Per-file results
  files_analyzed: number;
  cache_hits: number;
  cache_misses: number;
  
  // Function-level analysis
  function_analyses: FunctionAnalysis[];
  
  // Grouped issues
  insights: string[];
  recommendations: string[];
  memory_safety_issues: string[];
  security_concerns: string[];
  potential_bugs: string[];
  
  // Error info if failed
  error?: string;
}

export interface CacheStats {
  total_entries: number;
  memory_usage_bytes: number;
  hit_count: number;
  miss_count: number;
  hit_rate: number;
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
    // Server-side: use getServerSession with authOptions
    const session = await getServerSession(authOptions)
    accessToken = session?.accessToken
  } else {
    // Client-side
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
  getStatus: (jobId: string) => request<JobStatus>(`/status/${jobId}`),
  getResult: (jobId: string) => request<AnalysisResult>(`/result/${jobId}`),
  getCacheStats: () => request<CacheStats>("/cache/stats"),
  clearCache: () => request<{ cleared: number }>("/cache/clear", { method: "POST" }),
  health: () => request<HealthStatus>("/health"),
  listJobs: (limit = 50, offset = 0) =>
    request<{ jobs: JobStatus[]; total: number }>(`/jobs?limit=${limit}&offset=${offset}`),
}

export const fetcher = <T>(endpoint: string): Promise<T> => request<T>(endpoint)