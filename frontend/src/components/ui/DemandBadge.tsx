import type { DemandType } from "@/types/api";
import { cn } from "@/lib/utils";

interface DemandBadgeProps {
  type: DemandType;
  adi?: number;
  cv2?: number;
  size?: "sm" | "md";
  showLabel?: boolean;
  className?: string;
}

const ICON_PATHS: Record<DemandType, string> = {
  Smooth: "M2 8 L14 8",
  Erratic: "M2 11 L5 4 L8 11 L11 4 L14 11",
  Intermittent: "M2 8 L4 8 M7 8 L9 8 M12 8 L14 8",
  Lumpy: "M2 11 L4 5 M6 9 L8 4 M10 11 L12 6 M14 9 L14 9",
};

const COLOR_CLASSES: Record<DemandType, { text: string; bg: string; border: string }> = {
  Smooth: {
    text: "text-demand-smooth",
    bg: "bg-demand-smooth/10",
    border: "border-demand-smooth/30",
  },
  Erratic: {
    text: "text-demand-erratic",
    bg: "bg-demand-erratic/10",
    border: "border-demand-erratic/30",
  },
  Intermittent: {
    text: "text-demand-intermittent",
    bg: "bg-demand-intermittent/10",
    border: "border-demand-intermittent/30",
  },
  Lumpy: {
    text: "text-demand-lumpy",
    bg: "bg-demand-lumpy/10",
    border: "border-demand-lumpy/30",
  },
};

export function DemandBadge({
  type,
  adi,
  cv2,
  size = "md",
  showLabel = true,
  className,
}: DemandBadgeProps) {
  const colors = COLOR_CLASSES[type];
  const iconSize = size === "sm" ? 12 : 16;

  const description =
    adi !== undefined && cv2 !== undefined
      ? `${type} demand pattern, average demand interval ${adi.toFixed(2)}, coefficient of variation squared ${cv2.toFixed(2)}`
      : `${type} demand pattern`;

  return (
    <span
      role="img"
      aria-label={description}
      title={description}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5",
        colors.bg,
        colors.border,
        size === "sm" ? "text-2xs" : "text-xs",
        className,
      )}
    >
      <svg
        width={iconSize}
        height={iconSize}
        viewBox="0 0 16 16"
        fill="none"
        aria-hidden="true"
        className={colors.text}
      >
        <path
          d={ICON_PATHS[type]}
          stroke="currentColor"
          strokeWidth="1.75"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      {showLabel && (
        <span className={cn("font-medium", colors.text)}>{type}</span>
      )}
    </span>
  );
}