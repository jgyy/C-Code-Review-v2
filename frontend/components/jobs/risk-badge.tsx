import { cn } from "@/lib/utils";

type RiskLevel = "low" | "medium" | "high" | "critical";

interface RiskBadgeProps {
  level: RiskLevel;
  size?: "sm" | "md";
}

const riskConfig: Record<RiskLevel, { label: string; className: string }> = {
  low: {
    label: "Low Risk",
    className: "bg-risk-low/20 text-risk-low border-risk-low/30",
  },
  medium: {
    label: "Medium",
    className: "bg-risk-medium/20 text-risk-medium border-risk-medium/30",
  },
  high: {
    label: "High Risk",
    className: "bg-risk-high/20 text-risk-high border-risk-high/30",
  },
  critical: {
    label: "Critical",
    className: "bg-risk-critical/20 text-risk-critical border-risk-critical/30",
  },
};

export function RiskBadge({ level, size = "md" }: RiskBadgeProps) {
  const config = riskConfig[level];

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border font-medium",
        config.className,
        size === "sm" ? "px-2 py-0.5 text-xs" : "px-2.5 py-1 text-sm"
      )}
    >
      {config.label}
    </span>
  );
}
