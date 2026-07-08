"use client";

import useSWR from "swr";
import { fetcher } from "@/lib/api";
import type { PullRequestCardsResponse } from "@/lib/api";
import { PrCard, PrCardSkeleton, EmptyState } from "./pr-card";

interface PrSectionProps {
  title: string;
  endpoint: string;
  badge?: { label: string; tone: "accent" | "warning" };
  emptyMessage: string;
  skeletonCount?: number;
  // Sections with no meaningful content (e.g. user isn't in any orgs) can
  // hide themselves entirely rather than show an empty state.
  hideWhenEmpty?: boolean;
}

export function PrSection({
  title,
  endpoint,
  badge,
  emptyMessage,
  skeletonCount = 2,
  hideWhenEmpty = false,
}: PrSectionProps) {
  const { data, error, isLoading } = useSWR<PullRequestCardsResponse>(
    endpoint,
    fetcher,
    { revalidateOnFocus: false, refreshInterval: 60000 }
  );

  const pulls = data?.pull_requests ?? [];

  if (hideWhenEmpty && !isLoading && !error && pulls.length === 0) {
    return null;
  }

  return (
    <section>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-bold uppercase tracking-wide text-muted-foreground">
          {title}
          {!isLoading && !error && pulls.length > 0 ? ` · ${pulls.length}` : ""}
        </h3>
      </div>

      {error && (
        <EmptyState message="Couldn't load this section. Try refreshing." />
      )}

      {isLoading && !error && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: skeletonCount }).map((_, i) => (
            <PrCardSkeleton key={i} />
          ))}
        </div>
      )}

      {!isLoading && !error && pulls.length === 0 && (
        <EmptyState message={emptyMessage} />
      )}

      {!isLoading && !error && pulls.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {pulls.map((pr) => (
            <PrCard key={`${pr.repo_full_name}-${pr.number}`} pr={pr} badge={badge} />
          ))}
        </div>
      )}
    </section>
  );
}