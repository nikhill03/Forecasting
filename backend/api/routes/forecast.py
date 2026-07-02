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
"""

from __future__ import annotations

import base64
import io
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from backend.core.config import Settings, get_settings
from backend.models.schemas import (
    ForecastJobResponse,
    ForecastRequest,
    ProgressResponse,
    SuccessResponse,
)
from backend.api.routes.upload import get_upload_content

router = APIRouter(prefix="/forecast", tags=["forecast"])

# In-memory job store for Phase 1
# Phase 2: replaced by PostgreSQL forecast_jobs table + Celery
_job_store: Dict[str, Dict[str, Any]] = {}
_stop_flags: Dict[str, bool] = {}


def _encode_content(content: bytes) -> str:
    """Encode bytes to base64 string for the existing pipeline."""
    return "data:application/octet-stream;base64," + base64.b64encode(content).decode()


def _run_pipeline(job_id: str, request: ForecastRequest, file_content: bytes):
    """
    Background thread that runs the existing processing_worker.

    Phase 1: runs in a thread (same as v1.0 but properly managed).
    Phase 2: this becomes a Celery task — thread is removed entirely.
    """
    try:
        _job_store[job_id]["status"]     = "running"
        _job_store[job_id]["started_at"] = datetime.now(timezone.utc)

        # Import here to avoid circular imports at module load time
        from services.processing_engine import processing_worker

        # Progress callback that updates our in-memory store
        # Phase 2: Celery task will update PostgreSQL + emit WebSocket event
        def progress_hook(percent: int, message: str):
            if _stop_flags.get(job_id):
                raise InterruptedError("Stopped by user")
            _job_store[job_id]["progress"] = percent
            _job_store[job_id]["message"]  = message

        # Call existing processing_worker with base64-encoded content
        # (preserves compatibility with the existing pipeline in Phase 1)
        processing_worker(
            file_contents_norm   = _encode_content(file_content),
            selected_sheets_list = request.selected_sheets,
            selected_metrics     = request.selected_metrics,
            selected_x_cols      = request.selected_x_cols,
            forecast_horizon     = request.forecast_horizon,
            test_window          = request.test_window,
            selected_regions     = request.selected_regions,
        )

        # Read results from outputs/ (Phase 1 — file-based IPC still in use)
        # Phase 2: results read from PostgreSQL / S3
        from services.processing_engine import read_predictions_and_figs
        preds, figs = read_predictions_and_figs()

        _job_store[job_id].update({
            "status"      : "success",
            "progress"    : 100,
            "message"     : "Completed successfully",
            "completed_at": datetime.now(timezone.utc),
            "results"     : preds,
        })

    except InterruptedError:
        _job_store[job_id].update({
            "status"  : "stopped",
            "progress": _job_store[job_id].get("progress", 0),
            "message" : "Stopped by user",
        })
    except Exception as e:
        _job_store[job_id].update({
            "status"      : "failed",
            "message"     : "Pipeline failed",
            "error"       : str(e),
            "completed_at": datetime.now(timezone.utc),
        })


@router.post(
    "",
    response_model=ForecastJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a forecast job",
)
async def submit_forecast(
    request  : ForecastRequest,
    settings : Settings = Depends(get_settings),
    # Phase 2: uncomment to require auth
    # user_id: str = Depends(get_current_user_id),
) -> ForecastJobResponse:
    """
    Submit a forecast job for the previously uploaded file.

    Returns immediately with a job_id.
    Poll GET /forecast/{job_id}/progress for live updates.

    Phase 2: job submitted to Celery instead of a thread.
    """
    # Retrieve uploaded file content
    file_content = get_upload_content(request.upload_id)

    # Check no job already running (Phase 1 single-user limitation)
    # Phase 2: multi-user support via Celery — this check is removed
    running = [j for j in _job_store.values() if j["status"] == "running"]
    if running:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A forecast job is already running. Please wait for it to complete.",
        )

    job_id = str(uuid.uuid4())
    now    = datetime.now(timezone.utc)

    _job_store[job_id] = {
        "job_id"    : job_id,
        "status"    : "pending",
        "progress"  : 0,
        "message"   : "Job queued",
        "created_at": now,
        "started_at": None,
        "completed_at": None,
        "results"   : None,
        "error"     : None,
    }
    _stop_flags[job_id] = False

    # Phase 1: background thread
    # Phase 2: celery_app.send_task("tasks.run_forecast", args=[job_id, ...])
    thread = threading.Thread(
        target=_run_pipeline,
        args=(job_id, request, file_content),
        daemon=True,
    )
    thread.start()

    return ForecastJobResponse(
        job_id      = job_id,
        status      = "pending",
        progress    = 0,
        message     = "Job submitted successfully",
        created_at  = now,
        started_at  = None,
        completed_at= None,
    )


@router.get(
    "/{job_id}/progress",
    response_model=ProgressResponse,
    summary="Get lightweight job progress",
)
async def get_progress(job_id: str) -> ProgressResponse:
    """
    Lightweight endpoint for polling job progress.
    Frontend polls this every 2 seconds for the progress bar.

    Phase 2: replaced by WebSocket / SSE for push-based updates.
    """
    job = _job_store.get(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found",
        )
    return ProgressResponse(
        job_id   = job_id,
        status   = job["status"],
        progress = job["progress"],
        message  = job["message"],
    )


@router.get(
    "/{job_id}",
    response_model=ForecastJobResponse,
    summary="Get full job status and results",
)
async def get_job(job_id: str) -> ForecastJobResponse:
    job = _job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")

    # Normalize results from processing_engine format to API schema format
    if job.get("results"):
        normalized = {}
        for sheet_name, sheet_data in job["results"].items():
            if isinstance(sheet_data, dict) and "metrics" not in sheet_data:
                # Old format: {sheet_name: {metric_name: {...}}}
                # New format: {sheet_name: {sheet_name: ..., metrics: {metric_name: {...}}}}
                normalized[sheet_name] = {
                    "sheet_name": sheet_name,
                    "metrics": {
                        metric_name: {"metric_name": metric_name, **metric_data}
                        for metric_name, metric_data in sheet_data.items()
                    }
                }
            else:
                normalized[sheet_name] = sheet_data
        job = {**job, "results": normalized}

    return ForecastJobResponse(**job)


@router.delete(
    "/{job_id}",
    response_model=SuccessResponse,
    summary="Stop a running forecast job",
)
async def stop_job(job_id: str) -> SuccessResponse:
    """
    Signal a running job to stop gracefully.
    Phase 2: calls Celery task revoke instead of flag.
    """
    job = _job_store.get(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found",
        )
    if job["status"] not in ("pending", "running"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job is already in terminal state: {job['status']}",
        )

    _stop_flags[job_id] = True

    # Also write the stop flag file for compatibility with
    # existing processing_engine.py STOP_FLAG check
    import os
    stop_flag_path = os.path.join(os.getcwd(), "outputs", "processing_stop.flag")
    os.makedirs(os.path.dirname(stop_flag_path), exist_ok=True)
    with open(stop_flag_path, "w") as f:
        f.write(f"stopped:{job_id}")

    return SuccessResponse(message=f"Stop signal sent to job {job_id}")