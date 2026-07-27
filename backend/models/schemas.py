"""
backend/models/schemas.py
==========================
Pydantic v2 request and response schemas for all API endpoints.
These are the data contracts between the frontend and backend.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
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


class ColumnInfo(BaseModel):
    name        : str
    dtype       : str
    is_numeric  : bool
    null_count  : int
    sample_vals : List[Any]


# ══════════════════════════════════════════════════════════════════
# FORECAST SCHEMAS
# ══════════════════════════════════════════════════════════════════

class ForecastRequest(BaseModel):
    upload_id        : str
    selected_sheets  : List[str]
    selected_metrics : List[str]
    selected_x_cols  : Optional[List[str]] = None
    forecast_horizon : int = Field(default=60, ge=1, le=365)
    test_window      : int = Field(default=30, ge=7, le=180)
    selected_regions : List[str] = ["US", "IN"]
    quantile_level   : float = Field(default=0.75, ge=0.5, le=0.99)

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


class DemandProfileSchema(BaseModel):
    demand_type        : str
    adi                : float
    cv2                : float
    is_intermittent    : bool
    is_erratic         : bool
    recommended_models : List[str]


class ModelRunResult(BaseModel):
    model_name    : str
    stage         : str          # "Univariate" | "Multivariate"
    wmape         : Optional[float]
    mae           : Optional[float]
    mape          : Optional[float]
    rmse          : Optional[float]
    accuracy      : Optional[float]
    composite_score: Optional[float]
    demand_profile : Optional[DemandProfileSchema]


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
    records: List[ForecastRecord] = []


class SheetResult(BaseModel):
    sheet_name: Optional[str] = None
    metrics: Dict[str, MetricResult] = {}


class ForecastJobResponse(BaseModel):
    model_config = {"extra": "ignore"}  

    job_id: str
    status: str
    progress: int
    message: str
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    results: Optional[Dict[str, SheetResult]] = None
    error: Optional[str] = None


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