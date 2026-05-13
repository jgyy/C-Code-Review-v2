"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { Loader2, Play } from "lucide-react";

export function QuickAnalyze() {
  const router = useRouter();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  
  const [formData, setFormData] = useState({
    owner: "",
    repo: "",
    pr_number: "",
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsLoading(true);

    try {
      const result = await api.analyze({
        owner: formData.owner,
        repo: formData.repo,
        pr_number: parseInt(formData.pr_number, 10),
      });

      router.push(`/jobs/${result.job_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start analysis");
    } finally {
      setIsLoading(false);
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFormData((prev) => ({
      ...prev,
      [e.target.name]: e.target.value,
    }));
  };

  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <h2 className="text-lg font-semibold text-foreground">Quick Analyze</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Manually trigger analysis for a GitHub pull request
      </p>

      <form onSubmit={handleSubmit} className="mt-4 space-y-4">
        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <label
              htmlFor="owner"
              className="block text-sm font-medium text-muted-foreground"
            >
              Owner
            </label>
            <input
              type="text"
              id="owner"
              name="owner"
              value={formData.owner}
              onChange={handleChange}
              placeholder="octocat"
              required
              className="mt-1 block w-full rounded-md border border-border bg-secondary px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
          
          <div>
            <label
              htmlFor="repo"
              className="block text-sm font-medium text-muted-foreground"
            >
              Repository
            </label>
            <input
              type="text"
              id="repo"
              name="repo"
              value={formData.repo}
              onChange={handleChange}
              placeholder="my-c-project"
              required
              className="mt-1 block w-full rounded-md border border-border bg-secondary px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
          
          <div>
            <label
              htmlFor="pr_number"
              className="block text-sm font-medium text-muted-foreground"
            >
              PR Number
            </label>
            <input
              type="number"
              id="pr_number"
              name="pr_number"
              value={formData.pr_number}
              onChange={handleChange}
              placeholder="123"
              min="1"
              required
              className="mt-1 block w-full rounded-md border border-border bg-secondary px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
        </div>

        {error && (
          <p className="text-sm text-status-failed">{error}</p>
        )}

        <button
          type="submit"
          disabled={isLoading}
          className="flex items-center gap-2 rounded-md bg-foreground px-4 py-2 text-sm font-medium text-background transition-colors hover:bg-foreground/90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isLoading ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Starting...
            </>
          ) : (
            <>
              <Play className="h-4 w-4" />
              Start Analysis
            </>
          )}
        </button>
      </form>
    </div>
  );
}
