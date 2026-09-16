import { apiClient } from "./client";
import { parseOrThrow } from "@/lib/validateResponse";
import { DashboardSummarySchema } from "@/types/api.schemas";
import type { DashboardSummary } from "@/types/api";

export const dashboardService = {
  async getSummary(): Promise<DashboardSummary> {
    const { data } = await apiClient.get("/dashboard");
    return parseOrThrow(
      DashboardSummarySchema,
      data,
      "dashboardService.getSummary",
    );
  },
};
