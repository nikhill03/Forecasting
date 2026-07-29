import type { z } from "zod";
import type {
  ActionCenterStateSchema,
  ApiValidationErrorSchema,
  DemandProfileSchema,
  DemandTypeSchema,
  ErrorResponseSchema,
  ExplanationResponseSchema,
  ForecastEditSummarySchema,
  ForecastJobListResponseSchema,
  ForecastJobMetricSummarySchema,
  ForecastJobResponseSchema,
  ForecastJobSummarySchema,
  ForecastRecordSchema,
  ForecastRequestSchema,
  JobStatusSchema,
  MetricResultSchema,
  ProgressResponseSchema,
  QAResponseSchema,
  SheetResultSchema,
  SuccessResponseSchema,
  TokenResponseSchema,
  UploadResponseSchema,
  UserLoginRequestSchema,
  UserRegisterRequestSchema,
  UserResponseSchema,
} from "./api.schemas";

// Types are inferred from the Zod schemas in `api.schemas.ts`, which are the
// single source of truth for the API contract — never hand-write a duplicate
// interface here.

export type UserRegisterRequest = z.infer<typeof UserRegisterRequestSchema>;
export type UserLoginRequest = z.infer<typeof UserLoginRequestSchema>;
export type TokenResponse = z.infer<typeof TokenResponseSchema>;
export type UserResponse = z.infer<typeof UserResponseSchema>;

export type UploadResponse = z.infer<typeof UploadResponseSchema>;

export type ForecastRequest = z.infer<typeof ForecastRequestSchema>;

export type DemandType = z.infer<typeof DemandTypeSchema>;
export type DemandProfile = z.infer<typeof DemandProfileSchema>;
export type ForecastRecord = z.infer<typeof ForecastRecordSchema>;
export type MetricResult = z.infer<typeof MetricResultSchema>;
export type SheetResult = z.infer<typeof SheetResultSchema>;

export type JobStatus = z.infer<typeof JobStatusSchema>;
export type ForecastJobResponse = z.infer<typeof ForecastJobResponseSchema>;

export type ForecastJobMetricSummary = z.infer<
  typeof ForecastJobMetricSummarySchema
>;
export type ForecastJobSummary = z.infer<typeof ForecastJobSummarySchema>;
export type ForecastJobListResponse = z.infer<
  typeof ForecastJobListResponseSchema
>;

export type ProgressResponse = z.infer<typeof ProgressResponseSchema>;

export type ForecastEditSummary = z.infer<typeof ForecastEditSummarySchema>;
export type ActionCenterState = z.infer<typeof ActionCenterStateSchema>;

export type ExplanationResponse = z.infer<typeof ExplanationResponseSchema>;

export type QAResponse = z.infer<typeof QAResponseSchema>;

export type SuccessResponse = z.infer<typeof SuccessResponseSchema>;
export type ErrorResponse = z.infer<typeof ErrorResponseSchema>;

export type ApiValidationError = z.infer<typeof ApiValidationErrorSchema>;
