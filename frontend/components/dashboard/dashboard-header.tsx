"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Search } from "lucide-react";

// Matches, in order of preference:
// 1. Full PR URL:            https://github.com/owner/repo/pull/123
// 2. Shorthand with number:  owner/repo#123
// 3. Repo shorthand only:    owner/repo
const PR_URL_RE = /^https?:\/\/github\.com\/([^/]+)\/([^/]+)\/pull\/(\d+)/;
const SHORTHAND_WITH_NUMBER_RE = /^([^/\s]+)\/([^/\s#]+)#(\d+)$/;
const REPO_SHORTHAND_RE = /^([^/\s]+)\/([^/\s#]+)$/;

function parseSmartInput(raw: string) {
  const value = raw.trim();

  const urlMatch = value.match(PR_URL_RE);
  if (urlMatch) {
    const [, owner, repo, prNumber] = urlMatch;
    return { type: "pr" as const, owner, repo, pr_number: parseInt(prNumber, 10) };
  }

  const shorthandMatch = value.match(SHORTHAND_WITH_NUMBER_RE);
  if (shorthandMatch) {
    const [, owner, repo, prNumber] = shorthandMatch;
    return { type: "pr" as const, owner, repo, pr_number: parseInt(prNumber, 10) };
  }

  const repoMatch = value.match(REPO_SHORTHAND_RE);
  if (repoMatch) {
    const [, owner, repo] = repoMatch;
    return { type: "repo" as const, owner, repo };
  }

  return null;
}

export function DashboardHeader() {
  const router = useRouter();
  const [query, setQuery] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const parsed = parseSmartInput(query);

    if (!parsed) {
      // Fall through to manual entry — the free-text search box there
      // covers repo name search and anything the shorthand parser missed.
      router.push(`/search?q=${encodeURIComponent(query.trim())}`);
      return;
    }

    if (parsed.type === "pr") {
      router.push(
        `/search?owner=${encodeURIComponent(parsed.owner)}&repo=${encodeURIComponent(
          parsed.repo
        )}&pr_number=${parsed.pr_number}&autostart=1`
      );
    } else {
      router.push(
        `/search?owner=${encodeURIComponent(parsed.owner)}&repo=${encodeURIComponent(
          parsed.repo
        )}`
      );
    }
  };

  return (
    <form onSubmit={handleSubmit} className="relative max-w-xl">
      <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
      <input
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Paste a PR URL, owner/repo#123, or search a repo"
        className="block w-full rounded-md border border-border bg-secondary py-2 pl-8 pr-3 text-sm text-foreground placeholder:text-muted-foreground/50 focus:border-ring focus:outline-none focus:ring-1 focus:ring-ring"
      />
    </form>
  );
}