import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useDataQualityReport } from "./useDataQualityReport";
import { mockQualityReport } from "@/test/handlers";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const selected = {
  selectedSheets: ["Sheet1"],
  selectedMetrics: ["units_sold"],
  forecastHorizon: 60,
  testWindow: 30,
};

describe("useDataQualityReport", () => {
  it("returns the report for a checkable selection", async () => {
    const { result } = renderHook(() => useDataQualityReport("upload-1", selected), { wrapper });
    await waitFor(() => expect(result.current.report).toEqual(mockQualityReport));
    expect(result.current.idleReason).toBeNull();
  });

  it("drops the previous report once every metric is unselected", async () => {
    const { result, rerender } = renderHook(
      ({ config }) => useDataQualityReport("upload-1", config),
      { wrapper, initialProps: { config: selected } },
    );
    await waitFor(() => expect(result.current.report).toBeDefined());

    rerender({ config: { ...selected, selectedMetrics: [] } });
    expect(result.current.report).toBeUndefined();
    expect(result.current.idleReason).toBe("no-selection");
  });

  it("reports invalid settings rather than checking", () => {
    const { result } = renderHook(
      () => useDataQualityReport("upload-1", { ...selected, testWindow: 0 }),
      { wrapper },
    );
    expect(result.current.report).toBeUndefined();
    expect(result.current.isLoading).toBe(false);
    expect(result.current.idleReason).toBe("invalid-settings");
  });
});
