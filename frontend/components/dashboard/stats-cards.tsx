"use client";

import { cn } from "@/lib/utils";
import { 
  Activity, 
  CheckCircle, 
  Clock, 
  Database 
} from "lucide-react";

interface StatsCardsProps {
  stats: {
    totalJobs: number;
    successRate: number;
    avgAnalysisTime: number;
    cacheHitRate: number;
  };
}

export function StatsCards({ stats }: StatsCardsProps) {
  const cards = [
    {
      title: "Total Jobs",
      value: stats.totalJobs.toLocaleString(),
      icon: Activity,
      description: "All-time analyses",
    },
    {
      title: "Success Rate",
      value: `${stats.successRate.toFixed(1)}%`,
      icon: CheckCircle,
      description: "Completed without errors",
      color: stats.successRate >= 95 ? "text-status-completed" : stats.successRate >= 80 ? "text-status-pending" : "text-status-failed",
    },
    {
      title: "Avg Analysis Time",
      value: `${stats.avgAnalysisTime.toFixed(1)}s`,
      icon: Clock,
      description: "Per pull request",
    },
    {
      title: "Cache Hit Rate",
      value: `${stats.cacheHitRate.toFixed(1)}%`,
      icon: Database,
      description: "AST cache efficiency",
      color: stats.cacheHitRate >= 70 ? "text-status-completed" : stats.cacheHitRate >= 40 ? "text-status-pending" : "text-muted-foreground",
    },
  ];

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {cards.map((card) => (
        <div
          key={card.title}
          className="rounded-lg border border-border bg-card p-6"
        >
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium text-muted-foreground">
              {card.title}
            </span>
            <card.icon className="h-5 w-5 text-muted-foreground/50" />
          </div>
          <div className="mt-2">
            <span className={cn("text-3xl font-semibold", card.color)}>
              {card.value}
            </span>
          </div>
          <p className="mt-1 text-xs text-muted-foreground/70">
            {card.description}
          </p>
        </div>
      ))}
    </div>
  );
}
