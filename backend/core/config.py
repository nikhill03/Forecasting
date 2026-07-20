"""
backend/core/config.py
=======================
Centralised application configuration via Pydantic Settings.

All environment variables are validated at startup — the app will
refuse to start if required variables are missing or invalid.
This replaces the scattered os.getenv() calls in v1.0.

Usage:
    from backend.core.config import settings
    print(settings.DATABASE_URL)
"""

from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import AnyHttpUrl, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables / .env file.
    All fields are validated at import time — fail fast, fail loud.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",        # silently ignore unknown env vars
    )

    # ── App ───────────────────────────────────────────────────────
    APP_ENV       : str  = "development"
    APP_HOST      : str  = "0.0.0.0"
    APP_PORT      : int  = 8000
    DEBUG         : bool = False
    PROJECT_NAME  : str  = "Forecasting Platform"
    API_V1_PREFIX : str  = "/api/v1"

    # ── Security ──────────────────────────────────────────────────
    SECRET_KEY                   : str
    ACCESS_TOKEN_EXPIRE_MINUTES  : int = 30
    REFRESH_TOKEN_EXPIRE_DAYS    : int = 7
    ALGORITHM                    : str = "HS256"

    @field_validator("SECRET_KEY")
    @classmethod
    def secret_key_min_length(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters")
        return v

    # ── Database ──────────────────────────────────────────────────
    DATABASE_URL          : str
    DATABASE_POOL_SIZE    : int = 10
    DATABASE_MAX_OVERFLOW : int = 20

    # ── Redis / Celery ────────────────────────────────────────────
    REDIS_URL              : str = "redis://localhost:6379/0"
    CELERY_BROKER_URL      : str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND  : str = "redis://localhost:6379/2"

    # ── Rate Limiting ─────────────────────────────────────────────
    RATE_LIMIT_AUTH : str = "5/minute"   # shared by /auth/login and /auth/register

    # ── AWS ───────────────────────────────────────────────────────
    AWS_ACCESS_KEY_ID     : str = ""
    AWS_SECRET_ACCESS_KEY : str = ""
    AWS_DEFAULT_REGION    : str = "us-east-1"
    S3_BUCKET_NAME        : str = ""
    S3_UPLOAD_PREFIX      : str = "uploads/"
    S3_OUTPUT_PREFIX      : str = "outputs/"

    # ── LLM ───────────────────────────────────────────────────────
    HF_TOKEN      : str = ""
    LLM_MODEL_ID  : str = "Qwen/Qwen2.5-Coder-32B-Instruct"

    # ── CORS ──────────────────────────────────────────────────────
    CORS_ORIGINS : List[str] = ["http://localhost:5173", "http://localhost:3000"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        """Accept either a list or a comma-separated string."""
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    # ── Forecasting Defaults ──────────────────────────────────────
    DEFAULT_FORECAST_HORIZON : int   = 60
    DEFAULT_TEST_WINDOW      : int   = 30
    MAX_UPLOAD_SIZE_MB       : int   = 50

    @property
    def MAX_UPLOAD_SIZE_BYTES(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def is_development(self) -> bool:
        return self.APP_ENV == "development"


@lru_cache
def get_settings() -> Settings:
    """
    Returns a cached Settings instance.
    lru_cache ensures Settings is only instantiated once per process.
    Use get_settings() as a FastAPI dependency for testability.
    """
    return Settings()


# Module-level singleton for non-DI usage
settings = get_settings()