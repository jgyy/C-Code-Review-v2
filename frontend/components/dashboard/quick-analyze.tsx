"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import type { OpenPullRequestsResponse } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Loader2, Play, Search, Check, GitPullRequest } from "lucide-react";

const PR_URL_PATTERN =
  /^https?:\/\/github\.com\/([^/]+)\/([^/]+)\/pull\/(\d+)/;

function parsePrUrl(url: string) {
  const match = url.trim().match(PR_URL_PATTERN);
  if (!match) return null;
  const [, owner, repo, prNumber] = match;
  return { owner, repo, pr_number: prNumber };
}

// Small delay before firing the PR lookup so we don't fetch on every
// keystroke while the user is still typing the owner/repo.
const REPO_DEBOUNCE_MS = 400;

function initials(login: string) {
  return login.slice(0, 2).toUpperCase();
}

function timeAgo(iso?: string) {
  if (!iso) return null;
  const diffMs = Date.now() - new Date(iso).getTime();
  const days = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  if (days <= 0) return "today";
  if (days === 1) return "1 day ago";
  return `${days} days ago`;
}

function PrAvatar({ login, url }: { login: string; url?: string }) {
  const [failed, setFailed] = useState(false);

  if (!url || failed) {
    return (
      <div
        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-secondary text-[11px] font-medium text-foreground"
        aria-hidden="true"
      >
        {initials(login)}
      </div>
    );
  }

  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={`${url}${url.includes("?") ? "&" : "?"}s=64`}
      alt=""
      width={28}
      height={28}
      loading="lazy"
      onError={() => setFailed(true)}
      className="h-7 w-7 shrink-0 rounded-full"
    />
  );
}

export function QuickAnalyze() {
  const router = useRouter();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"browse" | "fields" | "url">("browse");

  const [formData, setFormData] = useState({
    owner: "",
    repo: "",
    pr_number: "",
  });
  const [prUrl, setPrUrl] = useState("");
  const [postComment, setPostComment] = useState(true);

  // --- Browse PRs mode (new) --------------------------------------------
  const [prSearch, setPrSearch] = useState("");
  const [selectedPr, setSelectedPr] = useState<number | null>(null);
  const [debouncedOwner, setDebouncedOwner] = useState("");
  const [debouncedRepo, setDebouncedRepo] = useState("");

  useEffect(() => {
    const handle = setTimeout(() => {
      setDebouncedOwner(formData.owner.trim());
      setDebouncedRepo(formData.repo.trim());
    }, REPO_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [formData.owner, formData.repo]);

  const shouldFetchPulls =
    mode === "browse" && debouncedOwner.length > 0 && debouncedRepo.length > 0;

  const {
    data: pullsData,
    error: pullsError,
    isLoading: pullsLoading,
  } = useSWR<OpenPullRequestsResponse>(
    shouldFetchPulls
      ? `/api/repos/${encodeURIComponent(debouncedOwner)}/${encodeURIComponent(debouncedRepo)}/pulls`
      : null,
    fetcher,
    { revalidateOnFocus: false }
  );

  const filteredPulls = useMemo(() => {
    const pulls = pullsData?.pull_requests ?? [];
    const query = prSearch.trim().toLowerCase();
    if (!query) return pulls;
    return pulls.filter((pr) => {
      return (
        String(pr.number).includes(query) ||
        pr.title.toLowerCase().includes(query) ||
        pr.author.toLowerCase().includes(query)
      );
    });
  }, [pullsData, prSearch]);

  // Selection no longer belongs to the current repo's PR list (owner/repo
  // changed) — clear it so we don't submit a stale PR number.
  useEffect(() => {
    setSelectedPr(null);
  }, [debouncedOwner, debouncedRepo]);

  const handleSelectPr = (prNumber: number) => {
    setSelectedPr(prNumber);
    setFormData((prev) => ({ ...prev, pr_number: String(prNumber) }));
  };

  // --- Submit -------------------------------------------------------------

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

    if (mode === "browse" && !selectedPr) {
      setError("Select an open pull request from the list below.");
      return;
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
        Trigger analysis for a GitHub pull request
      </p>

      <div className="mt-4 inline-flex rounded-md border border-border bg-secondary p-1 text-sm">
        <button
          type="button"
          onClick={() => setMode("browse")}
          className={`rounded px-3 py-1 transition-colors ${
            mode === "browse"
              ? "bg-foreground text-background"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Browse PRs
        </button>
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
        {mode === "browse" && (
          <div className="space-y-3">
            <div className="grid gap-4 sm:grid-cols-2">
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
            </div>

            {shouldFetchPulls && (
              <>
                <div className="relative">
                  <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <input
                    type="text"
                    value={prSearch}
                    onChange={(e) => setPrSearch(e.target.value)}
                    placeholder="Search open PRs by number, title, or author"
                    className="mt-0 block w-full rounded-md border border-border bg-secondary py-2 pl-8 pr-3 text-sm text-foreground placeholder:text-muted-foreground/50 focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
                  />
                </div>

                <div className="max-h-72 overflow-y-auto rounded-md border border-border">
                  {pullsLoading && (
                    <div className="flex items-center gap-2 p-4 text-sm text-muted-foreground">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      Loading open pull requests...
                    </div>
                  )}

                  {pullsError && !pullsLoading && (
                    <p className="p-4 text-sm text-status-failed">
                      Couldn&apos;t load pull requests for {formData.owner}/
                      {formData.repo}. Check the owner and repo name.
                    </p>
                  )}

                  {!pullsLoading && !pullsError && filteredPulls.length === 0 && (
                    <p className="p-4 text-sm text-muted-foreground">
                      {pullsData?.pull_requests.length
                        ? "No open PRs match that search."
                        : "No open pull requests found for this repo."}
                    </p>
                  )}

                  {!pullsLoading &&
                    !pullsError &&
                    filteredPulls.map((pr, idx) => {
                      const isSelected = selectedPr === pr.number;
                      return (
                        <button
                          type="button"
                          key={pr.number}
                          onClick={() => handleSelectPr(pr.number)}
                          className={cn(
                            "flex w-full items-center gap-3 px-3 py-2.5 text-left text-sm transition-colors",
                            idx !== filteredPulls.length - 1 &&
                              "border-b border-border",
                            isSelected ? "bg-primary/10" : "hover:bg-secondary"
                          )}
                        >
                          <PrAvatar login={pr.author} url={pr.author_avatar_url} />
                          <span
                            className={cn(
                              "shrink-0 font-medium",
                              isSelected ? "text-primary" : "text-muted-foreground"
                            )}
                          >
                            #{pr.number}
                          </span>
                          <span className="min-w-0 flex-1">
                            <span className="block truncate font-medium text-foreground">
                              {pr.title}
                            </span>
                            <span
                              className={cn(
                                "block truncate text-xs",
                                isSelected ? "text-primary" : "text-muted-foreground"
                              )}
                            >
                              {pr.author}
                              {timeAgo(pr.created_at)
                                ? ` · opened ${timeAgo(pr.created_at)}`
                                : ""}
                            </span>
                          </span>
                          {isSelected && (
                            <Check className="h-4 w-4 shrink-0 text-primary" />
                          )}
                        </button>
                      );
                    })}
                </div>
              </>
            )}

            {!shouldFetchPulls && (
              <p className="flex items-center gap-2 rounded-md border border-dashed border-border p-3 text-sm text-muted-foreground">
                <GitPullRequest className="h-4 w-4" />
                Enter an owner and repository to see its open pull requests.
              </p>
            )}
          </div>
        )}

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
        ) : null}

        {mode === "url" ? (
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
        ) : null}

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