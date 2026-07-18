export interface UserRegisterRequest {
  email: string;
  password: string;
  full_name: string;
}

export interface UserLoginRequest {
  email: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: "bearer";
}

export interface UserResponse {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  created_at: string;
}

export interface UploadResponse {
  upload_id: string;
  file_name: string;
  s3_key: string;
  sheets: string[];
  columns: Record<string, string[]>;
  row_counts: Record<string, number>;
  uploaded_at: string;
}

export interface ForecastRequest {
  upload_id: string;
  selected_sheets: string[];
  selected_metrics: string[];
  selected_x_cols?: string[];
  forecast_horizon: number;
  test_window: number;
  selected_regions: string[];
  quantile_level: number;
}

export type DemandType = "Smooth" | "Erratic" | "Intermittent" | "Lumpy";

export interface DemandProfile {
  demand_type: DemandType;
  adi: number;
  cv2: number;
  is_intermittent: boolean;
  is_erratic: boolean;
  recommended_models: string[];
}

export interface ForecastRecord {
  Date: string;
  TrainActual: number | null;
  TrainRaw: number | null;
  TestActual: number | null;
  TestPrediction: number | null;
  Forecast: number | null;
}

export interface MetricResult {
  metric_name: string;
  best_model: string | null;
  wmape: number | null;
  mae: number | null;
  mape: number | null;
  rmse: number | null;
  accuracy: number | null;
  composite_score: number | null;
  demand_profile: DemandProfile | null;
  feature_importance: Record<string, number> | null;
  forecast_bias: number | null;
  records: ForecastRecord[];
}

export interface SheetResult {
  sheet_name: string;
  metrics: Record<string, MetricResult>;
}

export type JobStatus =
  | "pending"
  | "running"
  | "success"
  | "failed"
  | "stopped";

export interface ForecastJobResponse {
  job_id: string;
  status: JobStatus;
  progress: number;
  message: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  results: Record<string, SheetResult> | null;
  error: string | null;
}

export interface ProgressResponse {
  job_id: string;
  status: JobStatus;
  progress: number;
  message: string;
}

export interface SuccessResponse {
  success: true;
  message: string;
  data?: unknown;
}

export interface ErrorResponse {
  success: false;
  error: string;
  detail?: string;
}

export interface ApiValidationError {
  detail: Array<{
    loc: (string | number)[];
    msg: string;
    type: string;
  }>;
}