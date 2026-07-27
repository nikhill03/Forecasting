"""
backend/api/routes/forecast.py
================================
Forecast job management endpoints.
Replaces: callbacks/processing.py (Dash-specific callback)

Endpoints:
    POST /api/v1/forecast              — submit a forecast job
    GET  /api/v1/forecast              — list your past forecast jobs
    GET  /api/v1/forecast/{job_id}     — get job status + results
    GET  /api/v1/forecast/{job_id}/progress — lightweight progress poll
    DELETE /api/v1/forecast/{job_id}   — stop a running job
    Phase 2: jobs submitted to Celery, status tracked in PostgreSQL.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

import redis
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.dependencies import get_current_user_id, parse_uuid_or_404
from backend.models.db_models import ForecastJob, ModelRun, Upload
from backend.models.schemas import (
    ForecastJobListResponse,
    ForecastJobResponse,
    ForecastJobSummary,
    ForecastJobMetricSummary,
    ForecastRequest,
    ProgressResponse,
    RenameJobRequest,
    SuccessResponse,
)

router = APIRouter(prefix="/forecast", tags=["forecast"])
logger = structlog.get_logger("forecasting.forecast")

# Job-scoped stop signal — one key per job so DELETE on job A can never
# affect job B's running worker (the F5 "global stop flag" defect).
_STOP_KEY_TTL = 3600  # matches run_forecast's Celery time_limit
_REDIS_RETRY_COOLDOWN_SECONDS = 30
_redis_client = None
_redis_retry_at: float | None = None


def _get_redis_client():
    """Lazily construct a redis client, same defensive shape as
    services/processing_engine.py's — never raises, since a misconfigured
    or unreachable Redis (including the test suite's REDIS_URL=memory://,
    which redis-py cannot parse) must not crash module import. A
    construction failure is retried after a cooldown rather than latched
    forever — a permanent latch would mean one transient error
    permanently 503s every future DELETE in this process."""
    global _redis_client, _redis_retry_at
    if _redis_retry_at is not None and time.time() < _redis_retry_at:
        return None
    if _redis_client is None:
        try:
            _redis_client = redis.Redis.from_url(
                settings.REDIS_URL, socket_connect_timeout=1, socket_timeout=1
            )
            _redis_retry_at = None
        except Exception:
            _redis_retry_at = time.time() + _REDIS_RETRY_COOLDOWN_SECONDS
            return None
    return _redis_client


def _normalize_results(results: dict | None) -> dict | None:
    """Normalize processing_engine output format to API schema format."""
    if not results:
        return results
    normalized = {}
    for sheet_name, sheet_data in results.items():
        if isinstance(sheet_data, dict) and "metrics" in sheet_data:
            # Already has metrics key — just add sheet_name and fix metric_name fields
            normalized[sheet_name] = {
                "sheet_name": sheet_name,
                "metrics": {
                    metric_name: {
                        "metric_name": metric_name,
                        **{k: v for k, v in metric_data.items() if k != "records"},
                        "records": metric_data.get("records", []),
                    }
                    for metric_name, metric_data in sheet_data["metrics"].items()
                    if isinstance(metric_data, dict)
                },
            }
        elif isinstance(sheet_data, dict):
            normalized[sheet_name] = {
                "sheet_name": sheet_name,
                "metrics": {
                    metric_name: {
                        "metric_name": metric_name,
                        **{k: v for k, v in metric_data.items() if k != "records"},
                        "records": metric_data.get("records", []),
                    }
                    for metric_name, metric_data in sheet_data.items()
                    if isinstance(metric_data, dict)
                },
            }
        else:
            normalized[sheet_name] = sheet_data
    return normalized


def _read_json_file(path: str) -> dict | None:
    """Sync helper — run via asyncio.to_thread so callers don't block the event loop."""
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


async def _read_live_progress(job_id: str) -> dict | None:
    """Reads the per-job progress.json that services/processing_engine.py's
    _emit_status() writes stage-by-stage (job-scoped path — safe under
    concurrent jobs). Returns None if the file doesn't exist yet (job just
    started) or fails to parse — callers should fall back to the DB columns
    in that case, never raise."""
    path = os.path.join("outputs", "predictions", job_id, "progress.json")
    try:
        return await asyncio.to_thread(_read_json_file, path)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("job_live_progress_load_failed", job_id=job_id, error=str(exc))
        return None


async def _job_to_response(job: ForecastJob) -> ForecastJobResponse:
    """Convert ORM object to response schema."""
    results = None
    if job.status == "success":
        if job.s3_output_key and job.s3_output_key.startswith("local:"):
            path = job.s3_output_key.replace("local:", "")
            try:
                raw = await asyncio.to_thread(_read_json_file, path)
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning(
                    "job_results_load_failed", job_id=job.id, error=str(exc)
                )
                raw = None
            if raw is not None:
                results = _normalize_results(raw)
        elif job.s3_output_key:
            try:
                from backend.storage.s3_client import download_json
                raw = await download_json(job.s3_output_key)
                results = _normalize_results(raw)
            except Exception as exc:
                logger.warning(
                    "job_results_load_failed", job_id=job.id, error=str(exc)
                )
                results = None
        else:
            # No job-scoped storage location recorded. The only remaining
            # source would be the single global outputs/predictions/
            # predictions_all.json file shared by every job on the box
            # (the F5 "concurrent jobs overwrite each other" defect) —
            # reading it here would leak another tenant's forecast output
            # through this job's own, correctly-authorized job_id. Return
            # no results rather than risk a cross-tenant data leak; F5
            # (job-scoped artifacts) is what makes this branch safe to
            # populate again.
            pass

    return ForecastJobResponse(
        job_id=job.id,
        status=job.status,
        name=job.name,
        progress=job.progress_pct,
        message=job.progress_message or "",
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        results=results,
        error=job.error_message,
    )


@router.get("", response_model=ForecastJobListResponse)
async def list_jobs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> ForecastJobListResponse:
    """Paginated job history for the current user, newest first. Returns
    lightweight per-metric summaries from model_runs (best model + WMAPE),
    not the full results payload — that's only fetched when a specific job
    is opened via GET /forecast/{job_id}."""
    count_result = await db.execute(
        select(func.count())
        .select_from(ForecastJob)
        .where(ForecastJob.user_id == user_id)
    )
    total = count_result.scalar_one()

    jobs_result = await db.execute(
        select(ForecastJob)
        .where(ForecastJob.user_id == user_id)
        .order_by(ForecastJob.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    jobs = jobs_result.scalars().all()

    metrics_by_job: Dict[str, list[ForecastJobMetricSummary]] = {}
    job_ids = [j.id for j in jobs]
    if job_ids:
        runs_result = await db.execute(
            select(ModelRun)
            .where(ModelRun.job_id.in_(job_ids))
            .order_by(ModelRun.created_at.asc())
        )
        for run in runs_result.scalars().all():
            metrics_by_job.setdefault(run.job_id, []).append(
                ForecastJobMetricSummary(
                    sheet_name=run.sheet_name,
                    metric_name=run.metric_name,
                    model_name=run.model_name,
                    wmape=run.wmape,
                )
            )

    return ForecastJobListResponse(
        jobs=[
            ForecastJobSummary(
                job_id=job.id,
                status=job.status,
                name=job.name,
                file_name=job.file_name,
                progress=job.progress_pct,
                message=job.progress_message or "",
                created_at=job.created_at,
                started_at=job.started_at,
                completed_at=job.completed_at,
                error=job.error_message,
                metrics=metrics_by_job.get(job.id, []),
            )
            for job in jobs
        ],
        total=total,
    )


@router.post("", response_model=ForecastJobResponse, status_code=202)
async def submit_forecast(
    request: ForecastRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> ForecastJobResponse:
    """Submit a forecast job. Returns immediately with job_id."""
    parse_uuid_or_404(request.upload_id, "Upload")

    result = await db.execute(
        select(Upload).where(
            Upload.id == request.upload_id, Upload.user_id == user_id
        )
    )
    upload = result.scalar_one_or_none()
    if not upload:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Upload '{request.upload_id}' not found",
        )

    job = ForecastJob(
        id=str(uuid.uuid4()),
        user_id=user_id,
        status="pending",
        file_name=upload.file_name,
        progress_pct=0,
        progress_message="Job queued",
        s3_input_key=upload.s3_key,
        config={
            "upload_id"       : request.upload_id,
            "selected_sheets" : request.selected_sheets,
            "selected_metrics": request.selected_metrics,
            "selected_x_cols" : request.selected_x_cols,
            "forecast_horizon": request.forecast_horizon,
            "test_window"     : request.test_window,
            "selected_regions": request.selected_regions,
            "quantile_level"  : request.quantile_level,
        },
        created_at=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.flush()
    job_id = job.id

    try:
        from backend.tasks.forecast_task import run_forecast
        task = run_forecast.apply_async(
            args=[job_id, upload.s3_key, job.config],
            queue="forecasts",
        )
    except Exception:
        logger.error("forecast_enqueue_failed", job_id=job_id, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Forecast queue unavailable",
        )

    job.celery_task_id = task.id
    await db.commit()
    await db.refresh(job)

    return ForecastJobResponse(
        job_id=job_id,
        status="pending",
        progress=0,
        message="Job submitted successfully",
        created_at=job.created_at,
        started_at=None,
        completed_at=None,
    )


@router.get("/{job_id}/progress", response_model=ProgressResponse)
async def get_progress(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> ProgressResponse:
    result = await db.execute(
        select(ForecastJob).where(
            ForecastJob.id == job_id, ForecastJob.user_id == user_id
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    progress = job.progress_pct
    message = job.progress_message or ""

    # The DB columns are only written once at job start and once at
    # completion — services/processing_engine.py emits much more granular,
    # real-time stage updates to a per-job progress.json in between. Prefer
    # that while the job is actually running; the DB is authoritative once
    # terminal (success/failed/stopped already carry their final message).
    if job.status == "running":
        live = await _read_live_progress(job_id)
        if live is not None:
            progress = live.get("percent", progress)
            message = live.get("message", message)

    return ProgressResponse(
        job_id=job_id,
        status=job.status,
        progress=progress,
        message=message,
    )


@router.get("/{job_id}", response_model=ForecastJobResponse)
async def get_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> ForecastJobResponse:
    result = await db.execute(
        select(ForecastJob).where(
            ForecastJob.id == job_id, ForecastJob.user_id == user_id
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    return await _job_to_response(job)


@router.patch("/{job_id}", response_model=ForecastJobResponse)
async def rename_job(
    job_id: str,
    request: RenameJobRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> ForecastJobResponse:
    """Renames a job. Touches only the `name` column — never the run's
    config, status, or stored results."""
    result = await db.execute(
        select(ForecastJob).where(
            ForecastJob.id == job_id, ForecastJob.user_id == user_id
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    job.name = request.name
    await db.commit()
    await db.refresh(job)

    return await _job_to_response(job)


@router.delete("/{job_id}", response_model=SuccessResponse)
async def stop_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> SuccessResponse:
    result = await db.execute(
        select(ForecastJob).where(
            ForecastJob.id == job_id, ForecastJob.user_id == user_id
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    if job.status not in ("pending", "running"):
        raise HTTPException(
            status_code=409,
            detail=f"Job already in terminal state: {job.status}",
        )

    # Revoke Celery task if running
    if job.celery_task_id:
        try:
            from backend.tasks.celery_app import celery_app
            celery_app.control.revoke(job.celery_task_id, terminate=True)
        except Exception:
            pass

    # Signal the per-job stop key so only this job's worker observes it —
    # a shared/global flag would stop every other running job too (F5).
    def _set_stop_key() -> None:
        client = _get_redis_client()
        if client is None:
            raise redis.exceptions.RedisError("Redis client unavailable")
        client.set(f"dmc:stop:{job_id}", "1", ex=_STOP_KEY_TTL)

    try:
        await asyncio.to_thread(_set_stop_key)
    except redis.exceptions.RedisError:
        logger.error("stop_signal_failed", job_id=job_id, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stop signal unavailable",
        )

    job.status = "stopped"
    job.completed_at = datetime.now(timezone.utc)
    await db.commit()

    return SuccessResponse(message=f"Stop signal sent to job {job_id}")