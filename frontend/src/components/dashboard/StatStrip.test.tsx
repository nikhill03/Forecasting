import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { StatStrip } from "./StatStrip";
import { mockDashboardSummary } from "@/test/handlers";

describe("StatStrip", () => {
  it("shows total runs, success rate and median WMAPE", () => {
    render(<StatStrip summary={mockDashboardSummary} />);

    expect(screen.getByText("11")).toBeInTheDocument();
    expect(screen.getByText("90%")).toBeInTheDocument();
    expect(screen.getByText("7.2%")).toBeInTheDocument();
  });

  it("shows a dash rather than 0% when nothing has finished", () => {
    // null * 100 is 0 in JavaScript — a missing rate must not read as "0%".
    render(
      <StatStrip
        summary={{ ...mockDashboardSummary, success_rate: null, median_wmape: null }}
      />,
    );

    expect(screen.queryByText("0%")).not.toBeInTheDocument();
    expect(screen.queryByText("0.0%")).not.toBeInTheDocument();
    expect(screen.getAllByText("—")).toHaveLength(2);
  });

  it("labels the backtest median and the realized figure so they can't be confused", () => {
    render(<StatStrip summary={mockDashboardSummary} />);

    expect(screen.getByText("Median WMAPE")).toBeInTheDocument();
    expect(screen.getByText("Backtest")).toBeInTheDocument();
    expect(screen.getByText("Realized WMAPE")).toBeInTheDocument();
    expect(screen.getByText("12.4%")).toBeInTheDocument();
    expect(screen.getByText("Against actuals, 3 runs")).toBeInTheDocument();
  });

  it("says nothing has been measured yet instead of showing a score", () => {
    render(
      <StatStrip
        summary={{ ...mockDashboardSummary, realized_wmape: null, realized_runs: 0 }}
      />,
    );

    expect(screen.getByText("Not measured yet")).toBeInTheDocument();
    expect(screen.queryByText("12.4%")).not.toBeInTheDocument();
  });
});
