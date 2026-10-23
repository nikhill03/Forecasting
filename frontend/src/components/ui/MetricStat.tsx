import { cn } from "@/lib/utils";

interface MetricStatProps {
  label: string;
  value: string;
  trend?: "up" | "down" | "neutral";
  hint?: string;
  className?: string;
}

export function MetricStat({ label, value, trend, hint, className }: MetricStatProps) {
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
      {hint && <span className="text-2xs text-text-subtle">{hint}</span>}
    </div>
  );
}
