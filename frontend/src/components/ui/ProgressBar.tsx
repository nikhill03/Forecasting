import { cn } from "@/lib/utils";

interface ProgressBarProps {
  value: number;
  label?: string;
  className?: string;
}

export function ProgressBar({ value, label, className }: ProgressBarProps) {
  const clamped = Math.max(0, Math.min(100, value));

  return (
    <div className={cn("w-full", className)}>
      {label && (
        <div className="mb-1.5 flex items-center justify-between text-xs">
          <span className="text-text-muted">{label}</span>
          <span className="font-mono text-text">{clamped}%</span>
        </div>
      )}
      <div
        role="progressbar"
        aria-valuenow={clamped}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={label ?? "Progress"}
        className="h-1.5 w-full overflow-hidden rounded-full bg-bg-raised"
      >
        <div
          className="h-full rounded-full bg-accent transition-all duration-300 ease-out"
          style={{ width: `${clamped}%` }}
        />
      </div>
    </div>
  );
}