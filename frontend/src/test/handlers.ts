import { http, HttpResponse } from "msw";
import type {
  ActiveRun,
  DashboardSummary,
  DataQualityReport,
  SeriesQuality,
  SampleDataset,
  TokenResponse,
  UploadResponse,
  UserResponse,
} from "@/types/api";

export const validTokenResponse: TokenResponse = {
  access_token: "mock-access-token",
  refresh_token: "mock-refresh-token",
  token_type: "bearer",
};

export const mockUser: UserResponse = {
  id: "user-1",
  email: "test@example.com",
  full_name: "Test User",
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
};

// Mirrors backend SAMPLE_CATALOG closely enough to exercise the UI: three
// entries in three different demand quadrants.
export const mockSamples: SampleDataset[] = [
  {
    id: "retail-daily-smooth",
    title: "Retail store sales",
    description: "Two years of daily unit sales for a steady retail line.",
    demand_class: "Smooth",
    file_name: "retail-daily-smooth.csv",
    frequency: "Daily",
    row_count: 730,
    columns: ["date", "units_sold", "marketing_spend", "avg_temp_c"],
  },
  {
    id: "spare-parts-intermittent",
    title: "Spare parts — intermittent",
    description: "Orders arrive on roughly one day in four.",
    demand_class: "Intermittent",
    file_name: "spare-parts-intermittent.csv",
    frequency: "Daily",
    row_count: 730,
    columns: ["date", "units_shipped"],
  },
  {
    id: "spare-parts-lumpy",
    title: "Spare parts — lumpy",
    description: "Sporadic and erratic at once.",
    demand_class: "Lumpy",
    file_name: "spare-parts-lumpy.csv",
    frequency: "Daily",
    row_count: 730,
    columns: ["date", "units_shipped"],
  },
];

export const mockSampleUpload: UploadResponse = {
  upload_id: "upload-from-sample-1",
  file_name: "retail-daily-smooth.csv",
  s3_key: "uploads/upload-from-sample-1/retail-daily-smooth.csv",
  sheets: ["Sheet1"],
  columns: { Sheet1: ["date", "units_sold", "marketing_spend", "avg_temp_c"] },
  row_counts: { Sheet1: 730 },
  uploaded_at: "2026-01-01T00:00:00Z",
};

// An account with no runs. This is the default because a signed-in visitor
// lands on /dashboard, and tests that don't care about the dashboard should
// see the plain empty state rather than invented numbers.
export const emptyDashboardSummary: DashboardSummary = {
  total_runs: 0,
  status_counts: { success: 0, failed: 0, stopped: 0, running: 0, pending: 0 },
  success_rate: null,
  median_wmape: null,
  last_run_at: null,
  recent_runs: [],
  accuracy_trend: [],
  demand_mix: { Smooth: 0, Erratic: 0, Intermittent: 0, Lumpy: 0, unclassified: 0 },
  active_runs: [],
  median_run_seconds: null,
  slowest_runs: [],
  model_wins: [],
};

// Not in mockDashboardSummary by default: an active run makes its row poll
// GET /forecast/{id}/progress, so tests that include one must also mock that.
export const mockActiveRun: ActiveRun = {
  job_id: "job-active",
  name: null,
  file_name: "spare-parts-lumpy.csv",
  status: "running",
  created_at: "2026-09-15T12:00:00Z",
  started_at: "2026-09-15T12:00:02Z",
};

export const mockDashboardSummary: DashboardSummary = {
  total_runs: 11,
  status_counts: { success: 9, failed: 1, stopped: 1, running: 0, pending: 0 },
  success_rate: 0.9,
  median_wmape: 0.0717,
  last_run_at: "2026-09-11T14:39:03Z",
  recent_runs: [
    {
      job_id: "job-5",
      name: null,
      file_name: "retail-daily-smooth.csv",
      status: "success",
      created_at: "2026-09-11T14:39:03Z",
      champion_model: "Prophet",
      metric_count: 1,
      wmape: 0.0316,
    },
    {
      job_id: "job-4",
      name: "Q3 target",
      file_name: "target_y.xlsx",
      status: "failed",
      created_at: "2026-08-26T10:00:00Z",
      champion_model: null,
      metric_count: 0,
      wmape: null,
    },
    {
      job_id: "job-3",
      name: null,
      file_name: "AirPassengers.csv",
      status: "success",
      created_at: "2026-07-27T09:00:00Z",
      champion_model: "Ridge",
      metric_count: 3,
      wmape: 0.0786,
    },
  ],
  accuracy_trend: [
    { job_id: "job-1", created_at: "2026-07-26T09:00:00Z", wmape: 0.12 },
    { job_id: "job-3", created_at: "2026-07-27T09:00:00Z", wmape: 0.0786 },
    { job_id: "job-5", created_at: "2026-09-11T14:39:03Z", wmape: 0.0316 },
  ],
  demand_mix: { Smooth: 7, Erratic: 2, Intermittent: 0, Lumpy: 1, unclassified: 1 },
  active_runs: [],
  median_run_seconds: 237,
  slowest_runs: [
    {
      job_id: "job-2",
      name: null,
      file_name: "AirPassengers.csv",
      created_at: "2026-07-26T09:00:00Z",
      duration_seconds: 413,
    },
    {
      job_id: "job-5",
      name: null,
      file_name: "retail-daily-smooth.csv",
      created_at: "2026-09-11T14:39:03Z",
      duration_seconds: 239,
    },
  ],
  model_wins: [
    { model_name: "Prophet", wins: 7 },
    { model_name: "Baseline_SMA", wins: 1 },
    { model_name: "Ensemble[Huber+Ridge]", wins: 1 },
    { model_name: "Theta", wins: 1 },
  ],
};

// ── data quality (F16) ───────────────────────────────────────────────

export const mockSeriesQuality: SeriesQuality = {
  sheet: "Sheet1",
  metric: "units_sold",
  rows_total: 730,
  usable_points: 730,
  start: "2023-01-01T00:00:00",
  end: "2024-12-30T00:00:00",
  span_days: 729,
  inferred_frequency: "D",
  imputed_pct: 0,
  duplicate_timestamps: 0,
  unparseable_dates: 0,
  non_numeric_values: 0,
  negative_values: 0,
  zero_pct: 0,
  outliers: 0,
  test_split_size: 30,
  effective_horizon: 60,
  issues: [],
};

// The default: a clean report, so pages that don't care about the data
// check render without one getting in the way.
export const mockQualityReport: DataQualityReport = {
  generated_at: "2026-09-16T10:00:00Z",
  has_blocking: false,
  series: [mockSeriesQuality],
  issues: [],
};

export const mockWarningReport: DataQualityReport = {
  ...mockQualityReport,
  series: [
    {
      ...mockSeriesQuality,
      duplicate_timestamps: 3,
      issues: [
        {
          code: "duplicate_timestamps",
          severity: "warning",
          message:
            "3 duplicate dates: only the last value for each date is kept — values are not summed.",
        },
      ],
    },
  ],
};

export const mockBlockingReport: DataQualityReport = {
  ...mockQualityReport,
  has_blocking: true,
  series: [
    {
      ...mockSeriesQuality,
      rows_total: 20,
      usable_points: 20,
      issues: [
        {
          code: "insufficient_history",
          severity: "blocking",
          message:
            "Only 20 usable data points; at least 30 are needed to train and test a model.",
        },
        {
          code: "negative_values",
          severity: "warning",
          message: "2 negative values will be clipped to 0.",
        },
      ],
    },
  ],
};

export const handlers = [
  http.post("*/api/v1/auth/login", () => HttpResponse.json(validTokenResponse)),
  http.post("*/api/v1/auth/refresh", () => HttpResponse.json(validTokenResponse)),
  http.get("*/api/v1/auth/me", () => HttpResponse.json(mockUser)),
  http.get("*/api/v1/upload/samples", () =>
    HttpResponse.json({ samples: mockSamples }),
  ),
  http.post("*/api/v1/upload/sample/:sampleId", () =>
    HttpResponse.json(mockSampleUpload, { status: 201 }),
  ),
  http.get("*/api/v1/dashboard", () =>
    HttpResponse.json(emptyDashboardSummary),
  ),
  http.post("*/api/v1/upload/:uploadId/quality-report", () =>
    HttpResponse.json(mockQualityReport),
  ),
];
