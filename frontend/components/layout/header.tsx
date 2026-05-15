"use client";

import { usePathname } from "next/navigation";
import { RefreshCw } from "lucide-react";
import { useSession, signOut } from "next-auth/react"

const pageTitles: Record<string, string> = {
  "/": "Dashboard",
  "/jobs": "Job Queue",
  "/history": "Review History",
  "/analytics": "Analytics",
  "/settings": "Settings",
};

export function Header() {
  const pathname = usePathname();
  const { data: session } = useSession()
  
  // Handle dynamic routes
  const getTitle = () => {
    if (pathname.startsWith("/jobs/") && pathname !== "/jobs") {
      return "Job Details";
    }
    return pageTitles[pathname] || "Dashboard";
  };

  return (
    <header className="border-b border-border px-6 py-3 flex items-center justify-between">
      <h1 className="text-xl font-semibold text-foreground">{getTitle()}</h1>
      
      <div className="flex items-center gap-4">
        <button
          onClick={() => window.location.reload()}
          className="flex items-center gap-2 rounded-md px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
        >
          <RefreshCw className="h-4 w-4" />
          Refresh
        </button>
        
        <div className="flex items-center gap-2">
          <div className="h-2 w-2 rounded-full bg-status-completed" />
          <span className="text-sm text-muted-foreground">System Online</span>
        </div>
      </div>
	 {session?.user && (
        <div className="flex items-center gap-3">
          <span className="text-sm text-muted-foreground">
            {session.user.login}
          </span>
          <img
            src={session.user.avatarUrl}
            alt={session.user.login}
            className="h-8 w-8 rounded-full ring-1 ring-border"
          />
          <button
            onClick={() => signOut({ callbackUrl: "/login" })}
            className="text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            Sign out
          </button>
        </div>
      )}

    </header>
  );
}

