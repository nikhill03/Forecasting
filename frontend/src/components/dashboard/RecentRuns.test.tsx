import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { act } from "react";
import { Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { RecentRuns } from "./RecentRuns";
import { renderWithProviders } from "@/test/renderWithProviders";
import { mockDashboardSummary } from "@/test/handlers";
import { useForecastStore } from "@/store/forecastStore";

function renderRuns() {
  return renderWithProviders(
    <Routes>
      <Route
        path="/"
        element={<RecentRuns runs={mockDashboardSummary.recent_runs} />}
      />
      <Route path="/results" element={<p>Results page</p>} />
    </Routes>,
  );
}

describe("RecentRuns", () => {
  beforeEach(() => {
    act(() => useForecastStore.getState().reset());
  });

  it("titles a run by its name, falling back to the file name", () => {
    renderRuns();

    expect(screen.getByText("Q3 target")).toBeInTheDocument();
    expect(screen.getByText("retail-daily-smooth.csv")).toBeInTheDocument();
  });

  it("says how many more metrics a multi-metric run has", () => {
    renderRuns();
    expect(screen.getByText("Ridge +2")).toBeInTheDocument();
  });

  it("opens a successful run's results", async () => {
    const user = userEvent.setup();
    renderRuns();

    await user.click(
      screen.getByRole("button", { name: /retail-daily-smooth\.csv/i }),
    );

    expect(useForecastStore.getState().activeJobId).toBe("job-5");
    expect(await screen.findByText("Results page")).toBeInTheDocument();
  });

  it("does not make an unsuccessful run clickable", () => {
    renderRuns();
    expect(screen.getByText("Q3 target").closest("button")).toBeNull();
  });

  it("links to the full history", () => {
    renderRuns();
    expect(screen.getByRole("link", { name: /view all/i })).toHaveAttribute(
      "href",
      "/history",
    );
  });
});
