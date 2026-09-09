import type { ModelRunResult } from "@/types/api";

export type SortKey = "composite_score" | "wmape" | "rmse" | "mae";

/**
 * Orders a metric's model field for display.
 *
 * Two rules that aren't obvious from the signature:
 *  - The champion is always pinned first, regardless of sort key or
 *    direction. It is the headline the surrounding card already states;
 *    letting a sort bury it would make the two disagree.
 *  - Rows with no score for the active column sink to the bottom rather than
 *    sorting as zero. A model that failed has no score, not a perfect one.
 *
 * Lives here rather than beside the component so it can be imported by tests
 * without tripping react-refresh/only-export-components, and follows the
 * codebase's habit of hoisting non-trivial logic into a pure, directly
 * testable function (see computeRefetchInterval in hooks/useForecastJob.ts).
 */
export function sortLeaderboard(
  rows: readonly ModelRunResult[],
  key: SortKey,
  direction: "asc" | "desc",
): ModelRunResult[] {
  const factor = direction === "asc" ? 1 : -1;

  return [...rows].sort((a, b) => {
    if (a.is_champion !== b.is_champion) return a.is_champion ? -1 : 1;

    const av = a[key];
    const bv = b[key];
    const aMissing = av === null || av === undefined || Number.isNaN(av);
    const bMissing = bv === null || bv === undefined || Number.isNaN(bv);
    if (aMissing && bMissing) return a.model_name.localeCompare(b.model_name);
    if (aMissing) return 1;
    if (bMissing) return -1;

    if (av === bv) return a.model_name.localeCompare(b.model_name);
    return (av - bv) * factor;
  });
}
