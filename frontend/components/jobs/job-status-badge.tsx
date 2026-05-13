import { cn } from "@/lib/utils";

type JobStatusType = "pending" | "processing" | "completed" | "failed";

interface JobStatusBadgeProps {
  status: JobStatusType;
  size?: "sm" | "md";
}

const statusConfig: Record<JobStatusType, { label: string; className: string }> = {
  pending: {
    label: "Pending",
    className: "bg-status-pending/20 text-status-pending border-status-pending/30",
  },
  processing: {
    label: "Processing",
    className: "bg-status-processing/20 text-status-processing border-status-processing/30",
  },
  completed: {
    label: "Completed",
    className: "bg-status-completed/20 text-status-completed border-status-completed/30",
  },
  failed: {
    label: "Failed",
    className: "bg-status-failed/20 text-status-failed border-status-failed/30",
  },
};

export function JobStatusBadge({ status, size = "md" }: JobStatusBadgeProps) {
  const config = statusConfig[status];

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border font-medium",
        config.className,
        size === "sm" ? "px-2 py-0.5 text-xs" : "px-2.5 py-1 text-sm"
      )}
    >
      <span
        className={cn(
          "mr-1.5 h-1.5 w-1.5 rounded-full",
          status === "pending" && "bg-status-pending",
          status === "processing" && "animate-pulse bg-status-processing",
          status === "completed" && "bg-status-completed",
          status === "failed" && "bg-status-failed"
        )}
      />
      {config.label}
    </span>
  );
}
