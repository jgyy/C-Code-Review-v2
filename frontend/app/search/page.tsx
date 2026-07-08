"use client";

import { Suspense } from "react";
import { QuickAnalyze } from "@/components/dashboard/quick-analyze";

// Wrapped in Suspense because QuickAnalyze reads useSearchParams() to
// prefill from links like /search?owner=x&repo=y or ?pr_number=123.
export default function SearchPage() {
  return (
    <div className="space-y-4">
      <Suspense fallback={null}>
        <QuickAnalyze />
      </Suspense>
    </div>
  );
}