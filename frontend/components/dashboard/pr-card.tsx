"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Play, GitPullRequest } from "lucide-react";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import type { PullRequestCard as PullRequestCardData } from "@/lib/api";

function initials(login: string) {
  return login.slice(0, 2).toUpperCase();
}

function timeAgo(iso?: string) {
  if (!iso) return null;
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diffMs / (1000 * 60));
  if (mins < 60) return `${Math.max(mins, 1)}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

interface PrCardProps {
  pr: PullRequestCardData;
  badge?: { label: string; tone: "accent" | "warning" };
}

export function PrCard({ pr, badge }: PrCardProps) {
  const router = useRouter();
  const [isStarting, setIsStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [owner, repo] = pr.repo_full_name.split("/");

  const handleAnalyze = async () => {
    setError(null);
    setIsStarting(true);
    try {
      const result = await api.analyze({
        owner,
        repo,
        pr_number: pr.number,
        post_comment: true,
      });
      router.push(`/jobs/${result.job_id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start analysis");
      setIsStarting(false);
    }
  };

  return (
    <div className="rounded-xl border border-border bg-card p-3">
      <div className="flex items-start justify-between gap-2">
        <span className="truncate text-xs text-muted-foreground">
          {pr.repo_full_name}
        </span>
        {badge && (
          <span
            className={cn(
              "shrink-0 rounded px-2 py-0.5 text-[11px]",
              badge.tone === "accent"
                ? "bg-primary/10 text-primary"
                : "bg-status-pending/10 text-status-pending"
            )}
          >
            {badge.label}
          </span>
        )}
      </div>

      <p className="mt-1.5 line-clamp-2 text-sm font-medium text-foreground">
        #{pr.number} {pr.title}
      </p>

      {pr.labels.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {pr.labels.slice(0, 3).map((label) => (
            <span
              key={label}
              className="rounded bg-secondary px-1.5 py-0.5 text-[10px] text-muted-foreground"
            >
              {label}
            </span>
          ))}
        </div>
      )}

      <div className="mt-2.5 flex items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          {pr.author_avatar_url ? (
            <img
              src={`${pr.author_avatar_url}${
                pr.author_avatar_url.includes("?") ? "&" : "?"
              }s=32`}
              alt=""
              width={16}
              height={16}
              loading="lazy"
              className="h-4 w-4 shrink-0 rounded-full"
            />
          ) : (
            <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-secondary text-[8px] font-medium">
              {initials(pr.author)}
            </span>
          )}
          <span className="truncate">
            {pr.author}
            {timeAgo(pr.updated_at) ? ` · ${timeAgo(pr.updated_at)}` : ""}
          </span>
        </span>

        <button
          type="button"
          onClick={handleAnalyze}
          disabled={isStarting}
          className="flex shrink-0 items-center gap-1 rounded-md border border-border px-2 py-1 text-xs font-medium transition-colors hover:bg-secondary disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Play className="h-3 w-3" />
          {isStarting ? "Starting..." : "Analyze"}
        </button>
      </div>

      {error && <p className="mt-2 text-xs text-status-failed">{error}</p>}
    </div>
  );
}

export function PrCardSkeleton() {
  return (
    <div className="rounded-xl border border-border bg-card p-3">
      <div className="h-3 w-2/5 animate-pulse rounded bg-secondary" />
      <div className="mt-2 h-4 w-4/5 animate-pulse rounded bg-secondary" />
      <div className="mt-3 h-3 w-1/3 animate-pulse rounded bg-secondary" />
    </div>
  );
}

export function EmptyState({
  icon: Icon = GitPullRequest,
  message,
}: {
  icon?: typeof GitPullRequest;
  message: string;
}) {
  return (
    <p className="flex items-center gap-2 rounded-xl border border-dashed border-border p-4 text-sm text-muted-foreground">
      <Icon className="h-4 w-4 shrink-0" />
      {message}
    </p>
  );
}