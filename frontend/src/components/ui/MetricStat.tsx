import { cn } from "@/lib/utils";

interface MetricStatProps {
  label: string;
  value: string;
  trend?: "up" | "down" | "neutral";
  className?: string;
}

export function MetricStat({ label, value, trend, className }: MetricStatProps) {
  return (
    <div className={cn("flex flex-col gap-1", className)}>
      <span className="text-2xs uppercase tracking-[0.08em] text-text-subtle">
        {label}
      </span>
      <span
        className={cn(
          "font-mono text-xl font-semibold tracking-tight tabular-nums",
          trend === "up" && "text-success",
          trend === "down" && "text-danger",
          !trend && "text-text",
        )}
      >
        {value}
      </span>
    </div>
  );
}
