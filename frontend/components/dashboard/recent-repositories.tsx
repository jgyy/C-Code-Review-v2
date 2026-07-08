"use client";

import { GitBranch, RotateCw } from "lucide-react";

export interface RecentRepository {
  owner: string;
  repo: string;
  lastPrNumber?: number;
  lastAnalyzedAt?: string;
}

interface RecentRepositoriesProps {
  repositories: RecentRepository[];
  onSelect: (repository: RecentRepository) => void;
}

export function RecentRepositories({
  repositories,
  onSelect,
}: RecentRepositoriesProps) {
  return (
    <div className="rounded-lg border border-border bg-card">
      <div className="border-b border-border px-6 py-4">
        <h2 className="text-lg font-semibold text-foreground">
          Recent Repositories
        </h2>
      </div>

      {repositories.length === 0 ? (
        <div className="px-6 py-8 text-sm text-muted-foreground">
          Recent repositories will appear after analyses complete.
        </div>
      ) : (
        <div className="divide-y divide-border">
          {repositories.map((repository) => (
            <div
              key={`${repository.owner}/${repository.repo}`}
              className="flex items-center justify-between gap-4 px-6 py-4"
            >
              <div className="flex min-w-0 items-center gap-3">
                <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-md bg-secondary">
                  <GitBranch className="h-5 w-5 text-muted-foreground" />
                </div>
                <div className="min-w-0">
                  <p className="truncate font-medium text-foreground">
                    {repository.owner}/{repository.repo}
                  </p>
                  <p className="text-sm text-muted-foreground">
                    Last analyzed PR{" "}
                    {repository.lastPrNumber ? `#${repository.lastPrNumber}` : "—"}
                  </p>
                </div>
              </div>

              <button
                type="button"
                onClick={() => onSelect(repository)}
                className="flex flex-shrink-0 items-center gap-2 rounded-md border border-border px-3 py-2 text-sm font-medium text-foreground transition-colors hover:bg-secondary"
              >
                <RotateCw className="h-4 w-4" />
                Analyze
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
