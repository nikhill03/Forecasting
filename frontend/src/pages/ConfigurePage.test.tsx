import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";

import { ConfigurePage } from "./ConfigurePage";
import { useForecastStore } from "@/store/forecastStore";
import { renderWithProviders } from "@/test/renderWithProviders";
import { server } from "@/test/server";
import {
  mockBlockingReport,
  mockQualityReport,
  mockSampleUpload,
  mockWarningReport,
} from "@/test/handlers";

const QUALITY_URL = "*/api/v1/upload/:uploadId/quality-report";

function seedConfigured() {
  useForecastStore.getState().reset();
  useForecastStore.getState().setUpload(mockSampleUpload);
  useForecastStore.getState().updateConfig({ selectedMetrics: ["units_sold"] });
}

const runButton = () => screen.getByRole("button", { name: /run forecast/i });

describe("ConfigurePage data check", () => {
  beforeEach(() => {
    seedConfigured();
  });

  it("disables Run forecast and names the series when the check blocks", async () => {
    server.use(http.post(QUALITY_URL, () => HttpResponse.json(mockBlockingReport)));
    renderWithProviders(<ConfigurePage />);

    expect(await screen.findByText("Must fix before running")).toBeInTheDocument();
    expect(runButton()).toBeDisabled();
    expect(
      screen.getByText("Fix Sheet1 / units_sold to run this forecast."),
    ).toBeInTheDocument();
  });

  it("leaves Run forecast enabled when there are only warnings", async () => {
    server.use(http.post(QUALITY_URL, () => HttpResponse.json(mockWarningReport)));
    renderWithProviders(<ConfigurePage />);

    expect(await screen.findByText("Worth knowing")).toBeInTheDocument();
    expect(runButton()).toBeEnabled();
  });

  it("leaves Run forecast enabled when the check itself fails", async () => {
    server.use(
      http.post(QUALITY_URL, () =>
        HttpResponse.json({ detail: "Upload storage unavailable" }, { status: 503 }),
      ),
    );
    renderWithProviders(<ConfigurePage />);

    expect(await screen.findByText(/couldn't check this data/i)).toBeInTheDocument();
    expect(runButton()).toBeEnabled();
  });

  it("does not check until a metric is selected", async () => {
    let calls = 0;
    server.use(
      http.post(QUALITY_URL, () => {
        calls += 1;
        return HttpResponse.json(mockQualityReport);
      }),
    );
    useForecastStore.getState().updateConfig({ selectedMetrics: [] });
    renderWithProviders(<ConfigurePage />);

    expect(
      await screen.findByText(/pick a sheet and a metric/i),
    ).toBeInTheDocument();
    expect(calls).toBe(0);
  });

  it("shows the report from a refused submit", async () => {
    // Preview says fine (e.g. the file changed between check and submit),
    // but the server's own check refuses.
    server.use(
      http.post("*/api/v1/forecast", () =>
        HttpResponse.json(
          {
            detail: {
              message: "This data can't be forecast yet — fix the issues marked as blocking.",
              quality_report: mockBlockingReport,
            },
          },
          { status: 422 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderWithProviders(<ConfigurePage />);

    await screen.findByText("No issues found in 1 series.");
    await user.click(runButton());

    expect(await screen.findByText("Must fix before running")).toBeInTheDocument();
    expect(runButton()).toBeDisabled();
  });

  it("sends one check after the horizon stops changing, not one per keystroke", async () => {
    const horizons: number[] = [];
    server.use(
      http.post(QUALITY_URL, async ({ request }) => {
        const body = (await request.json()) as { forecast_horizon: number };
        horizons.push(body.forecast_horizon);
        return HttpResponse.json(mockQualityReport);
      }),
    );
    const user = userEvent.setup();
    renderWithProviders(<ConfigurePage />);
    await waitFor(() => expect(horizons).toEqual([60]));

    const input = screen.getByLabelText(/forecast horizon/i);
    await user.clear(input);
    await user.type(input, "120");

    await waitFor(() => expect(horizons).toEqual([60, 120]), { timeout: 2000 });
  });
});

describe("ConfigurePage navigation", () => {
  beforeEach(() => {
    seedConfigured();
  });

  it("Back clears the loaded file so the upload page doesn't bounce back", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <Routes>
        <Route path="/configure" element={<ConfigurePage />} />
        <Route path="/upload" element={<p>upload page</p>} />
      </Routes>,
      { route: "/configure" },
    );

    await user.click(screen.getByRole("button", { name: /back/i }));

    expect(await screen.findByText("upload page")).toBeInTheDocument();
    expect(useForecastStore.getState().upload).toBeNull();
  });
});
