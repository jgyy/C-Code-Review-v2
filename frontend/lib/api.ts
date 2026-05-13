// API client for the C Code Review backend

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
  status: "completed" | "failed";
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

const API_BASE = "/api";

class APIError extends Error {
  constructor(
    message: string,
    public status: number,
    public body?: unknown
  ) {
    super(message);
    this.name = "APIError";
  }
}

async function request<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE}${endpoint}`;
  
  const response = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new APIError(
      body?.detail || `Request failed with status ${response.status}`,
      response.status,
      body
    );
  }

  return response.json();
}

export const api = {
  // Trigger analysis
  analyze: (data: AnalyzeRequest) =>
    request<{ job_id: string }>("/analyze", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  // Get job status
  getStatus: (jobId: string) =>
    request<JobStatus>(`/status/${jobId}`),

  // Get full analysis result
  getResult: (jobId: string) =>
    request<AnalysisResult>(`/result/${jobId}`),

  // Get cache stats
  getCacheStats: () =>
    request<CacheStats>("/cache/stats"),

  // Clear cache
  clearCache: () =>
    request<{ cleared: number }>("/cache/clear", {
      method: "POST",
    }),

  // Health check
  health: () =>
    request<HealthStatus>("/health"),

  // List recent jobs (mock - would need backend endpoint)
  listJobs: (limit = 50, offset = 0) =>
    request<{ jobs: JobStatus[]; total: number }>(
      `/jobs?limit=${limit}&offset=${offset}`
    ),
};

// SWR fetcher
export const fetcher = <T>(url: string): Promise<T> =>
  request<T>(url.replace(API_BASE, ""));
