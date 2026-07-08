"use client";

import Link from "next/link";
import useSWR from "swr";
import { GitBranch, Lock } from "lucide-react";
import { fetcher } from "@/lib/api";
import type { RepoListResponse } from "@/lib/api";

function timeAgo(iso?: string) {
  if (!iso) return null;
  const diffMs = Date.now() - new Date(iso).getTime();
  const days = Math.floor(diffMs / (1000 * 60 * 60 * 24));
  if (days <= 0) return "updated today";
  if (days === 1) return "updated 1 day ago";
  return `updated ${days} days ago`;
}

function RepoCardSkeleton() {
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="h-4 w-2/3 animate-pulse rounded bg-secondary" />
      <div className="mt-3 h-3 w-full animate-pulse rounded bg-secondary" />
      <div className="mt-2 h-3 w-4/5 animate-pulse rounded bg-secondary" />
      <div className="mt-4 h-3 w-1/3 animate-pulse rounded bg-secondary" />
    </div>
  );
}

export function RecentRepos() {
  const { data, isLoading } = useSWR<RepoListResponse>(
    "/api/me/repos",
    fetcher,
    { revalidateOnFocus: false }
  );

  const repos = data?.repos ?? [];

  return (
    <section>
      <h3 className="mb-3 text-sm font-bold uppercase tracking-wide text-muted-foreground">
        Recent repositories
      </h3>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {isLoading &&
          Array.from({ length: 3 }).map((_, i) => <RepoCardSkeleton key={i} />)}

        {!isLoading &&
          repos.slice(0, 9).map((repo) => (
            <Link
              key={repo.full_name}
              href={`/search?owner=${encodeURIComponent(
                repo.owner
              )}&repo=${encodeURIComponent(repo.name)}`}
              className="group flex flex-col rounded-xl border border-border bg-card p-4 transition-colors hover:border-border-strong hover:bg-secondary/40"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2">
                  <GitBranch className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <span className="truncate text-sm font-medium text-foreground">
                    {repo.full_name}
                  </span>
                </div>
                {repo.private && (
                  <Lock className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                )}
              </div>

              <p className="mt-2 line-clamp-2 min-h-[2.5rem] text-sm text-muted-foreground">
                {repo.description || "No description provided."}
              </p>

              {timeAgo(repo.pushed_at) && (
                <p className="mt-3 text-xs text-muted-foreground/70">
                  {timeAgo(repo.pushed_at)}
                </p>
              )}
            </Link>
          ))}

        {!isLoading && repos.length === 0 && (
          <p className="col-span-full rounded-xl border border-dashed border-border p-4 text-sm text-muted-foreground">
            No repositories found for your GitHub account.
          </p>
        )}
      </div>
    </section>
  );
}