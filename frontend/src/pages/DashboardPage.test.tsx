import { screen } from "@testing-library/react";
import { delay, http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { DashboardPage } from "./DashboardPage";
import { renderWithProviders } from "@/test/renderWithProviders";
import { server } from "@/test/server";
import { mockActiveRun, mockDashboardSummary } from "@/test/handlers";

describe("DashboardPage", () => {
  it("shows the empty state, with both ways in, for an account with no runs", async () => {
    // The default handler returns an empty summary.
    renderWithProviders(<DashboardPage />);

    expect(await screen.findByText("Start a new forecast")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /upload dataset/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /try sample data/i })).toBeInTheDocument();
  });

  it("shows the user's own numbers once they have runs", async () => {
    server.use(
      http.get("*/api/v1/dashboard", () => HttpResponse.json(mockDashboardSummary)),
    );
    renderWithProviders(<DashboardPage />);

    expect(await screen.findByText("Recent runs")).toBeInTheDocument();
    expect(screen.getByText("90%")).toBeInTheDocument();
    expect(screen.getByText("Accuracy over time")).toBeInTheDocument();
    expect(screen.getByText("Demand mix")).toBeInTheDocument();
    expect(screen.getByText("+1 unclassified")).toBeInTheDocument();
    expect(screen.getByText("Which models win")).toBeInTheDocument();
    expect(screen.getByText("Run time")).toBeInTheDocument();
    expect(screen.queryByText("In progress")).not.toBeInTheDocument();
    expect(screen.queryByText("Start a new forecast")).not.toBeInTheDocument();
  });

  it("shows one placeholder instead of empty charts before any run succeeds", async () => {
    server.use(
      http.get("*/api/v1/dashboard", () =>
        HttpResponse.json({
          ...mockDashboardSummary,
          total_runs: 1,
          status_counts: { success: 0, failed: 1, stopped: 0, running: 0, pending: 0 },
          success_rate: 0,
          accuracy_trend: [],
          model_wins: [],
          median_run_seconds: null,
          slowest_runs: [],
        }),
      ),
    );
    renderWithProviders(<DashboardPage />);

    expect(await screen.findByText("Your charts will appear here")).toBeInTheDocument();
    expect(screen.getByText("Recent runs")).toBeInTheDocument();
    expect(screen.queryByText("Which models win")).not.toBeInTheDocument();
    expect(screen.queryByText("Accuracy over time")).not.toBeInTheDocument();
    expect(screen.queryByText("Run time")).not.toBeInTheDocument();
    expect(screen.queryByText("Demand mix")).not.toBeInTheDocument();
  });

  it("shows the in-progress panel only while a run is in flight", async () => {
    server.use(
      http.get("*/api/v1/dashboard", () =>
        HttpResponse.json({ ...mockDashboardSummary, active_runs: [mockActiveRun] }),
      ),
      http.get("*/api/v1/forecast/:jobId/progress", () =>
        HttpResponse.json({
          job_id: mockActiveRun.job_id,
          status: "running",
          progress: 55,
          message: "Stage 4/5: Evaluating Multivariate",
        }),
      ),
    );
    renderWithProviders(<DashboardPage />);

    expect(await screen.findByText("In progress")).toBeInTheDocument();
    expect(
      await screen.findByText("Stage 4/5: Evaluating Multivariate"),
    ).toBeInTheDocument();
  });

  it("never flashes the empty state at a user with runs while loading", async () => {
    server.use(
      http.get("*/api/v1/dashboard", async () => {
        await delay(50);
        return HttpResponse.json(mockDashboardSummary);
      }),
    );
    renderWithProviders(<DashboardPage />);

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByText("Start a new forecast")).not.toBeInTheDocument();
    expect(await screen.findByText("Recent runs")).toBeInTheDocument();
  });

  it("shows an error with a retry when the summary fails to load", async () => {
    server.use(
      http.get("*/api/v1/dashboard", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    renderWithProviders(<DashboardPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /couldn't load your dashboard/i,
    );
    expect(screen.getByRole("button", { name: /try again/i })).toBeInTheDocument();
    expect(screen.queryByText("Start a new forecast")).not.toBeInTheDocument();
  });
});
