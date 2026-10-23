import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatStrip } from "./StatStrip";
import { mockDashboardSummary } from "@/test/handlers";

/**
 * Spec-driven tests for F17's dashboard headline: realized accuracy is a
 * separately labelled stat and is never confused with the backtest median.
 */
describe("StatStrip: realized accuracy stat", () => {
  const measured = { ...mockDashboardSummary, median_wmape: 0.072, realized_wmape: 0.124, realized_runs: 3 };

  it("shows a labelled 'Realized WMAPE' stat when runs have been measured", () => {
    render(<StatStrip summary={measured} />);
    expect(screen.getByText("Realized WMAPE")).toBeInTheDocument();
    expect(screen.getByText("12.4%")).toBeInTheDocument();
  });

  it("keeps the backtest 'Median WMAPE' as a distinct stat with its own value", () => {
    render(<StatStrip summary={measured} />);
    expect(screen.getByText("Median WMAPE")).toBeInTheDocument();
    expect(screen.getByText("7.2%")).toBeInTheDocument();
  });

  it("does not average or blend the two numbers", () => {
    render(<StatStrip summary={measured} />);
    // (7.2 + 12.4) / 2 = 9.8
    expect(screen.queryByText("9.8%")).not.toBeInTheDocument();
  });

  it("mentions how many runs were measured", () => {
    render(<StatStrip summary={measured} />);
    expect(screen.getByText(/3 runs/)).toBeInTheDocument();
  });

  it("says 'Not measured yet' when no run has been measured", () => {
    render(<StatStrip summary={{ ...measured, realized_wmape: null, realized_runs: 0 }} />);
    expect(screen.getByText("Not measured yet")).toBeInTheDocument();
  });

  it("does not show a realized score or a zero when nothing was measured", () => {
    render(<StatStrip summary={{ ...measured, realized_wmape: null, realized_runs: 0 }} />);
    expect(screen.queryByText("12.4%")).not.toBeInTheDocument();
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
    expect(screen.queryByText("0.0%")).not.toBeInTheDocument();
  });

  it("still shows the backtest median when nothing was measured against actuals", () => {
    render(<StatStrip summary={{ ...measured, realized_wmape: null, realized_runs: 0 }} />);
    expect(screen.getByText("7.2%")).toBeInTheDocument();
  });
});
