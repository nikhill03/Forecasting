import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { CheckActualsDialog } from "./CheckActualsDialog";
import { server } from "@/test/server";
import { renderWithProviders } from "@/test/renderWithProviders";
import { mockRealizedComplete } from "@/test/handlers";

const candidate = {
  upload_id: "upload-actuals",
  file_name: "january-actuals.csv",
  created_at: "2025-02-01T09:00:00Z",
};

function renderDialog(onClose = vi.fn()) {
  renderWithProviders(
    <CheckActualsDialog
      jobId="job-1"
      forecastStart="2025-01-01"
      forecastEnd="2025-01-10"
      panelId="panel"
      onClose={onClose}
    />,
  );
  return onClose;
}

function withCandidates(candidates: unknown[]) {
  server.use(
    http.get("*/api/v1/forecast/job-1/realized/candidates", () =>
      HttpResponse.json({ candidates }),
    ),
  );
}

describe("CheckActualsDialog", () => {
  it("lists later uploads and checks the forecast against the chosen one", async () => {
    withCandidates([candidate]);
    let body: unknown;
    server.use(
      http.post("*/api/v1/forecast/job-1/realized", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(mockRealizedComplete);
      }),
    );
    const onClose = renderDialog();

    await userEvent.click(await screen.findByRole("button", { name: "Use january-actuals.csv" }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(body).toEqual({ upload_id: "upload-actuals" });
  });

  it("offers an upload straight away when no earlier file fits", async () => {
    withCandidates([]);
    renderDialog();
    expect(await screen.findByText(/None of your later uploads include this metric/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Upload dataset file/)).toBeInTheDocument();
  });

  it("shows the server's reason when a file can't be used, and stays open", async () => {
    withCandidates([candidate]);
    server.use(
      http.post("*/api/v1/forecast/job-1/realized", () =>
        HttpResponse.json(
          { detail: "This file has none of the forecast's metric columns" },
          { status: 422 },
        ),
      ),
    );
    const onClose = renderDialog();

    await userEvent.click(await screen.findByRole("button", { name: "Use january-actuals.csv" }));

    expect(await screen.findByText(/none of the forecast's metric columns/)).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("closes on cancel without checking anything", async () => {
    withCandidates([]);
    const onClose = renderDialog();
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("keeps the upload option when the uploads can't be listed", async () => {
    server.use(
      http.get("*/api/v1/forecast/job-1/realized/candidates", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    renderDialog();
    expect(await screen.findByRole("alert")).toHaveTextContent(/Could not load your uploads/);
  });
});
