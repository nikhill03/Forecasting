import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { uploadService } from "@/services/uploadService";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";

export const QUALITY_REPORT_DEBOUNCE_MS = 400;

interface QualityReportConfig {
  selectedSheets: string[];
  selectedMetrics: string[];
  forecastHorizon: number;
  testWindow: number;
}

/**
 * Configure-time data-quality preview (F16). Each request re-reads and
 * re-profiles the whole file on the server, so the free-typed number inputs
 * are debounced; the previous report stays on screen while a new one loads.
 *
 * A failed request is surfaced as `isError` and must never block a run —
 * POST /forecast repeats the check authoritatively.
 */
export function useDataQualityReport(
  uploadId: string | undefined,
  config: QualityReportConfig,
) {
  const forecastHorizon = useDebouncedValue(
    config.forecastHorizon,
    QUALITY_REPORT_DEBOUNCE_MS,
  );
  const testWindow = useDebouncedValue(
    config.testWindow,
    QUALITY_REPORT_DEBOUNCE_MS,
  );
  const { selectedSheets, selectedMetrics } = config;
  const hasSelection = selectedSheets.length > 0 && selectedMetrics.length > 0;
  const hasValidSettings =
    Number.isInteger(forecastHorizon) &&
    forecastHorizon >= 1 &&
    forecastHorizon <= 365 &&
    Number.isInteger(testWindow) &&
    testWindow >= 7 &&
    testWindow <= 180;
  const enabled = uploadId !== undefined && hasSelection && hasValidSettings;

  const query = useQuery({
    queryKey: [
      "quality-report",
      uploadId,
      selectedSheets,
      selectedMetrics,
      forecastHorizon,
      testWindow,
    ],
    queryFn: () =>
      uploadService.getQualityReport(uploadId ?? "", {
        selected_sheets: selectedSheets,
        selected_metrics: selectedMetrics,
        forecast_horizon: forecastHorizon,
        test_window: testWindow,
      }),
    enabled,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });

  // keepPreviousData keeps the last result around even once the query is
  // disabled — e.g. after unselecting every metric. A report must only ever
  // describe the current selection, so drop it whenever nothing can be checked.
  return {
    report: enabled ? query.data : undefined,
    isLoading: enabled && query.isLoading,
    isFetching: enabled && query.isFetching,
    isError: enabled && query.isError,
    idleReason: !hasSelection
      ? ("no-selection" as const)
      : !hasValidSettings
        ? ("invalid-settings" as const)
        : null,
  };
}
