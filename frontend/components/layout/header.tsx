"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSession, signOut } from "next-auth/react";
import { Code2 } from "lucide-react";
import { cn } from "@/lib/utils";

const navigation = [
  { name: "Dashboard", href: "/" },
  { name: "Search", href: "/search" },
  { name: "Jobs", href: "/jobs" },
];

export function Header() {
  const pathname = usePathname();
  const { data: session } = useSession();

  return (
    <header className="relative flex items-center justify-between border-b border-border px-6 py-3">
      <Link href="/" className="flex items-center gap-2.5">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-foreground">
          <Code2 className="h-4 w-4 text-background" />
        </div>
        <span className="text-[15px] font-medium tracking-tight text-foreground">
          C Review
        </span>
      </Link>

      {/* Center nav — glass pill switcher */}
      <nav className="absolute left-1/2 flex -translate-x-1/2 items-center gap-1 rounded-full border border-white/10 bg-white/5 p-1 backdrop-blur-md">
        {navigation.map((item) => {
          const isActive =
            pathname === item.href ||
            (item.href !== "/" && pathname.startsWith(item.href));

          return (
            <Link
              key={item.name}
              href={item.href}
              className={cn(
                "rounded-full px-4 py-1.5 text-sm transition-colors",
                isActive
                  ? "border border-white/10 bg-white/10 font-medium text-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]"
                  : "text-muted-foreground hover:bg-white/5 hover:text-foreground"
              )}
            >
              {item.name}
            </Link>
          );
        })}
      </nav>

      {session?.user && (
        <div className="flex items-center gap-3">
          <span className="text-sm text-muted-foreground">
            {session.user.login}
          </span>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={session.user.avatarUrl}
            alt={session.user.login ?? ""}
            width={32}
            height={32}
            className="h-8 w-8 rounded-full ring-1 ring-border"
          />
          <button
            onClick={() => signOut({ callbackUrl: "/login" })}
            className="text-xs text-muted-foreground transition-colors hover:text-foreground"
          >
            Sign out
          </button>
        </div>
      )}
    </header>
  );
}