import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { RealizedAccuracySection } from "./RealizedAccuracySection";
import { server } from "@/test/server";
import { renderWithProviders } from "@/test/renderWithProviders";
import {
  mockRealizedAwaitingMetric,
  mockRealizedMeasuredMetric,
  mockRealizedScores,
} from "@/test/handlers";
import type { RealizedAccuracyResponse, RealizedMetric } from "@/types/api";

// ECharts needs a real layout engine; the chart has its own coverage by eye.
vi.mock("./RealizedChart", () => ({
  RealizedChart: ({ points }: { points: unknown[] }) => (
    <div data-testid="realized-chart">{points.length} points</div>
  ),
}));

const baseMetric = mockRealizedAwaitingMetric;
const measured   = mockRealizedMeasuredMetric;

function respondWith(metric: RealizedMetric) {
  const body: RealizedAccuracyResponse = { job_id: "job-1", metrics: [metric] };
  server.use(http.get("*/api/v1/forecast/job-1/realized", () => HttpResponse.json(body)));
}

function renderSection() {
  return renderWithProviders(
    <RealizedAccuracySection jobId="job-1" sheetName="Sheet1" metricName="units_sold" />,
  );
}

describe("RealizedAccuracySection", () => {
  it("says what dates are needed when the forecast has never been checked", async () => {
    renderSection();
    expect(await screen.findByText(/This forecast covers/)).toBeInTheDocument();
    expect(screen.getByText(/Upload data that includes those dates/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check against newer data" })).toBeInTheDocument();
    // No score of any kind before there is something to score.
    expect(screen.queryByText(/Realized WMAPE/)).not.toBeInTheDocument();
  });

  it("shows realized scores under their own heading, labelled as realized", async () => {
    respondWith(measured);
    renderSection();

    expect(await screen.findByText("How the forecast held up")).toBeInTheDocument();
    expect(screen.getByText("Realized WMAPE")).toBeInTheDocument();
    expect(screen.getByText("9.1%")).toBeInTheDocument();
    expect(screen.getByText("Under-forecast by 9%.")).toBeInTheDocument();
    expect(screen.getByText(/10 of 10 forecast dates measured/)).toBeInTheDocument();
    expect(screen.getByText(/january-actuals\.csv/)).toBeInTheDocument();
    expect(screen.getByTestId("realized-chart")).toHaveTextContent("2 points");
    expect(screen.getByRole("button", { name: "Check against another file" })).toBeInTheDocument();
  });

  it("reports a partial check with how many dates were measured", async () => {
    respondWith({
      ...measured,
      status: "partial",
      model: { ...mockRealizedScores, matched_points: 4 },
    });
    renderSection();
    expect(await screen.findByText(/4 of 10 forecast dates measured/)).toBeInTheDocument();
  });

  it("shows the model and the adjusted forecast side by side when there are edits", async () => {
    respondWith({
      ...measured,
      adjusted: { ...mockRealizedScores, wmape: 0.02, bias: 0.02 },
    });
    renderSection();

    expect(await screen.findByText("Model forecast")).toBeInTheDocument();
    expect(screen.getByText("Your adjusted forecast")).toBeInTheDocument();
    expect(screen.getByText("2.0%")).toBeInTheDocument();
  });

  it("explains a file that ends before the forecast starts", async () => {
    respondWith({
      ...baseMetric,
      status: "no_overlap",
      actuals_last_date: "2024-12-20",
      upload_file_name: "old.csv",
    });
    renderSection();
    expect(await screen.findByText(/old\.csv ends on .*before this forecast starts on/)).toBeInTheDocument();
    expect(screen.queryByText(/Realized WMAPE/)).not.toBeInTheDocument();
  });

  it("never turns a missing percentage into 0%", async () => {
    respondWith({
      ...measured,
      model: { ...mockRealizedScores, wmape: null, bias: null },
    });
    renderSection();
    expect(await screen.findByText(/Every actual was zero/)).toBeInTheDocument();
    expect(screen.queryByText("0.0%")).not.toBeInTheDocument();
  });

  it("renders nothing for a metric the response doesn't list", async () => {
    // The component also renders nothing while loading, so first wait until the
    // response has been served and the query has settled.
    let served = false;
    server.use(
      http.get("*/api/v1/forecast/job-1/realized", () => {
        served = true;
        return HttpResponse.json({ job_id: "job-1", metrics: [] });
      }),
    );
    const { container } = renderSection();
    await waitFor(() => expect(served).toBe(true));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(container).toBeEmptyDOMElement();
  });

  it("opens the picker from the check button", async () => {
    renderSection();
    await userEvent.click(await screen.findByRole("button", { name: "Check against newer data" }));
    expect(screen.getByRole("region", { name: "Check against newer data" })).toBeInTheDocument();
  });

  it("tells assistive tech whether the picker is open, and returns focus to the button when it closes", async () => {
    renderSection();
    const trigger = await screen.findByRole("button", { name: "Check against newer data" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    await userEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(trigger).toHaveAttribute("aria-controls", screen.getByRole("region", { name: "Check against newer data" }).id);

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("region", { name: "Check against newer data" })).not.toBeInTheDocument();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveFocus();
  });

  it("degrades quietly when the realized request fails", async () => {
    server.use(
      http.get("*/api/v1/forecast/job-1/realized", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    renderSection();
    expect(await screen.findByText(/Could not load how this forecast held up/)).toBeInTheDocument();
  });
});
