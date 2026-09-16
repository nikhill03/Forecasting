import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AccuracySparkline } from "./AccuracySparkline";
import { mockDashboardSummary } from "@/test/handlers";

const POINTS = mockDashboardSummary.accuracy_trend;

describe("AccuracySparkline", () => {
  it("explains itself when there are no scored runs", () => {
    render(<AccuracySparkline points={[]} />);
    expect(screen.getByText(/no completed runs with a score/i)).toBeInTheDocument();
  });

  it("draws a single run as a point without a line", () => {
    const { container } = render(<AccuracySparkline points={POINTS.slice(0, 1)} />);

    expect(container.querySelector("polyline")).toBeNull();
    expect(screen.getByTestId("sparkline-readout")).toHaveTextContent("12.0%");
    expect(screen.getByText(/run more forecasts to see a trend/i)).toBeInTheDocument();
  });

  it("drops the single-run hint once there is a trend", () => {
    render(<AccuracySparkline points={POINTS} />);
    expect(screen.queryByText(/run more forecasts to see a trend/i)).not.toBeInTheDocument();
  });

  it("draws a line and lists every value in a table", () => {
    const { container } = render(<AccuracySparkline points={POINTS} />);

    expect(container.querySelector("polyline")).not.toBeNull();
    // header row + one row per run
    expect(screen.getAllByRole("row")).toHaveLength(POINTS.length + 1);
  });

  it("reads out the latest run by default", () => {
    render(<AccuracySparkline points={POINTS} />);

    const readout = screen.getByTestId("sparkline-readout");
    expect(readout).toHaveTextContent("3.2%");
    expect(readout).toHaveTextContent("latest");
  });

  it("reads out the hovered run", async () => {
    const user = userEvent.setup();
    render(<AccuracySparkline points={POINTS} />);

    await user.hover(screen.getByLabelText(/WMAPE 12\.0%/));

    const readout = screen.getByTestId("sparkline-readout");
    expect(readout).toHaveTextContent("12.0%");
    expect(readout).not.toHaveTextContent("latest");
  });

  it("summarises the range for assistive tech", () => {
    render(<AccuracySparkline points={POINTS} />);
    expect(
      screen.getByRole("group", { name: /last 3 runs, from 12\.0% to 3\.2%/i }),
    ).toBeInTheDocument();
  });
});
