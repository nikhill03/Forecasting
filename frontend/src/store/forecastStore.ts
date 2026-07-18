import { create } from "zustand";
import type { UploadResponse, DemandType } from "@/types/api";

export type WorkflowStep = "upload" | "configure" | "running" | "results";

interface ForecastConfig {
  selectedSheets: string[];
  selectedMetrics: string[];
  selectedXCols: string[];
  forecastHorizon: number;
  testWindow: number;
  selectedRegions: string[];
  quantileLevel: number;
}

interface ForecastState {
  step: WorkflowStep;
  upload: UploadResponse | null;
  config: ForecastConfig;
  activeJobId: string | null;
  setStep: (step: WorkflowStep) => void;
  setUpload: (upload: UploadResponse) => void;
  updateConfig: (partial: Partial<ForecastConfig>) => void;
  setActiveJobId: (jobId: string | null) => void;
  reset: () => void;
}

const DEFAULT_CONFIG: ForecastConfig = {
  selectedSheets: [],
  selectedMetrics: [],
  selectedXCols: [],
  forecastHorizon: 60,
  testWindow: 30,
  selectedRegions: ["US", "IN"],
  quantileLevel: 0.75,
};

export const useForecastStore = create<ForecastState>((set) => ({
  step: "upload",
  upload: null,
  config: DEFAULT_CONFIG,
  activeJobId: null,

  setStep: (step) => set({ step }),

  setUpload: (upload) =>
    set({
      upload,
      step: "configure",
      config: {
        ...DEFAULT_CONFIG,
        selectedSheets: upload.sheets.slice(0, 1),
      },
    }),

  updateConfig: (partial) =>
    set((state) => ({ config: { ...state.config, ...partial } })),

  setActiveJobId: (jobId) =>
    set({ activeJobId: jobId, step: jobId ? "running" : "configure" }),

  reset: () =>
    set({
      step: "upload",
      upload: null,
      config: DEFAULT_CONFIG,
      activeJobId: null,
    }),
}));

export const DEMAND_TYPE_META: Record<
  DemandType,
  { label: string; colorVar: string; description: string }
> = {
  Smooth: {
    label: "Smooth",
    colorVar: "demand-smooth",
    description: "Regular, predictable demand",
  },
  Erratic: {
    label: "Erratic",
    colorVar: "demand-erratic",
    description: "Frequent but highly variable demand",
  },
  Intermittent: {
    label: "Intermittent",
    colorVar: "demand-intermittent",
    description: "Sparse but regular-sized demand",
  },
  Lumpy: {
    label: "Lumpy",
    colorVar: "demand-lumpy",
    description: "Sparse and highly variable demand",
  },
};