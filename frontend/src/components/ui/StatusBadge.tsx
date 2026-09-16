import { cn } from "@/lib/utils";
import type { JobStatus } from "@/types/api";

const STATUS_STYLES: Record<JobStatus, string> = {
  success: "bg-success/10 text-success",
  failed: "bg-danger/10 text-danger",
  running: "bg-accent/10 text-accent",
  pending: "bg-info/10 text-info",
  stopped: "bg-bg-raised text-text-muted",
};

interface StatusBadgeProps {
  status: JobStatus;
  className?: string;
}

// The status word is always shown, so a run's state never depends on colour
// alone.
export function StatusBadge({ status, className }: StatusBadgeProps) {
  return (
    <span
      className={cn(
        "shrink-0 rounded-full px-2 py-0.5 text-2xs font-medium capitalize",
        STATUS_STYLES[status],
        className,
      )}
    >
      {status}
    </span>
  );
}
