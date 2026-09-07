import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { act } from "react";
import { describe, it, expect, beforeEach } from "vitest";

import { SampleDataPanel } from "./SampleDataPanel";
import { renderWithProviders } from "@/test/renderWithProviders";
import { server } from "@/test/server";
import { mockSampleUpload, mockSamples } from "@/test/handlers";
import { useForecastStore } from "@/store/forecastStore";

describe("SampleDataPanel", () => {
  beforeEach(() => {
    act(() => useForecastStore.getState().reset());
  });

  it("renders every sample from the catalog", async () => {
    renderWithProviders(<SampleDataPanel />);

    for (const sample of mockSamples) {
      expect(await screen.findByText(sample.title)).toBeInTheDocument();
    }
  });

  it("shows each sample's demand quadrant and row count", async () => {
    renderWithProviders(<SampleDataPanel />);

    await screen.findByText("Retail store sales");

    // The three samples must be visibly different — that contrast is the
    // reason more than one ships.
    expect(screen.getByLabelText(/smooth demand pattern/i)).toBeInTheDocument();
    expect(
      screen.getByLabelText(/intermittent demand pattern/i),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/lumpy demand pattern/i)).toBeInTheDocument();

    expect(screen.getAllByText(/730 rows · Daily/)).toHaveLength(
      mockSamples.length,
    );
  });

  it("writes the created upload into the forecast store on selection", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SampleDataPanel />);

    await user.click(await screen.findByText("Retail store sales"));

    await waitFor(() => {
      expect(useForecastStore.getState().upload?.upload_id).toBe(
        mockSampleUpload.upload_id,
      );
    });
  });

  it("advances the workflow to the configure step, exactly as a file upload does", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SampleDataPanel />);

    await user.click(await screen.findByText("Spare parts — lumpy"));

    await waitFor(() => {
      expect(useForecastStore.getState().step).toBe("configure");
    });
    // setUpload seeds the first sheet, which is what ConfigurePage reads.
    expect(useForecastStore.getState().config.selectedSheets).toEqual([
      "Sheet1",
    ]);
  });

  it("surfaces a server error without losing the panel", async () => {
    server.use(
      http.post("*/api/v1/upload/sample/:sampleId", () =>
        HttpResponse.json({ detail: "Sample storage unavailable" }, { status: 503 }),
      ),
    );

    const user = userEvent.setup();
    renderWithProviders(<SampleDataPanel />);

    await user.click(await screen.findByText("Retail store sales"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Sample storage unavailable",
    );
    expect(useForecastStore.getState().upload).toBeNull();
  });

  it("renders nothing when the catalog is empty", async () => {
    server.use(
      http.get("*/api/v1/upload/samples", () =>
        HttpResponse.json({ samples: [] }),
      ),
    );

    const { container } = renderWithProviders(<SampleDataPanel />);

    await waitFor(() => {
      expect(screen.queryByText(/loading sample datasets/i)).not.toBeInTheDocument();
    });
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the catalog request fails", async () => {
    server.use(
      http.get("*/api/v1/upload/samples", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );

    const { container } = renderWithProviders(<SampleDataPanel />);

    await waitFor(() => {
      expect(container).toBeEmptyDOMElement();
    });
  });
});
