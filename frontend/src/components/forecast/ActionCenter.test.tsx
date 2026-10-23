import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";

import { ActionCenter } from "./ActionCenter";
import { server } from "@/test/server";
import { renderWithProviders } from "@/test/renderWithProviders";

const record = {
  Date: "2025-01-01",
  TrainActual: null,
  TrainRaw: null,
  TestActual: null,
  TestPrediction: null,
  Forecast: 100,
};
const edit = {
  id: "edit-1",
  sequence_no: 1,
  instruction_text: "cap the forecast at 90",
  operation_type: "clip_bounds",
  params: { max_value: 90 },
  created_at: "2025-02-01T00:00:00Z",
};

function renderCenter() {
  const onRecordsChange = vi.fn();
  const onEditsChanged = vi.fn();
  renderWithProviders(
    <ActionCenter
      jobId="job-1"
      sheetName="Sheet1"
      metricName="units_sold"
      onRecordsChange={onRecordsChange}
      onEditsChanged={onEditsChanged}
    />,
  );
  return { onRecordsChange, onEditsChanged };
}

describe("ActionCenter", () => {
  it("reports its records on first load without announcing an edit", async () => {
    server.use(
      http.get("*/api/v1/forecast/job-1/actions", () =>
        HttpResponse.json({ records: [record], edits: [] }),
      ),
    );
    const { onRecordsChange, onEditsChanged } = renderCenter();

    await waitFor(() => expect(onRecordsChange).toHaveBeenCalledWith([record]));
    expect(onEditsChanged).not.toHaveBeenCalled();
  });

  it("announces an edit once one is applied", async () => {
    server.use(
      http.get("*/api/v1/forecast/job-1/actions", () =>
        HttpResponse.json({ records: [record], edits: [] }),
      ),
      http.post("*/api/v1/forecast/job-1/actions", () =>
        HttpResponse.json({ records: [{ ...record, Forecast: 90 }], edits: [edit] }),
      ),
    );
    const { onRecordsChange, onEditsChanged } = renderCenter();
    await waitFor(() => expect(onRecordsChange).toHaveBeenCalled());

    await userEvent.type(screen.getByRole("textbox"), "cap the forecast at 90");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => expect(onEditsChanged).toHaveBeenCalledOnce());
  });

  it("announces an edit once one is reverted", async () => {
    server.use(
      http.get("*/api/v1/forecast/job-1/actions", () =>
        HttpResponse.json({ records: [{ ...record, Forecast: 90 }], edits: [edit] }),
      ),
      http.post("*/api/v1/forecast/job-1/actions/revert", () =>
        HttpResponse.json({ records: [record], edits: [] }),
      ),
    );
    const { onEditsChanged } = renderCenter();

    await userEvent.click(await screen.findByRole("button", { name: /Revert last edit/ }));

    await waitFor(() => expect(onEditsChanged).toHaveBeenCalledOnce());
  });
});
