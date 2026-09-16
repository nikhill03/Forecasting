import type { ModelWin } from "@/types/api";

export interface WinBar {
  label: string;
  wins: number;
  isOther: boolean;
}

export const MAX_WIN_BARS = 6;

/**
 * Up to `maxBars` models are shown individually. Past that, the leaders keep
 * their own bars and the rest fold into one "Other" bar at the bottom.
 * Folding a single model into "Other" would only hide its name, so a list that
 * fits is never folded.
 *
 * Expects `wins` already sorted (the API sends most wins first).
 */
export function foldModelWins(
  wins: readonly ModelWin[],
  maxBars = MAX_WIN_BARS,
): WinBar[] {
  const bars = wins.map((w) => ({
    label: w.model_name,
    wins: w.wins,
    isOther: false,
  }));
  if (bars.length <= maxBars) return bars;

  const kept = bars.slice(0, maxBars - 1);
  const rest = bars.slice(maxBars - 1);
  return [
    ...kept,
    {
      label: `Other (${rest.length})`,
      wins: rest.reduce((sum, bar) => sum + bar.wins, 0),
      isOther: true,
    },
  ];
}
