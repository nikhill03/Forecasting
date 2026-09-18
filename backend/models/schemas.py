"""
backend/models/schemas.py
==========================
Pydantic v2 request and response schemas for all API endpoints.
These are the data contracts between the frontend and backend.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


# ══════════════════════════════════════════════════════════════════
# AUTH SCHEMAS
# ══════════════════════════════════════════════════════════════════

class UserRegisterRequest(BaseModel):
    email     : EmailStr
    password  : str = Field(min_length=8, max_length=100)
    full_name : str = Field(min_length=1, max_length=255)

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        return v


class UserLoginRequest(BaseModel):
    email    : EmailStr
    password : str


class TokenResponse(BaseModel):
    access_token  : str
    refresh_token : str
    token_type    : str = "bearer"


class UserResponse(BaseModel):
    id         : UUID
    email      : str
    full_name  : str
    is_active  : bool
    created_at : datetime

    model_config = {"from_attributes": True}


# ══════════════════════════════════════════════════════════════════
# UPLOAD SCHEMAS
# ══════════════════════════════════════════════════════════════════

class UploadResponse(BaseModel):
    upload_id   : str          # UUID for this upload session
    file_name   : str
    s3_key      : str          # Phase 2: S3 object key
    sheets      : List[str]    # available sheet names
    columns     : Dict[str, List[str]]  # sheet -> column names
    row_counts  : Dict[str, int]        # sheet -> row count
    uploaded_at : datetime


class SampleDatasetResponse(BaseModel):
    """One built-in onboarding dataset, as advertised by GET /upload/samples.

    Mirrors backend.services.sample_datasets.SampleDataset. `demand_class`
    is the quadrant the series is expected to classify into — it is what
    lets the UI show the contrast between samples before a run happens.
    """

    id           : str
    title        : str
    description  : str
    demand_class : str
    file_name    : str
    frequency    : str
    row_count    : int
    columns      : List[str]


class SampleListResponse(BaseModel):
    samples : List[SampleDatasetResponse]


class ColumnInfo(BaseModel):
    name        : str
    dtype       : str
    is_numeric  : bool
    null_count  : int
    sample_vals : List[Any]


# ══════════════════════════════════════════════════════════════════
# FORECAST SCHEMAS
# ══════════════════════════════════════════════════════════════════

class SeriesSelection(BaseModel):
    """Which series a run covers and how it's evaluated. Shared by
    ForecastRequest and QualityReportRequest (F16) so the configure-time
    report is always requested with exactly the bounds a submit enforces."""

    selected_sheets  : List[str]
    selected_metrics : List[str]
    forecast_horizon : int = Field(default=60, ge=1, le=365)
    test_window      : int = Field(default=30, ge=7, le=180)

    @field_validator("selected_sheets")
    @classmethod
    def sheets_not_empty(cls, v):
        if not v:
            raise ValueError("At least one sheet must be selected")
        return v

    @field_validator("selected_metrics")
    @classmethod
    def metrics_not_empty(cls, v):
        if not v:
            raise ValueError("At least one metric must be selected")
        return v


class ForecastRequest(SeriesSelection):
    upload_id        : str
    selected_x_cols  : Optional[List[str]] = None
    selected_regions : List[str] = ["US", "IN"]
    quantile_level   : float = Field(default=0.75, ge=0.5, le=0.99)


# ══════════════════════════════════════════════════════════════════
# DATA QUALITY SCHEMAS (F16)
# ══════════════════════════════════════════════════════════════════

QualityIssueCode = Literal[
    "insufficient_history",
    "metric_missing_in_sheet",
    "unparseable_dates",
    "non_numeric_values",
    "duplicate_timestamps",
    "non_daily_frequency",
    "date_gaps",
    "negative_values",
    "outliers",
    "horizon_capped",
    "sparse_test_window",
    "short_history",
]


class QualityReportRequest(SeriesSelection):
    pass


class QualityIssue(BaseModel):
    code     : QualityIssueCode
    severity : Literal["blocking", "warning"]
    message  : str


class SeriesQuality(BaseModel):
    """One (sheet, metric) series as the pipeline will see it. Mirrors the
    dict built by services/data_quality.profile_series."""

    sheet                : str
    metric               : str
    rows_total           : int
    usable_points        : int
    start                : Optional[datetime] = None
    end                  : Optional[datetime] = None
    span_days            : Optional[int] = None
    inferred_frequency   : Optional[str] = None
    imputed_pct          : Optional[float] = None
    duplicate_timestamps : int
    unparseable_dates    : int
    non_numeric_values   : int
    negative_values      : int
    zero_pct             : float
    outliers             : int
    test_split_size      : int
    effective_horizon    : int
    issues               : List[QualityIssue] = []


class DataQualityReport(BaseModel):
    generated_at : datetime
    has_blocking : bool
    series       : List[SeriesQuality] = []
    issues       : List[QualityIssue] = []


class DemandProfileSchema(BaseModel):
    demand_type        : str
    adi                : float
    cv2                : float
    is_intermittent    : bool
    is_erratic         : bool
    recommended_models : List[str]


class ModelRunResult(BaseModel):
    """One competitor in a metric's leaderboard (F14).

    A run trains many models and scores each; before F14 only the winner
    survived. `status` is what separates a model that lost from one that
    never produced a score, so a scoreless row is never ambiguous.
    """

    model_name    : str
    stage         : str          # "Univariate" | "Multivariate"
    wmape         : Optional[float] = None
    mae           : Optional[float] = None
    mape          : Optional[float] = None
    rmse          : Optional[float] = None
    accuracy      : Optional[float] = None
    composite_score: Optional[float] = None
    demand_profile : Optional[DemandProfileSchema] = None
    is_champion   : bool = False
    status        : str = "completed"   # completed | failed | skipped
    error_message : Optional[str] = None


class ForecastRecord(BaseModel):
    Date            : datetime
    TrainActual     : Optional[float]
    TrainRaw        : Optional[float]
    TestActual      : Optional[float]
    TestPrediction  : Optional[float]
    Forecast        : Optional[float]


class MetricResult(BaseModel):
    metric_name: Optional[str] = None
    best_model: Optional[str] = None
    wmape: Optional[float] = None
    mae: Optional[float] = None
    mape: Optional[float] = None
    rmse: Optional[float] = None
    accuracy: Optional[float] = None
    composite_score: Optional[float] = None
    demand_profile: Optional[DemandProfileSchema] = None
    feature_importance: Optional[Dict[str, float]] = None
    forecast_bias: Optional[float] = None
    # Every model tried for this metric, champion included. Rides along on
    # the existing job fetch so the results page needs no second request.
    # Pydantic v2 ignores extra keys, so this field is what stops the
    # pipeline's model_leaderboard from being silently dropped here.
    model_leaderboard: List[ModelRunResult] = []
    records: List[ForecastRecord] = []


class SheetResult(BaseModel):
    sheet_name: Optional[str] = None
    metrics: Dict[str, MetricResult] = {}


class ForecastJobResponse(BaseModel):
    model_config = {"extra": "ignore"}  

    job_id: str
    status: str
    name: Optional[str] = None
    progress: int
    message: str
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    results: Optional[Dict[str, SheetResult]] = None
    error: Optional[str] = None
    # F16: the caveats the run was built on. None for jobs created before
    # the report existed — the UI says so rather than rendering nothing.
    quality_report: Optional[DataQualityReport] = None


class ProgressResponse(BaseModel):
    job_id   : str
    status   : str
    progress : int
    message  : str


class ForecastJobMetricSummary(BaseModel):
    sheet_name : Optional[str]
    metric_name: Optional[str]
    model_name : Optional[str]
    wmape      : Optional[float]


class ForecastJobSummary(BaseModel):
    """Lightweight per-job row for the job history list — deliberately
    excludes the full `results` payload (records/figures), which can be
    large and isn't needed until the user drills into one job."""

    job_id       : str
    status       : str
    name         : Optional[str] = None
    file_name    : Optional[str]
    progress     : int
    message      : str
    created_at   : datetime
    started_at   : Optional[datetime]
    completed_at : Optional[datetime]
    error        : Optional[str] = None
    metrics      : list[ForecastJobMetricSummary] = []


class ForecastJobListResponse(BaseModel):
    jobs : list[ForecastJobSummary]
    total: int


class RenameJobRequest(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        if len(v) > 255:
            raise ValueError("name must be 255 characters or fewer")
        return v


# ══════════════════════════════════════════════════════════════════
# DASHBOARD SCHEMAS (F15)
# ══════════════════════════════════════════════════════════════════

class StatusCounts(BaseModel):
    success : int = 0
    failed  : int = 0
    stopped : int = 0
    running : int = 0
    pending : int = 0


class RecentRun(BaseModel):
    """One of the user's newest jobs, any status.

    `champion_model` is the winner of the run's first metric (by sheet, then
    metric name); `metric_count` says how many metrics the run has, so the UI
    can show "Prophet +2" rather than pretend a multi-metric run had one winner.
    """

    job_id         : str
    name           : Optional[str] = None
    file_name      : Optional[str] = None
    status         : str
    created_at     : datetime
    champion_model : Optional[str] = None
    metric_count   : int = 0
    wmape          : Optional[float] = None


class TrendPoint(BaseModel):
    job_id     : str
    created_at : datetime
    wmape      : float


class DemandMix(BaseModel):
    """Distinct series per demand quadrant. Keys match DemandType so the
    frontend can index by it directly."""

    Smooth       : int = 0
    Erratic      : int = 0
    Intermittent : int = 0
    Lumpy        : int = 0
    unclassified : int = 0


class ActiveRun(BaseModel):
    """A pending or running job. Live progress is not stored here — the
    database only records progress at start and finish — so the client polls
    GET /forecast/{job_id}/progress per row."""

    job_id     : str
    name       : Optional[str] = None
    file_name  : Optional[str] = None
    status     : str
    created_at : datetime
    started_at : Optional[datetime] = None


class RunDuration(BaseModel):
    job_id           : str
    name             : Optional[str] = None
    file_name        : Optional[str] = None
    created_at       : datetime
    duration_seconds : float


class ModelWin(BaseModel):
    model_name : str
    wins       : int


class DashboardSummary(BaseModel):
    """Everything the dashboard shows, from one owner-scoped request.

    success_rate       = success / (success + failed); None when nothing has
                         finished. Stopped, pending and running are excluded.
    median_wmape       = median of per-run WMAPE over accuracy_trend's window.
    median_run_seconds = median duration of the newest successful runs.
    model_wins         = champion counts per model, every run-metric counted.
    """

    total_runs         : int
    status_counts      : StatusCounts
    success_rate       : Optional[float] = None
    median_wmape       : Optional[float] = None
    last_run_at        : Optional[datetime] = None
    recent_runs        : List[RecentRun] = []
    accuracy_trend     : List[TrendPoint] = []
    demand_mix         : DemandMix
    active_runs        : List[ActiveRun] = []
    median_run_seconds : Optional[float] = None
    slowest_runs       : List[RunDuration] = []
    model_wins         : List[ModelWin] = []


# ══════════════════════════════════════════════════════════════════
# AI ACTION CENTER SCHEMAS (feature-update.md Feature 2)
# ══════════════════════════════════════════════════════════════════

class ForecastEditSummary(BaseModel):
    id               : str
    sequence_no      : int
    instruction_text : str
    operation_type   : str
    params           : Dict[str, Any]
    created_at       : datetime


class ActionCenterState(BaseModel):
    records: List[ForecastRecord]
    edits  : List[ForecastEditSummary]


class ApplyActionRequest(BaseModel):
    sheet_name       : str
    metric_name      : str
    instruction_text : str = Field(min_length=1, max_length=500)


class RevertActionRequest(BaseModel):
    sheet_name : str
    metric_name: str


# ══════════════════════════════════════════════════════════════════
# UNDERSTANDABILITY + Q&A SCHEMAS (feature-update.md Feature 3)
# ══════════════════════════════════════════════════════════════════

class ExplanationResponse(BaseModel):
    explanation: str


class QARequest(BaseModel):
    sheet_name : str
    metric_name: str
    question   : str = Field(min_length=1, max_length=500)


class QAResponse(BaseModel):
    answer: str


# ══════════════════════════════════════════════════════════════════
# GENERIC RESPONSE WRAPPERS
# ══════════════════════════════════════════════════════════════════

class SuccessResponse(BaseModel):
    success : bool = True
    message : str
    data    : Optional[Any] = None


class ErrorResponse(BaseModel):
    success : bool = False
    error   : str
    detail  : Optional[str] = None