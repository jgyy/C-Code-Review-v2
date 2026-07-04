"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { Loader2, Play } from "lucide-react";

const PR_URL_PATTERN =
  /^https?:\/\/github\.com\/([^/]+)\/([^/]+)\/pull\/(\d+)/;

function parsePrUrl(url: string) {
  const match = url.trim().match(PR_URL_PATTERN);
  if (!match) return null;
  const [, owner, repo, prNumber] = match;
  return { owner, repo, pr_number: prNumber };
}

export function QuickAnalyze() {
  const router = useRouter();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"fields" | "url">("fields");

  const [formData, setFormData] = useState({
    owner: "",
    repo: "",
    pr_number: "",
  });
  const [prUrl, setPrUrl] = useState("");
  const [postComment, setPostComment] = useState(true);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    let owner = formData.owner;
    let repo = formData.repo;
    let prNumber = formData.pr_number;

    if (mode === "url") {
      const parsed = parsePrUrl(prUrl);
      if (!parsed) {
        setError(
          "Enter a valid GitHub PR URL, e.g. https://github.com/owner/repo/pull/123"
        );
        return;
      }
      ({ owner, repo, pr_number: prNumber } = parsed);
    }

    setIsLoading(true);
    try {
      const result = await api.analyze({
        owner,
        repo,
        pr_number: parseInt(prNumber, 10),
        post_comment: postComment,
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

      <div className="mt-4 inline-flex rounded-md border border-border bg-secondary p-1 text-sm">
        <button
          type="button"
          onClick={() => setMode("fields")}
          className={`rounded px-3 py-1 transition-colors ${
            mode === "fields"
              ? "bg-foreground text-background"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Fields
        </button>
        <button
          type="button"
          onClick={() => setMode("url")}
          className={`rounded px-3 py-1 transition-colors ${
            mode === "url"
              ? "bg-foreground text-background"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          PR URL
        </button>
      </div>

      <form onSubmit={handleSubmit} className="mt-4 space-y-4">
        {mode === "fields" ? (
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
        ) : (
          <div>
            <label
              htmlFor="pr_url"
              className="block text-sm font-medium text-muted-foreground"
            >
              Pull Request URL
            </label>
            <input
              type="url"
              id="pr_url"
              name="pr_url"
              value={prUrl}
              onChange={(e) => setPrUrl(e.target.value)}
              placeholder="https://github.com/octocat/my-c-project/pull/123"
              required
              className="mt-1 block w-full rounded-md border border-border bg-secondary px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
        )}

        <label className="flex items-center gap-2 text-sm text-muted-foreground">
          <input
            type="checkbox"
            checked={postComment}
            onChange={(e) => setPostComment(e.target.checked)}
            className="h-4 w-4 rounded border-border bg-secondary text-ring focus:ring-1 focus:ring-ring"
          />
          Post review as a comment on the GitHub PR
        </label>

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
