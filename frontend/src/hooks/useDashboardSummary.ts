import { useQuery } from "@tanstack/react-query";
import { dashboardService } from "@/services/dashboardService";
import type { DashboardSummary } from "@/types/api";

const ACTIVE_REFRESH_MS = 10_000;

/**
 * Refresh the summary on a timer only while a run is in flight, so a finished
 * run leaves the "In progress" panel and lands in the totals without a
 * reload. Each active row polls its own progress separately, and faster.
 *
 * Exported as a pure function so it can be tested without React, like
 * computeRefetchInterval in useForecastJob.ts.
 */
export function summaryRefetchInterval(
  summary: DashboardSummary | undefined,
): number | false {
  return summary && summary.active_runs.length > 0 ? ACTIVE_REFRESH_MS : false;
}

// Otherwise a finished run changes these numbers, but not from second to
// second. 30s keeps returning to the dashboard instant without showing stale
// totals for long after a job completes.
export function useDashboardSummary() {
  return useQuery({
    queryKey: ["dashboard-summary"],
    queryFn: () => dashboardService.getSummary(),
    staleTime: 30_000,
    refetchInterval: (query) => summaryRefetchInterval(query.state.data),
  });
}
