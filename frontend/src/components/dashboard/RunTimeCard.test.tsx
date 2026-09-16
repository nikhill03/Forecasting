import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { act } from "react";
import { Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { RunTimeCard } from "./RunTimeCard";
import { renderWithProviders } from "@/test/renderWithProviders";
import { mockDashboardSummary } from "@/test/handlers";
import { useForecastStore } from "@/store/forecastStore";

function renderCard(medianSeconds: number | null, withSlowest = true) {
  return renderWithProviders(
    <Routes>
      <Route
        path="/"
        element={
          <RunTimeCard
            medianSeconds={medianSeconds}
            slowest={withSlowest ? mockDashboardSummary.slowest_runs : []}
          />
        }
      />
      <Route path="/results" element={<p>Results page</p>} />
    </Routes>,
  );
}

describe("RunTimeCard", () => {
  beforeEach(() => {
    act(() => useForecastStore.getState().reset());
  });

  it("leads with the median run time", () => {
    renderCard(237);
    expect(screen.getByText("3m 57s")).toBeInTheDocument();
  });

  it("lists the slowest runs with their durations", () => {
    renderCard(237);
    expect(screen.getByText("AirPassengers.csv")).toBeInTheDocument();
    expect(screen.getByText("6m 53s")).toBeInTheDocument();
    expect(screen.getByText("3m 59s")).toBeInTheDocument();
  });

  it("opens a slow run's results", async () => {
    const user = userEvent.setup();
    renderCard(237);

    await user.click(screen.getByRole("button", { name: /AirPassengers\.csv/i }));

    expect(useForecastStore.getState().activeJobId).toBe("job-2");
    expect(await screen.findByText("Results page")).toBeInTheDocument();
  });

  it("explains itself when no run has timing", () => {
    renderCard(null, false);
    expect(screen.getByText(/no completed runs with timing yet/i)).toBeInTheDocument();
  });
});
