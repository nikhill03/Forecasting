import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { RealizedAccuracySection } from "./RealizedAccuracySection";
import { server } from "@/test/server";
import { renderWithProviders } from "@/test/renderWithProviders";
import { mockRealizedAwaiting, mockRealizedComplete } from "@/test/handlers";
import type { RealizedAccuracyResponse, RealizedMetric } from "@/types/api";

/**
 * Spec-driven tests for F17's RealizedAccuracySection
 * (.claude/specs/p2.5-forecast-accuracy-tracking.md, "Frontend Changes").
 * Independent of RealizedAccuracySection.test.tsx.
 */

// ECharts does not render in jsdom.
vi.mock("./RealizedChart", () => ({
  RealizedChart: () => <div data-testid="realized-chart" />,
}));

const awaiting = mockRealizedAwaiting.metrics[0] as RealizedMetric;
const measured = mockRealizedComplete.metrics[0] as RealizedMetric;

function respondWith(metric: RealizedMetric) {
  const body: RealizedAccuracyResponse = { job_id: "job-1", metrics: [metric] };
  server.use(http.get("*/api/v1/forecast/:jobId/realized", () => HttpResponse.json(body)));
}

function renderSection() {
  return renderWithProviders(
    <RealizedAccuracySection jobId="job-1" sheetName="Sheet1" metricName="units_sold" />,
  );
}

const scores = (over: Partial<NonNullable<RealizedMetric["model"]>> = {}) => ({
  wmape: 0.0909,
  mae: 10,
  bias: 0.06,
  matched_points: 10,
  actual_total: 1100,
  forecast_total: 1000,
  ...over,
});

describe("RealizedAccuracySection: awaiting_actuals", () => {
  it("shows the forecast period and the check button", async () => {
    renderSection();
    expect(await screen.findByText(/This forecast covers/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Check against newer data/i })).toBeInTheDocument();
  });

  it("shows no score of any kind", async () => {
    renderSection();
    await screen.findByText(/This forecast covers/);
    expect(screen.queryByText(/Realized WMAPE/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it("does not render the overlay chart", async () => {
    renderSection();
    await screen.findByText(/This forecast covers/);
    expect(screen.queryByTestId("realized-chart")).not.toBeInTheDocument();
  });
});

describe("RealizedAccuracySection: no_overlap", () => {
  const noOverlap: RealizedMetric = {
    ...awaiting,
    status: "no_overlap",
    actuals_last_date: "2024-11-30",
    upload_id: "upload-old",
    upload_file_name: "too-early.csv",
    evaluated_at: "2025-02-01T09:00:00Z",
  };

  it("names the file and says it ends before the forecast starts", async () => {
    respondWith(noOverlap);
    renderSection();
    expect(await screen.findByText(/too-early\.csv/)).toBeInTheDocument();
    expect(screen.getByText(/ends on/)).toBeInTheDocument();
    expect(screen.getByText(/before this forecast starts/)).toBeInTheDocument();
  });

  it("mentions the dates involved", async () => {
    respondWith(noOverlap);
    renderSection();
    const message = await screen.findByText(/before this forecast starts/);
    // Format is a presentation choice; accept ISO or a localised rendering of either date.
    expect(message.textContent).toMatch(/2024|Nov/);
    expect(message.textContent).toMatch(/2025|Jan/);
  });

  it("shows no score", async () => {
    respondWith(noOverlap);
    renderSection();
    await screen.findByText(/too-early\.csv/);
    expect(screen.queryByText(/Realized WMAPE/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/forecast dates measured/)).not.toBeInTheDocument();
  });
});

describe("RealizedAccuracySection: partial and complete", () => {
  it("shows Realized WMAPE under the heading 'How the forecast held up'", async () => {
    respondWith(measured);
    renderSection();
    expect(await screen.findByText("How the forecast held up")).toBeInTheDocument();
    expect(screen.getByText("Realized WMAPE")).toBeInTheDocument();
    expect(screen.getByText(/9\.1%/)).toBeInTheDocument();
  });

  it("shows how many forecast dates were measured and the source file", async () => {
    respondWith(measured);
    renderSection();
    expect(await screen.findByText(/10 of 10 forecast dates measured/)).toBeInTheDocument();
    expect(screen.getByText(/january-actuals\.csv/)).toBeInTheDocument();
  });

  it("reports a partial run as N of M", async () => {
    respondWith({
      ...measured,
      status: "partial",
      model: scores({ matched_points: 4 }),
      points: measured.points.slice(0, 1),
    });
    renderSection();
    expect(await screen.findByText(/4 of 10 forecast dates measured/)).toBeInTheDocument();
    expect(screen.getByText("Realized WMAPE")).toBeInTheDocument();
  });

  it("offers a way to re-check", async () => {
    respondWith(measured);
    renderSection();
    await screen.findByText("Realized WMAPE");
    expect(screen.getByRole("button", { name: /check|again|re-?check|newer/i })).toBeInTheDocument();
  });

  it("shows only the model forecast when there is no adjusted forecast", async () => {
    respondWith({ ...measured, adjusted: null });
    renderSection();
    await screen.findByText("Realized WMAPE");
    expect(screen.queryByText(/Your adjusted forecast/)).not.toBeInTheDocument();
  });

  it("shows both the model and the adjusted forecast when adjusted exists", async () => {
    respondWith({ ...measured, adjusted: scores({ wmape: 0.05, bias: 0.01 }) });
    renderSection();
    expect(await screen.findByText(/Model forecast/)).toBeInTheDocument();
    expect(screen.getByText(/Your adjusted forecast/)).toBeInTheDocument();
    expect(screen.getByText(/5\.0%|5%/)).toBeInTheDocument();
  });

  it("never renders a null WMAPE as 0%", async () => {
    // Every actual was zero: the score is undefined, not perfect.
    respondWith({
      ...measured,
      model: scores({ wmape: null, bias: null, actual_total: 0 }),
    });
    renderSection();
    await screen.findByText(/forecast dates measured/);
    expect(screen.queryByText("0%")).not.toBeInTheDocument();
    expect(screen.queryByText("0.0%")).not.toBeInTheDocument();
  });

  it("never mixes backtest stats into the realized section", async () => {
    respondWith(measured);
    renderSection();
    await screen.findByText("How the forecast held up");
    expect(screen.queryByText(/backtest/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^WMAPE$/)).not.toBeInTheDocument();
    expect(screen.queryByText(/median/i)).not.toBeInTheDocument();
  });
});

describe("RealizedAccuracySection: other metrics in the response", () => {
  it("renders only the entry for its own sheet and metric", async () => {
    const other: RealizedMetric = {
      ...measured,
      metric_name: "revenue",
      model: scores({ wmape: 0.777 }),
    };
    server.use(
      http.get("*/api/v1/forecast/:jobId/realized", () =>
        HttpResponse.json({ job_id: "job-1", metrics: [other, awaiting] }),
      ),
    );
    renderSection();
    expect(await screen.findByText(/This forecast covers/)).toBeInTheDocument();
    expect(screen.queryByText(/77\.7%/)).not.toBeInTheDocument();
  });
});
