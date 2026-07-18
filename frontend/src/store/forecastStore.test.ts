import { describe, it, expect, beforeEach } from "vitest";
import { useForecastStore } from "./forecastStore";
import type { UploadResponse } from "@/types/api";

const mockUpload: UploadResponse = {
  upload_id: "abc-123",
  file_name: "sales.csv",
  s3_key: "uploads/abc-123/sales.csv",
  sheets: ["Sheet1", "Sheet2"],
  columns: { Sheet1: ["date", "revenue"], Sheet2: ["date", "units"] },
  row_counts: { Sheet1: 100, Sheet2: 50 },
  uploaded_at: "2024-01-01T00:00:00Z",
};

describe("useForecastStore", () => {
  beforeEach(() => {
    useForecastStore.getState().reset();
  });

  it("starts at the upload step", () => {
    expect(useForecastStore.getState().step).toBe("upload");
  });

  it("transitions to configure step on setUpload", () => {
    useForecastStore.getState().setUpload(mockUpload);
    const state = useForecastStore.getState();
    expect(state.step).toBe("configure");
    expect(state.upload).toEqual(mockUpload);
  });

  it("defaults selectedSheets to first sheet after upload", () => {
    useForecastStore.getState().setUpload(mockUpload);
    expect(useForecastStore.getState().config.selectedSheets).toEqual([
      "Sheet1",
    ]);
  });

  it("updateConfig merges partial config without losing other fields", () => {
    useForecastStore.getState().setUpload(mockUpload);
    useForecastStore.getState().updateConfig({ forecastHorizon: 90 });

    const config = useForecastStore.getState().config;
    expect(config.forecastHorizon).toBe(90);
    expect(config.testWindow).toBe(30);
  });

  it("setActiveJobId transitions to running step", () => {
    useForecastStore.getState().setActiveJobId("job-456");
    const state = useForecastStore.getState();
    expect(state.activeJobId).toBe("job-456");
    expect(state.step).toBe("running");
  });

  it("setActiveJobId(null) transitions back to configure step", () => {
    useForecastStore.getState().setActiveJobId("job-456");
    useForecastStore.getState().setActiveJobId(null);
    expect(useForecastStore.getState().step).toBe("configure");
  });

  it("reset clears all state back to initial", () => {
    useForecastStore.getState().setUpload(mockUpload);
    useForecastStore.getState().setActiveJobId("job-456");
    useForecastStore.getState().reset();

    const state = useForecastStore.getState();
    expect(state.step).toBe("upload");
    expect(state.upload).toBeNull();
    expect(state.activeJobId).toBeNull();
  });
});