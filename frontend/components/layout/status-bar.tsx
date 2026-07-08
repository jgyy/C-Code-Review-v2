"use client";

import { useState } from "react";
import { RefreshCw, Loader2 } from "lucide-react";

export function StatusBar() {
  const [isRefreshing, setIsRefreshing] = useState(false);

  const handleRefresh = () => {
    setIsRefreshing(true);
    window.location.reload();
  };

  return (
    <div className="fixed bottom-4 right-4 z-50 flex items-center gap-3 rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm backdrop-blur-md">
      <button
        onClick={handleRefresh}
        disabled={isRefreshing}
        className="flex items-center gap-1.5 text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
      >
        {isRefreshing ? (
          <Loader2 className="h-3.5 w-3.5 animate-spin" />
        ) : (
          <RefreshCw className="h-3.5 w-3.5" />
        )}
        Refresh
      </button>

      <div className="h-3.5 w-px bg-border" />

      <div className="flex items-center gap-1.5 text-muted-foreground">
        <span className="h-2 w-2 rounded-full bg-status-completed" />
        System online
      </div>
    </div>
  );
}