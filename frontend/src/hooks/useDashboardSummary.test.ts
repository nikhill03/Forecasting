import { describe, expect, it } from "vitest";
import { summaryRefetchInterval } from "./useDashboardSummary";
import {
  emptyDashboardSummary,
  mockActiveRun,
  mockDashboardSummary,
} from "@/test/handlers";

describe("summaryRefetchInterval", () => {
  it("does not poll before the first response", () => {
    expect(summaryRefetchInterval(undefined)).toBe(false);
  });

  it("does not poll when nothing is running", () => {
    expect(summaryRefetchInterval(mockDashboardSummary)).toBe(false);
    expect(summaryRefetchInterval(emptyDashboardSummary)).toBe(false);
  });

  it("polls while a run is in flight", () => {
    expect(
      summaryRefetchInterval({ ...mockDashboardSummary, active_runs: [mockActiveRun] }),
    ).toBe(10_000);
  });
});
