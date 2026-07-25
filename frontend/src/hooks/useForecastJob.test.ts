import { describe, expect, it } from "vitest";
import { computeRefetchInterval } from "./useForecastJob";

describe("computeRefetchInterval", () => {
  it("returns 2000 before the 30s tier switch", () => {
    expect(computeRefetchInterval("running", 0, 29_000)).toBe(2000);
  });

  it("returns 5000 after the 30s tier switch", () => {
    expect(computeRefetchInterval("running", 0, 31_000)).toBe(5000);
  });

  it("switches to the slow tier at exactly 30000ms elapsed (strict less-than)", () => {
    expect(computeRefetchInterval("running", 0, 30_000)).toBe(5000);
  });

  it("returns false for terminal states regardless of elapsed time", () => {
    expect(computeRefetchInterval("success", 0, 1000)).toBe(false);
    expect(computeRefetchInterval("failed", 0, 100_000)).toBe(false);
    expect(computeRefetchInterval("stopped", 0, 100_000)).toBe(false);
  });

  it("returns 2000 when polling hasn't started yet (no data fetched)", () => {
    expect(computeRefetchInterval("pending", null, 1000)).toBe(2000);
  });

  it("returns 2000 for a non-terminal status with no elapsed time", () => {
    expect(computeRefetchInterval("running", 5000, 5000)).toBe(2000);
  });

  it("returns 2000 when status is undefined (query hasn't resolved yet)", () => {
    // Mirrors useForecastProgress's actual call site: query.state.data?.status
    // is `undefined`, not a string, until the first fetch resolves -- the
    // `if (status && ...)` terminal-state guard must short-circuit on
    // `undefined` rather than throwing or mis-reading it as terminal.
    expect(computeRefetchInterval(undefined, null, 1000)).toBe(2000);
  });
});
