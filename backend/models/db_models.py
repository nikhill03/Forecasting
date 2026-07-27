"""
backend/models/db_models.py
============================
SQLAlchemy ORM models.

Tables:
  users         — registered user accounts
  uploads       — one row per uploaded file
  forecast_jobs — one row per forecast run
  model_runs    — one row per metric per job
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, DateTime, Float,
    ForeignKey, Integer, String, Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from backend.core.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


# ── users ─────────────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    jobs: Mapped[list["ForecastJob"]] = relationship(
        "ForecastJob", back_populates="user", lazy="select"
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email}>"


# ── forecast_jobs ─────────────────────────────────────────────────────
class ForecastJob(Base):
    __tablename__ = "forecast_jobs"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True
    )
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    s3_input_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    s3_output_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    progress_pct: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    progress_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["User | None"] = relationship("User", back_populates="jobs")
    model_runs: Mapped[list["ModelRun"]] = relationship(
        "ModelRun", back_populates="job",
        lazy="select", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<ForecastJob id={self.id} status={self.status}>"


# ── uploads ───────────────────────────────────────────────────────────
class Upload(Base):
    __tablename__ = "uploads"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    s3_key: Mapped[str] = mapped_column(String(500), nullable=False)
    sheets: Mapped[list] = mapped_column(JSONB, nullable=False)
    columns: Mapped[dict] = mapped_column(JSONB, nullable=False)
    row_counts: Mapped[dict] = mapped_column(JSONB, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # No relationship back to User (unlike ForecastJob.user/User.jobs) —
    # every query touching this table is owner-scoped directly by
    # user_id, nothing traverses .user or needs user.uploads.

    def __repr__(self) -> str:
        return f"<Upload id={self.id} file_name={self.file_name}>"


# ── model_runs ────────────────────────────────────────────────────────
class ModelRun(Base):
    __tablename__ = "model_runs"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    job_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("forecast_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sheet_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metric_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    stage: Mapped[str | None] = mapped_column(String(20), nullable=True)
    wmape: Mapped[float | None] = mapped_column(Float, nullable=True)
    mae: Mapped[float | None] = mapped_column(Float, nullable=True)
    mape: Mapped[float | None] = mapped_column(Float, nullable=True)
    rmse: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    composite_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    demand_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    adi: Mapped[float | None] = mapped_column(Float, nullable=True)
    cv2: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    job: Mapped["ForecastJob"] = relationship(
        "ForecastJob", back_populates="model_runs"
    )

    def __repr__(self) -> str:
        return f"<ModelRun job={self.job_id} metric={self.metric_name} model={self.model_name}>"


# ── forecast_edits ────────────────────────────────────────────────────
# The AI Action Center's persisted operation stack (feature-update.md
# Feature 2). One row per applied operation, ordered by sequence_no within
# (job_id, sheet_name, metric_name). Revert = delete the latest row for that
# scope and replay the remainder from baseline — see
# backend/services/forecast_edits.py.
class ForecastEdit(Base):
    __tablename__ = "forecast_edits"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    job_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("forecast_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    sheet_name: Mapped[str] = mapped_column(String(255), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(255), nullable=False)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    instruction_text: Mapped[str] = mapped_column(Text, nullable=False)
    operation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    affected_points_before: Mapped[list] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return (
            f"<ForecastEdit job={self.job_id} {self.sheet_name}/{self.metric_name} "
            f"#{self.sequence_no} {self.operation_type}>"
        )