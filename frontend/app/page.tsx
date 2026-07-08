"use client";

import { DashboardHeader } from "@/components/dashboard/dashboard-header";
import { PrSection } from "@/components/dashboard/pr-section";
import { RecentRepos } from "@/components/dashboard/recent-repos";

export default function DashboardPage() {
  return (
    <div className="space-y-8">
      {/* <DashboardHeader /> */}

      <PrSection
        title="Review requests"
        endpoint="/api/me/pulls/review-requested"
        badge={{ label: "Review requested", tone: "accent" }}
        emptyMessage="No open PRs are waiting on your review."
        skeletonCount={2}
      />

      <PrSection
        title="My open pull requests"
        endpoint="/api/me/pulls/authored"
        emptyMessage="You don't have any open pull requests right now."
        skeletonCount={3}
      />

      <PrSection
        title="Recently updated team PRs"
        endpoint="/api/me/pulls/recent-team"
        emptyMessage="No recent activity from your organizations."
        skeletonCount={3}
        hideWhenEmpty
      />

      <RecentRepos />
    </div>
  );
}