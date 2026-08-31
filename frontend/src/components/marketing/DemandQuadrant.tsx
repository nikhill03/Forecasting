import { cn } from "@/lib/utils";

interface DemandQuadrantProps {
  className?: string;
}

interface ScatterPoint {
  x: number;
  y: number;
  r: number;
}

// Fixed, hand-placed scatter — not random per render, so the illustration
// is stable and the staggered entrance animation is reproducible.
const SMOOTH: ScatterPoint[] = [
  { x: 62, y: 208, r: 5 },
  { x: 88, y: 226, r: 4 },
  { x: 44, y: 190, r: 3.5 },
  { x: 104, y: 200, r: 4.5 },
];
const ERRATIC: ScatterPoint[] = [
  { x: 58, y: 70, r: 5 },
  { x: 92, y: 46, r: 4 },
  { x: 40, y: 92, r: 4.5 },
];
const INTERMITTENT: ScatterPoint[] = [
  { x: 240, y: 214, r: 4 },
  { x: 274, y: 232, r: 3.5 },
  { x: 300, y: 196, r: 4.5 },
];
const LUMPY: ScatterPoint[] = [
  { x: 246, y: 64, r: 6 },
  { x: 288, y: 84, r: 5 },
  { x: 264, y: 40, r: 4 },
  { x: 310, y: 52, r: 4.5 },
];

const GROUPS: { points: ScatterPoint[]; colorClass: string }[] = [
  { points: SMOOTH, colorClass: "text-demand-smooth" },
  { points: ERRATIC, colorClass: "text-demand-erratic" },
  { points: INTERMITTENT, colorClass: "text-demand-intermittent" },
  { points: LUMPY, colorClass: "text-demand-lumpy" },
];

/**
 * The ADI × CV² demand classification chart, rendered as the hero's
 * visual thesis: this is what the platform actually does to every
 * series it's handed, before it ever picks a model.
 */
export function DemandQuadrant({ className }: DemandQuadrantProps) {
  let dotIndex = 0;

  return (
    <svg
      viewBox="0 0 340 260"
      fill="none"
      role="img"
      aria-label="Scatter chart showing demand series classified into four quadrants by order interval and demand variability: Smooth, Erratic, Intermittent and Lumpy"
      className={cn("w-full", className)}
    >
      <line x1="170" y1="10" x2="170" y2="240" className="stroke-border" strokeWidth="1" strokeDasharray="3 4" />
      <line x1="20" y1="128" x2="330" y2="128" className="stroke-border" strokeWidth="1" strokeDasharray="3 4" />

      <line x1="20" y1="240" x2="330" y2="240" className="stroke-border-strong" strokeWidth="1.25" />
      <line x1="20" y1="10" x2="20" y2="240" className="stroke-border-strong" strokeWidth="1.25" />

      <text x="330" y="254" textAnchor="end" className="fill-text-subtle font-mono text-[9px] uppercase tracking-wider">
        order interval →
      </text>
      <text x="26" y="16" textAnchor="start" className="fill-text-subtle font-mono text-[9px] uppercase tracking-wider">
        ↑ variability
      </text>

      <text x="30" y="226" className="fill-demand-smooth font-display text-[11px] font-semibold tracking-wide">SMOOTH</text>
      <text x="30" y="36" className="fill-demand-erratic font-display text-[11px] font-semibold tracking-wide">ERRATIC</text>
      <text x="234" y="226" className="fill-demand-intermittent font-display text-[11px] font-semibold tracking-wide">INTERMITTENT</text>
      <text x="270" y="36" className="fill-demand-lumpy font-display text-[11px] font-semibold tracking-wide">LUMPY</text>

      {GROUPS.map((group) =>
        group.points.map((p) => {
          const delay = dotIndex * 70;
          dotIndex += 1;
          return (
            <circle
              key={`${p.x}-${p.y}`}
              cx={p.x}
              cy={p.y}
              r={p.r}
              fill="currentColor"
              className={cn(group.colorClass, "origin-center animate-scale-in")}
              style={{ animationDelay: `${delay}ms`, transformBox: "fill-box" }}
            />
          );
        }),
      )}
    </svg>
  );
}
