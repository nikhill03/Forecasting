import { describe, it, expect } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/server";
import { ApiError } from "./client";
import { dashboardService } from "./dashboardService";
import { mockDashboardSummary } from "@/test/handlers";

describe("dashboardService.getSummary", () => {
  it("returns the validated summary", async () => {
    server.use(
      http.get("*/api/v1/dashboard", () =>
        HttpResponse.json(mockDashboardSummary),
      ),
    );

    await expect(dashboardService.getSummary()).resolves.toEqual(
      mockDashboardSummary,
    );
  });

  it("rejects with ApiError when the response is malformed", async () => {
    server.use(
      http.get("*/api/v1/dashboard", () =>
        HttpResponse.json({ total_runs: "many" }),
      ),
    );

    await expect(dashboardService.getSummary()).rejects.toBeInstanceOf(ApiError);
  });
});
