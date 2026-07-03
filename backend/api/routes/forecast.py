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

import base64
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.dependencies import get_optional_user_id
from backend.models.db_models import ForecastJob
from backend.models.schemas import (
    ForecastJobResponse,
    ForecastRequest,
    ProgressResponse,
    SuccessResponse,
)
from backend.api.routes.upload import get_upload_content

router = APIRouter(prefix="/forecast", tags=["forecast"])


def _normalize_results(results: dict | None) -> dict | None:
    """Normalize processing_engine output format to API schema format."""
    if not results:
        return results
    normalized = {}
    for sheet_name, sheet_data in results.items():
        if isinstance(sheet_data, dict) and "metrics" not in sheet_data:
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


async def _job_to_response(job: ForecastJob) -> ForecastJobResponse:
    """Convert ORM object to response schema."""
    results = None
    if job.status == "success" and job.s3_output_key:
        try:
            from backend.storage.s3_client import download_json
            raw = await download_json(job.s3_output_key)
            results = _normalize_results(raw)
        except Exception:
            results = None

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
    user_id: str | None = Depends(get_optional_user_id),
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
        job.celery_task_id = task.id
        await db.commit()
        await db.refresh(job)
    except Exception:
        # Celery not running — fall back to thread (Phase 1 behaviour)
        import threading
        await db.commit()

        def _run_thread():
            import asyncio
            from services.processing_engine import processing_worker

            file_str = f"data:application/octet-stream;base64,{file_content_b64}"
            try:
                processing_worker(
                    file_contents_norm   = file_str,
                    selected_sheets_list = request.selected_sheets,
                    selected_metrics     = request.selected_metrics,
                    selected_x_cols      = request.selected_x_cols,
                    forecast_horizon     = request.forecast_horizon,
                    test_window          = request.test_window,
                    selected_regions     = request.selected_regions,
                )
                asyncio.run(_update_db_success(job_id))
            except Exception as e:
                asyncio.run(_update_db_error(job_id, str(e)))

        threading.Thread(target=_run_thread, daemon=True).start()

    return ForecastJobResponse(
        job_id=job_id,
        status="pending",
        progress=0,
        message="Job submitted successfully",
        created_at=job.created_at,
        started_at=None,
        completed_at=None,
    )


async def _update_db_success(job_id: str):
    from backend.core.database import AsyncSessionLocal
    import json, os
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ForecastJob).where(ForecastJob.id == job_id))
        job = result.scalar_one_or_none()
        if job:
            predictions_path = os.path.join(
                os.getcwd(), "outputs", "predictions", "predictions_all.json"
            )
            if os.path.exists(predictions_path):
                with open(predictions_path) as f:
                    preds = json.load(f)
                job.s3_output_key = f"local:{predictions_path}"
            job.status = "success"
            job.progress_pct = 100
            job.progress_message = "Completed successfully"
            job.completed_at = datetime.now(timezone.utc)
            await db.commit()


async def _update_db_error(job_id: str, error: str):
    from backend.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ForecastJob).where(ForecastJob.id == job_id))
        job = result.scalar_one_or_none()
        if job:
            job.status = "failed"
            job.error_message = error
            job.completed_at = datetime.now(timezone.utc)
            await db.commit()


@router.get("/{job_id}/progress", response_model=ProgressResponse)
async def get_progress(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> ProgressResponse:
    result = await db.execute(
        select(ForecastJob).where(ForecastJob.id == job_id)
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
) -> ForecastJobResponse:
    result = await db.execute(
        select(ForecastJob).where(ForecastJob.id == job_id)
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    # For thread-based fallback: read from local file
    results = None
    if job.status == "success":
        if job.s3_output_key and job.s3_output_key.startswith("local:"):
            import json, os
            path = job.s3_output_key.replace("local:", "")
            if os.path.exists(path):
                with open(path) as f:
                    results = _normalize_results(json.load(f))
        elif job.s3_output_key:
            try:
                from backend.storage.s3_client import download_json
                raw = await download_json(job.s3_output_key)
                results = _normalize_results(raw)
            except Exception:
                pass
        else:
            # Final fallback: read from outputs/ directly
            import json, os
            path = os.path.join(
                os.getcwd(), "outputs", "predictions", "predictions_all.json"
            )
            if os.path.exists(path):
                with open(path) as f:
                    results = _normalize_results(json.load(f))

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


@router.delete("/{job_id}", response_model=SuccessResponse)
async def stop_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> SuccessResponse:
    result = await db.execute(
        select(ForecastJob).where(ForecastJob.id == job_id)
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