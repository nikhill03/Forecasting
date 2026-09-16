import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { act } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ActiveRuns } from "./ActiveRuns";
import { server } from "@/test/server";
import { mockActiveRun } from "@/test/handlers";
import { useForecastStore } from "@/store/forecastStore";
import type { ActiveRun, ProgressResponse } from "@/types/api";

function mockProgress(body: Partial<ProgressResponse>) {
  server.use(
    http.get("*/api/v1/forecast/:jobId/progress", () =>
      HttpResponse.json({
        job_id: mockActiveRun.job_id,
        status: "running",
        progress: 0,
        message: "",
        ...body,
      }),
    ),
  );
}

// A local render (not renderWithProviders) so a test can hand in its own
// QueryClient and watch what gets invalidated.
function renderActive(runs: ActiveRun[], client?: QueryClient) {
  const queryClient =
    client ?? new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/" element={<ActiveRuns runs={runs} />} />
          <Route path="/running" element={<p>Running page</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ActiveRuns", () => {
  beforeEach(() => {
    act(() => useForecastStore.getState().reset());
  });

  it("renders nothing when no run is in flight", () => {
    const { container } = renderActive([]);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows live progress from the progress endpoint, not the stored row", async () => {
    mockProgress({ progress: 42, message: "Stage 3/5: Evaluating models" });
    renderActive([mockActiveRun]);

    expect(await screen.findByText("Stage 3/5: Evaluating models")).toBeInTheDocument();
    expect(screen.getByText("42%")).toBeInTheDocument();
  });

  it("opens the Running page for that job", async () => {
    mockProgress({ progress: 10, message: "Stage 1/5" });
    const user = userEvent.setup();
    renderActive([mockActiveRun]);

    await user.click(screen.getByRole("button", { name: /spare-parts-lumpy\.csv/i }));

    expect(useForecastStore.getState().activeJobId).toBe("job-active");
    expect(await screen.findByText("Running page")).toBeInTheDocument();
  });

  it("refreshes the dashboard summary when the run finishes", async () => {
    mockProgress({ status: "success", progress: 100, message: "Completed successfully" });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidate = vi.spyOn(client, "invalidateQueries");

    renderActive([mockActiveRun], client);

    await waitFor(() =>
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ["dashboard-summary"] }),
    );
  });

  it("does not refresh the summary while the run is still going", async () => {
    mockProgress({ progress: 30, message: "Stage 2/5" });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidate = vi.spyOn(client, "invalidateQueries");

    renderActive([mockActiveRun], client);
    await screen.findByText("Stage 2/5");

    expect(invalidate).not.toHaveBeenCalled();
  });
});
