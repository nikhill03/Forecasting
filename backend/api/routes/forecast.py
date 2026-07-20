"""
backend/api/routes/forecast.py
================================
Forecast job management endpoints.
Replaces: callbacks/processing.py (Dash-specific callback)

Endpoints:
    POST /api/v1/forecast              — submit a forecast job
    GET  /api/v1/forecast/{job_id}     — get job status + results
    GET  /api/v1/forecast/{job_id}/progress — lightweight progress poll
    DELETE /api/v1/forecast/{job_id}   — stop a running job
    Phase 2: jobs submitted to Celery, status tracked in PostgreSQL.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.dependencies import get_current_user_id
from backend.models.db_models import ForecastJob
from backend.models.schemas import (
    ForecastJobResponse,
    ForecastRequest,
    ProgressResponse,
    SuccessResponse,
)
from backend.api.routes.upload import get_upload_content

router = APIRouter(prefix="/forecast", tags=["forecast"])
logger = structlog.get_logger("forecasting.forecast")


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
        progress=job.progress_pct,
        message=job.progress_message or "",
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        results=results,
        error=job.error_message,
    )


@router.post("", response_model=ForecastJobResponse, status_code=202)
async def submit_forecast(
    request: ForecastRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> ForecastJobResponse:
    """Submit a forecast job. Returns immediately with job_id."""
    file_content = get_upload_content(request.upload_id)
    file_content_b64 = base64.b64encode(file_content).decode("utf-8")

    job = ForecastJob(
        id=str(uuid.uuid4()),
        user_id=user_id,
        status="pending",
        progress_pct=0,
        progress_message="Job queued",
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
            args=[job_id, file_content_b64, job.config],
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

    return ProgressResponse(
        job_id=job_id,
        status=job.status,
        progress=job.progress_pct,
        message=job.progress_message or "",
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

    # Write stop flag for thread-based fallback
    import os
    stop_path = os.path.join(os.getcwd(), "outputs", "processing_stop.flag")
    os.makedirs(os.path.dirname(stop_path), exist_ok=True)
    with open(stop_path, "w") as f:
        f.write(f"stopped:{job_id}")

    job.status = "stopped"
    job.completed_at = datetime.now(timezone.utc)
    await db.commit()

    return SuccessResponse(message=f"Stop signal sent to job {job_id}")