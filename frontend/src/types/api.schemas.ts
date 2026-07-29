import { z } from "zod";

// Zod schemas are the single source of truth for API request/response shapes.
// `types/api.ts` re-exports `z.infer<typeof X>` for each of these — never
// hand-write a duplicate interface there.
//
// Datetime/UUID-shaped fields stay `z.string()` (no `.datetime()`/`.uuid()`):
// the contract being enforced here is structural (presence, type, nullability),
// not stricter format validation than the codebase has ever asserted.

// ── auth ──────────────────────────────────────────────────────────────

export const UserRegisterRequestSchema = z.object({
  email: z.string().email(),
  password: z.string().min(8).max(100),
  full_name: z.string().min(1).max(255),
});

export const UserLoginRequestSchema = z.object({
  email: z.string().email(),
  password: z.string(),
});

export const TokenResponseSchema = z.object({
  access_token: z.string(),
  refresh_token: z.string(),
  token_type: z.literal("bearer"),
});

export const UserResponseSchema = z.object({
  id: z.string(),
  email: z.string(),
  full_name: z.string(),
  is_active: z.boolean(),
  created_at: z.string(),
});

// ── upload ────────────────────────────────────────────────────────────

export const UploadResponseSchema = z.object({
  upload_id: z.string(),
  file_name: z.string(),
  s3_key: z.string(),
  sheets: z.array(z.string()),
  columns: z.record(z.array(z.string())),
  row_counts: z.record(z.number()),
  uploaded_at: z.string(),
});

// ── forecast: shared enums ───────────────────────────────────────────

export const DemandTypeSchema = z.enum([
  "Smooth",
  "Erratic",
  "Intermittent",
  "Lumpy",
]);

export const JobStatusSchema = z.enum([
  "pending",
  "running",
  "success",
  "failed",
  "stopped",
]);

// ── forecast: request ────────────────────────────────────────────────

export const ForecastRequestSchema = z.object({
  upload_id: z.string(),
  selected_sheets: z.array(z.string()).min(1),
  selected_metrics: z.array(z.string()).min(1),
  selected_x_cols: z.array(z.string()).optional(),
  forecast_horizon: z.number().int().min(1).max(365),
  test_window: z.number().int().min(7).max(180),
  selected_regions: z.array(z.string()),
  quantile_level: z.number().min(0.5).max(0.99),
});

export const RenameJobRequestSchema = z.object({
  name: z.string().trim().min(1).max(255),
});

export const ApplyActionRequestSchema = z.object({
  sheet_name: z.string(),
  metric_name: z.string(),
  instruction_text: z.string().min(1).max(500),
});

export const RevertActionRequestSchema = z.object({
  sheet_name: z.string(),
  metric_name: z.string(),
});

export const QARequestSchema = z.object({
  sheet_name: z.string(),
  metric_name: z.string(),
  question: z.string().min(1).max(500),
});

// ── forecast: response, built bottom-up to mirror backend/models/schemas.py ─

export const DemandProfileSchema = z.object({
  demand_type: DemandTypeSchema,
  adi: z.number(),
  cv2: z.number(),
  is_intermittent: z.boolean(),
  is_erratic: z.boolean(),
  recommended_models: z.array(z.string()),
});

export const ForecastRecordSchema = z.object({
  Date: z.string(),
  TrainActual: z.number().nullable(),
  TrainRaw: z.number().nullable(),
  TestActual: z.number().nullable(),
  TestPrediction: z.number().nullable(),
  Forecast: z.number().nullable(),
});

export const MetricResultSchema = z.object({
  // Optional[str] on the backend (backend/models/schemas.py) — can be null
  // for a partial/failed model run. See ResultsPage.tsx for the call site
  // this drove a fix in.
  metric_name: z.string().nullable(),
  best_model: z.string().nullable(),
  wmape: z.number().nullable(),
  mae: z.number().nullable(),
  mape: z.number().nullable(),
  rmse: z.number().nullable(),
  accuracy: z.number().nullable(),
  composite_score: z.number().nullable(),
  demand_profile: DemandProfileSchema.nullable(),
  feature_importance: z.record(z.number()).nullable(),
  forecast_bias: z.number().nullable(),
  records: z.array(ForecastRecordSchema),
});

export const SheetResultSchema = z.object({
  // Optional[str] on the backend, same as MetricResult.metric_name above.
  sheet_name: z.string().nullable(),
  metrics: z.record(MetricResultSchema),
});

export const ForecastJobResponseSchema = z.object({
  job_id: z.string(),
  status: JobStatusSchema,
  name: z.string().nullable(),
  progress: z.number(),
  message: z.string(),
  created_at: z.string(),
  started_at: z.string().nullable(),
  completed_at: z.string().nullable(),
  results: z.record(SheetResultSchema).nullable(),
  error: z.string().nullable(),
});

export const ForecastJobMetricSummarySchema = z.object({
  sheet_name: z.string().nullable(),
  metric_name: z.string().nullable(),
  model_name: z.string().nullable(),
  wmape: z.number().nullable(),
});

export const ForecastJobSummarySchema = z.object({
  job_id: z.string(),
  status: JobStatusSchema,
  name: z.string().nullable(),
  file_name: z.string().nullable(),
  progress: z.number(),
  message: z.string(),
  created_at: z.string(),
  started_at: z.string().nullable(),
  completed_at: z.string().nullable(),
  error: z.string().nullable(),
  metrics: z.array(ForecastJobMetricSummarySchema),
});

export const ForecastJobListResponseSchema = z.object({
  jobs: z.array(ForecastJobSummarySchema),
  total: z.number(),
});

export const ProgressResponseSchema = z.object({
  job_id: z.string(),
  status: JobStatusSchema,
  progress: z.number(),
  message: z.string(),
});

// ── AI Action Center ─────────────────────────────────────────────────

export const ForecastEditSummarySchema = z.object({
  id: z.string(),
  sequence_no: z.number(),
  instruction_text: z.string(),
  operation_type: z.string(),
  params: z.record(z.unknown()),
  created_at: z.string(),
});

export const ActionCenterStateSchema = z.object({
  records: z.array(ForecastRecordSchema),
  edits: z.array(ForecastEditSummarySchema),
});

export const ExplanationResponseSchema = z.object({
  explanation: z.string(),
});

export const QAResponseSchema = z.object({
  answer: z.string(),
});

// ── generic response wrappers ────────────────────────────────────────

export const SuccessResponseSchema = z.object({
  success: z.literal(true),
  message: z.string(),
  data: z.unknown().optional(),
});

export const ErrorResponseSchema = z.object({
  success: z.literal(false),
  error: z.string(),
  detail: z.string().optional(),
});

export const ApiValidationErrorSchema = z.object({
  detail: z.array(
    z.object({
      loc: z.array(z.union([z.string(), z.number()])),
      msg: z.string(),
      type: z.string(),
    }),
  ),
});
