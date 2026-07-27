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
import csv
import io
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

import pandas as pd
import redis
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.dependencies import get_current_user_id, parse_uuid_or_404
from backend.models.db_models import ForecastEdit, ForecastJob, ModelRun, Upload
from backend.models.schemas import (
    ActionCenterState,
    ApplyActionRequest,
    ExplanationResponse,
    ForecastEditSummary,
    ForecastJobListResponse,
    ForecastJobResponse,
    ForecastJobSummary,
    ForecastJobMetricSummary,
    ForecastRequest,
    ProgressResponse,
    QARequest,
    QAResponse,
    RenameJobRequest,
    RevertActionRequest,
    SuccessResponse,
)
from backend.services.forecast_edits import (
    InvalidOperationError,
    affected_points_before,
    apply_operation,
    parse_operation,
    replay_edits,
)
from backend.services.llm_client import LLMClientError, chat_completion

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


async def _load_job_results(job: ForecastJob) -> dict | None:
    """Loads and normalizes a completed job's results.json from wherever
    s3_output_key points (job-scoped local file or S3) — shared by
    _job_to_response and the AI Action Center's baseline-record loader."""
    if job.status != "success":
        return None

    if job.s3_output_key and job.s3_output_key.startswith("local:"):
        path = job.s3_output_key.replace("local:", "")
        try:
            raw = await asyncio.to_thread(_read_json_file, path)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("job_results_load_failed", job_id=job.id, error=str(exc))
            return None
        return _normalize_results(raw) if raw is not None else None

    if job.s3_output_key:
        try:
            from backend.storage.s3_client import download_json
            raw = await download_json(job.s3_output_key)
            return _normalize_results(raw)
        except Exception as exc:
            logger.warning("job_results_load_failed", job_id=job.id, error=str(exc))
            return None

    # No job-scoped storage location recorded. The only remaining source
    # would be the single global outputs/predictions/predictions_all.json
    # file shared by every job on the box (the F5 "concurrent jobs
    # overwrite each other" defect) — reading it here would leak another
    # tenant's forecast output through this job's own, correctly-authorized
    # job_id. Return no results rather than risk a cross-tenant data leak;
    # F5 (job-scoped artifacts) is what makes this branch safe to populate
    # again.
    return None


async def _load_metric(job: ForecastJob, sheet_name: str, metric_name: str) -> dict:
    """Loads one metric's full result dict (stats + baseline records). Raises
    404 if the job has no results yet, or the sheet/metric doesn't exist —
    matches the ownership-scoped 404 convention used throughout this file."""
    results = await _load_job_results(job)
    if not results:
        raise HTTPException(status_code=404, detail="No results available for this job")

    sheet = results.get(sheet_name)
    if not sheet:
        raise HTTPException(status_code=404, detail=f"Sheet '{sheet_name}' not found")

    metric = sheet.get("metrics", {}).get(metric_name)
    if not metric:
        raise HTTPException(status_code=404, detail=f"Metric '{metric_name}' not found")

    return metric


async def _load_metric_records(job: ForecastJob, sheet_name: str, metric_name: str) -> list[dict]:
    """Loads one metric's baseline records for the AI Action Center."""
    metric = await _load_metric(job, sheet_name, metric_name)
    return metric.get("records", [])


async def _get_owned_job(job_id: str, user_id: str, db: AsyncSession) -> ForecastJob:
    result = await db.execute(
        select(ForecastJob).where(
            ForecastJob.id == job_id, ForecastJob.user_id == user_id
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found")
    return job


async def _get_edit_stack(
    db: AsyncSession, job_id: str, sheet_name: str, metric_name: str
) -> list[ForecastEdit]:
    result = await db.execute(
        select(ForecastEdit)
        .where(
            ForecastEdit.job_id == job_id,
            ForecastEdit.sheet_name == sheet_name,
            ForecastEdit.metric_name == metric_name,
        )
        .order_by(ForecastEdit.sequence_no.asc())
    )
    return list(result.scalars().all())


def _edit_to_summary(edit: ForecastEdit) -> ForecastEditSummary:
    return ForecastEditSummary(
        id=edit.id,
        sequence_no=edit.sequence_no,
        instruction_text=edit.instruction_text,
        operation_type=edit.operation_type,
        params=edit.params,
        created_at=edit.created_at,
    )


async def _job_to_response(job: ForecastJob) -> ForecastJobResponse:
    """Convert ORM object to response schema."""
    results = await _load_job_results(job)

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


# ── AI Action Center (feature-update.md Feature 2) ─────────────────────

_ACTION_SYSTEM_PROMPT = """You are a forecast-editing assistant. Convert the user's plain-language instruction into a single JSON object describing ONE operation to apply to a forecast time series. Output ONLY that JSON object — no markdown, no code fences, no explanation, nothing else.

The forecast covers dates from {date_from} to {date_to} (inclusive).

Allowed operation_type values (choose exactly one):

1. set_value_range — sets the forecast to a fixed value for matching dates
   {{"operation_type": "set_value_range", "value": <number>, "date_from": "YYYY-MM-DD" or null, "date_to": "YYYY-MM-DD" or null, "days_of_week": [0-6] or null}}

2. scale_range — scales the forecast by a percentage for matching dates (scale_pct=120 multiplies by 1.2, scale_pct=80 multiplies by 0.8)
   {{"operation_type": "scale_range", "scale_pct": <number>, "date_from": ..., "date_to": ..., "days_of_week": ...}}

3. clip_bounds — clips the forecast into a [min_value, max_value] range for matching dates
   {{"operation_type": "clip_bounds", "min_value": <number or null>, "max_value": <number or null>, "date_from": ..., "date_to": ..., "days_of_week": ...}}

If the instruction does NOT describe an edit to the forecast (e.g. it's off-topic, a
question, or you cannot map it to one of the three operations above with reasonable
confidence), respond with exactly {{"operation_type": "none"}} instead of guessing.

days_of_week uses 0=Monday, 1=Tuesday, 2=Wednesday, 3=Thursday, 4=Friday, 5=Saturday, 6=Sunday.
Use date_from/date_to for a specific date range, and days_of_week for a recurring weekday pattern (e.g. "weekends" = [5, 6]). Leave a field null if not relevant.

Examples:
User: "set forecast to 0 for weekends"
{{"operation_type": "set_value_range", "value": 0, "date_from": null, "date_to": null, "days_of_week": [5, 6]}}

User: "cap the forecast at 500"
{{"operation_type": "clip_bounds", "min_value": null, "max_value": 500, "date_from": null, "date_to": null, "days_of_week": null}}

User: "increase the forecast by 10 percent"
{{"operation_type": "scale_range", "scale_pct": 110, "date_from": null, "date_to": null, "days_of_week": null}}

User: "what's the weather like tomorrow"
{{"operation_type": "none"}}
"""


@router.get("/{job_id}/actions", response_model=ActionCenterState)
async def get_action_state(
    job_id: str,
    sheet_name: str,
    metric_name: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> ActionCenterState:
    """Hydrates the Action Center on page load: baseline + persisted edits
    replayed, so edits survive a reload (DB-backed operation stack)."""
    job = await _get_owned_job(job_id, user_id, db)
    baseline = await _load_metric_records(job, sheet_name, metric_name)
    edits = await _get_edit_stack(db, job_id, sheet_name, metric_name)
    records = replay_edits(baseline, edits)

    return ActionCenterState(
        records=records,
        edits=[_edit_to_summary(e) for e in edits],
    )


@router.post("/{job_id}/actions", response_model=ActionCenterState)
async def apply_action(
    job_id: str,
    request: ApplyActionRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> ActionCenterState:
    """Parses a plain-language instruction into a whitelisted operation via
    the LLM, validates it strictly against the Pydantic operation schemas
    (never executes it — see backend/services/forecast_edits.py), applies
    it, and persists it as the next entry in this metric's edit stack."""
    job = await _get_owned_job(job_id, user_id, db)
    baseline = await _load_metric_records(job, request.sheet_name, request.metric_name)

    existing_edits = await _get_edit_stack(db, job_id, request.sheet_name, request.metric_name)
    current_records = replay_edits(baseline, existing_edits)

    forecast_dates = [
        pd.Timestamp(r["Date"]) for r in current_records if r.get("Forecast") is not None
    ]
    if not forecast_dates:
        raise HTTPException(
            status_code=422, detail="This metric has no forecast points to edit"
        )
    system_prompt = _ACTION_SYSTEM_PROMPT.format(
        date_from=min(forecast_dates).strftime("%Y-%m-%d"),
        date_to=max(forecast_dates).strftime("%Y-%m-%d"),
    )

    try:
        raw_response = await chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": request.instruction_text},
            ],
            max_tokens=200,
        )
    except LLMClientError as exc:
        raise HTTPException(
            status_code=503, detail=f"AI assistant unavailable: {exc}"
        )

    try:
        operation_type, params = parse_operation(raw_response)
    except InvalidOperationError as exc:
        raise HTTPException(
            status_code=422, detail=f"Couldn't understand that instruction: {exc}"
        )

    before_points = affected_points_before(current_records, operation_type, params)

    edit = ForecastEdit(
        job_id=job_id,
        user_id=user_id,
        sheet_name=request.sheet_name,
        metric_name=request.metric_name,
        sequence_no=len(existing_edits) + 1,
        instruction_text=request.instruction_text,
        operation_type=operation_type,
        params=params,
        affected_points_before=before_points,
    )
    db.add(edit)
    await db.commit()
    await db.refresh(edit)

    updated_records = apply_operation(current_records, operation_type, params)
    all_edits = existing_edits + [edit]

    return ActionCenterState(
        records=updated_records,
        edits=[_edit_to_summary(e) for e in all_edits],
    )


@router.post("/{job_id}/actions/revert", response_model=ActionCenterState)
async def revert_action(
    job_id: str,
    request: RevertActionRequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> ActionCenterState:
    """Pops the latest edit for this metric and replays the remainder from
    baseline. Calling it repeatedly walks back through the whole stack —
    multi-step undo, per the spec, without extra endpoint surface."""
    job = await _get_owned_job(job_id, user_id, db)
    baseline = await _load_metric_records(job, request.sheet_name, request.metric_name)
    edits = await _get_edit_stack(db, job_id, request.sheet_name, request.metric_name)

    if not edits:
        raise HTTPException(status_code=409, detail="No edits to revert")

    latest = edits[-1]
    await db.delete(latest)
    await db.commit()

    remaining = edits[:-1]
    records = replay_edits(baseline, remaining)

    return ActionCenterState(
        records=records,
        edits=[_edit_to_summary(e) for e in remaining],
    )


# ── Understandability + Q&A (feature-update.md Feature 3) ──────────────

_EXPLANATION_SYSTEM_PROMPT = """You are a forecasting analyst explaining a demand forecast to a non-technical business user. Given the metric's stats below, write a short (2-4 sentence) plain-language explanation covering: what the forecast shows, which model produced it and how accurate it is, and one notable pattern in the historical data. Spell out technical terms in plain language rather than using jargon like "WMAPE" on its own. Output only the explanation itself — no preamble, no headings."""

_QA_SYSTEM_PROMPT = """You are a forecasting analyst answering a user's question about a specific demand forecast. Use only the stats provided below to answer — if they don't contain enough information to answer confidently, say so rather than guessing. Keep the answer concise (2-4 sentences), in plain language."""


def _build_metric_context(metric: dict, records: list[dict]) -> str:
    """Compact, exactly-computed stats for the LLM prompt — deliberately not
    the full raw record list (keeps token usage bounded and avoids asking
    the model to do arithmetic we can just compute ourselves)."""
    df = pd.DataFrame(records)

    lines = [
        f"Metric: {metric.get('metric_name')}",
        f"Best model: {metric.get('best_model')}",
        f"WMAPE (weighted mean absolute percentage error): {metric.get('wmape')}",
        f"Accuracy: {metric.get('accuracy')}%",
        f"RMSE: {metric.get('rmse')}",
        f"MAE: {metric.get('mae')}",
    ]
    demand_profile = metric.get("demand_profile")
    if demand_profile:
        lines.append(f"Demand type: {demand_profile.get('demand_type')}")

    if "TrainActual" in df.columns:
        train = df["TrainActual"].dropna()
        if not train.empty:
            lines.append(
                f"Historical actuals: {len(train)} points, "
                f"mean={train.mean():.2f}, min={train.min():.2f}, max={train.max():.2f}"
            )

    if "Forecast" in df.columns:
        forecast = df[df["Forecast"].notna()]
        if not forecast.empty:
            lines.append(
                f"Forecast: {len(forecast)} points from {forecast['Date'].min()} "
                f"to {forecast['Date'].max()}, mean={forecast['Forecast'].mean():.2f}, "
                f"min={forecast['Forecast'].min():.2f}, max={forecast['Forecast'].max():.2f}"
            )

    return "\n".join(lines)


@router.get("/{job_id}/explanation", response_model=ExplanationResponse)
async def get_explanation(
    job_id: str,
    sheet_name: str,
    metric_name: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> ExplanationResponse:
    """Plain-language explanation of the forecast, generated on demand —
    the frontend fetches this lazily with a long staleTime rather than
    regenerating it on every visit."""
    job = await _get_owned_job(job_id, user_id, db)
    metric = await _load_metric(job, sheet_name, metric_name)
    edits = await _get_edit_stack(db, job_id, sheet_name, metric_name)
    records = replay_edits(metric.get("records", []), edits)

    context = _build_metric_context(metric, records)

    try:
        explanation = await chat_completion(
            messages=[
                {"role": "system", "content": _EXPLANATION_SYSTEM_PROMPT},
                {"role": "user", "content": context},
            ],
            max_tokens=250,
        )
    except LLMClientError as exc:
        raise HTTPException(
            status_code=503, detail=f"AI assistant unavailable: {exc}"
        )

    return ExplanationResponse(explanation=explanation.strip())


@router.post("/{job_id}/qa", response_model=QAResponse)
async def ask_question(
    job_id: str,
    request: QARequest,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> QAResponse:
    """Answers a free-text question about the forecast. Q&A history is kept
    client-side only (not persisted) — a deliberate, smaller scope than the
    Action Center's edit stack, which the spec requires to survive reload."""
    job = await _get_owned_job(job_id, user_id, db)
    metric = await _load_metric(job, request.sheet_name, request.metric_name)
    edits = await _get_edit_stack(db, job_id, request.sheet_name, request.metric_name)
    records = replay_edits(metric.get("records", []), edits)

    context = _build_metric_context(metric, records)

    try:
        answer = await chat_completion(
            messages=[
                {"role": "system", "content": _QA_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Stats:\n{context}\n\nQuestion: {request.question}",
                },
            ],
            max_tokens=300,
        )
    except LLMClientError as exc:
        raise HTTPException(
            status_code=503, detail=f"AI assistant unavailable: {exc}"
        )

    return QAResponse(answer=answer.strip())


# ── CSV export (feature-update.md Feature 5) ────────────────────────────

def _safe_filename_part(s: str) -> str:
    """Query-param-derived, used in a Content-Disposition header — strip
    anything but a conservative safe charset to avoid header injection."""
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s).strip("_") or "export"


@router.get("/{job_id}/export")
async def export_csv(
    job_id: str,
    sheet_name: str,
    metric_name: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> StreamingResponse:
    """Computed on demand from baseline + the persisted edit stack — never
    reads from or writes to the job's stored results.json, so exporting can
    never mutate the canonical forecast data. One op_N_<type> column per
    applied edit shows the forecast immediately after that specific edit, so
    the user can trace how each change affected the numbers.

    Column shape depends on whether any edits exist, to avoid two columns
    ever holding identical values: with no edits there's just "forecast"
    (baseline == current, so one column is enough); once edits exist,
    "forecast" is renamed to "baseline_forecast" and followed by one
    op_N_<type> column per edit — the last of those already *is* the current
    forecast, so there's no separate trailing "forecast" column."""
    job = await _get_owned_job(job_id, user_id, db)
    baseline = await _load_metric_records(job, sheet_name, metric_name)
    edits = await _get_edit_stack(db, job_id, sheet_name, metric_name)

    op_columns: list[tuple[str, dict]] = []
    current = baseline
    for edit in edits:
        current = apply_operation(current, edit.operation_type, edit.params)
        column_name = f"op_{edit.sequence_no}_{edit.operation_type}"
        op_columns.append((column_name, {r["Date"]: r["Forecast"] for r in current}))

    baseline_by_date = {r["Date"]: r["Forecast"] for r in baseline}
    forecast_fieldnames = (
        ["baseline_forecast"] + [name for name, _ in op_columns]
        if op_columns
        else ["forecast"]
    )

    fieldnames = [
        "date", "actual_train", "actual_test", "test_prediction",
    ] + forecast_fieldnames

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in baseline:
        date = row["Date"]
        out_row = {
            "date": date,
            "actual_train": row.get("TrainActual"),
            "actual_test": row.get("TestActual"),
            "test_prediction": row.get("TestPrediction"),
        }
        if op_columns:
            out_row["baseline_forecast"] = baseline_by_date.get(date)
            for column_name, lookup in op_columns:
                out_row[column_name] = lookup.get(date)
        else:
            out_row["forecast"] = baseline_by_date.get(date)
        writer.writerow(out_row)

    filename = f"{_safe_filename_part(sheet_name)}_{_safe_filename_part(metric_name)}_forecast.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )