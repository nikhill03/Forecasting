import { cn } from "@/lib/utils";

interface BrandMarkProps {
  className?: string;
}

/**
 * The four-quadrant glyph — a miniature of the ADI × CV² demand
 * classification chart every forecast in this product is plotted
 * against (Smooth / Erratic / Intermittent / Lumpy). Stands in for a
 * generic icon because it's literally what the platform does.
 */
export function BrandMark({ className }: BrandMarkProps) {
  return (
    <svg
      viewBox="0 0 20 20"
      fill="none"
      aria-hidden="true"
      className={cn("shrink-0", className)}
    >
      <rect x="1" y="1" width="18" height="18" rx="4" className="stroke-border-strong" strokeWidth="1.25" />
      <path d="M10 2.5V17.5M2.5 10H17.5" className="stroke-border-strong" strokeWidth="1" />
      <circle cx="6" cy="14" r="1.6" fill="currentColor" className="text-demand-smooth" />
      <circle cx="6" cy="6" r="1.6" fill="currentColor" className="text-demand-erratic" />
      <circle cx="14" cy="6" r="1.6" fill="currentColor" className="text-demand-lumpy" />
      <circle cx="14" cy="14" r="1.6" fill="currentColor" className="text-demand-intermittent" />
    </svg>
  );
}
