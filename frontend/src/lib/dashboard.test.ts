import { describe, expect, it } from "vitest";
import { foldModelWins } from "./dashboard";

const wins = (n: number) =>
  Array.from({ length: n }, (_, i) => ({ model_name: `M${i}`, wins: n - i }));

describe("foldModelWins", () => {
  it("returns nothing for no wins", () => {
    expect(foldModelWins([])).toEqual([]);
  });

  it("keeps every model when they fit", () => {
    const bars = foldModelWins(wins(6));
    expect(bars).toHaveLength(6);
    expect(bars.some((b) => b.isOther)).toBe(false);
  });

  it("folds the tail into one Other bar when they don't", () => {
    const bars = foldModelWins(wins(8)); // wins 8,7,6,5,4 kept; 3,2,1 folded
    expect(bars).toHaveLength(6);
    expect(bars.map((b) => b.label)).toEqual(["M0", "M1", "M2", "M3", "M4", "Other (3)"]);
    expect(bars[5]).toEqual({ label: "Other (3)", wins: 6, isOther: true });
  });

  it("keeps the input order", () => {
    expect(foldModelWins(wins(3)).map((b) => b.wins)).toEqual([3, 2, 1]);
  });
});
