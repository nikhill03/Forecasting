"""
backend/tasks/forecast_task.py
================================
Celery task for running the forecast pipeline.

Fixes vs initial version:
- sys.path fix so Celery worker can find `services/` module
- Replaced async DB calls with synchronous psycopg2 to avoid
  event loop conflicts between Celery's fork model and asyncpg
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import os
import sys
import uuid
from datetime import datetime, timezone

# ── Fix module path so Celery can import services/ and utils/ ─────────
# Celery worker may start from a different working directory
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from celery import Task
from backend.tasks.celery_app import celery_app
from backend.core.config import settings

logger = logging.getLogger("tasks.forecast")

# Dev-only fallback when S3 isn't configured. Mirrors backend/api/routes/
# upload.py's _store_locally — same "outputs/" root, same "local:"-prefixed
# key convention that backend/api/routes/forecast.py's _job_to_response
# already knows how to read back.
_LOCAL_OUTPUT_ROOT = "outputs"


def _store_results_locally(results: dict, job_id: str) -> str:
    directory = os.path.join(
        _LOCAL_OUTPUT_ROOT, settings.S3_OUTPUT_PREFIX.rstrip("/"), job_id
    )
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "results.json")
    with open(path, "w") as f:
        json.dump(results, f, default=str)
    return f"local:{path}"


# ── Sync DB helper (avoids asyncpg event loop conflicts in Celery) ────
def _get_sync_conn():
    """
    Returns a psycopg2 connection for synchronous DB updates from Celery.
    We use psycopg2 (sync) instead of asyncpg here because Celery workers
    use forked processes with their own event loops — sharing the async
    engine from the FastAPI process causes 'attached to different loop' errors.
    """
    import psycopg2
    db_url = settings.DATABASE_URL.replace("+asyncpg", "")
    return psycopg2.connect(db_url)


def _update_job_status_sync(
    job_id: str,
    status: str,
    progress: int = 0,
    message: str = "",
    error: str | None = None,
    s3_output_key: str | None = None,
):
    """Synchronous DB update — safe to call from Celery worker process."""
    try:
        conn = _get_sync_conn()
        cur = conn.cursor()

        now = datetime.now(timezone.utc)
        fields = [
            "status = %s",
            "progress_pct = %s",
            "progress_message = %s",
        ]
        values = [status, progress, message]

        if error:
            fields.append("error_message = %s")
            values.append(error)
        if s3_output_key:
            fields.append("s3_output_key = %s")
            values.append(s3_output_key)
        if status == "running":
            fields.append("started_at = %s")
            values.append(now)
        if status in ("success", "failed", "stopped"):
            fields.append("completed_at = %s")
            values.append(now)

        values.append(job_id)
        sql = f"UPDATE forecast_jobs SET {', '.join(fields)} WHERE id = %s"
        cur.execute(sql, values)
        conn.commit()
        cur.close()
        conn.close()
    except Exception:
        logger.error(f"DB update failed for job {job_id}", exc_info=True)
        raise


# ── model_runs row building (F14) ─────────────────────────────────────
# Kept pure and DB-free so the interesting logic — the champion invariant,
# the pre-F14 fallback, non-finite handling — is unit-testable without a
# connection. The DB half below is then a single executemany.

_MODEL_RUN_INSERT = """
    INSERT INTO model_runs (
        id, job_id, sheet_name, metric_name, model_name,
        stage, wmape, mae, mape, rmse, accuracy,
        composite_score, demand_type, adi, cv2,
        is_champion, status, error_message
    ) VALUES (
        %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s,
        %s, %s, %s
    )
"""


def _finite(value) -> float | None:
    """Coerce a score to a JSON- and DB-safe float, or None.

    Both engines use float("inf") as a "no valid points" sentinel. That
    survives json.dump() as a bare `Infinity` token, which is not valid
    JSON and makes the browser's JSON.parse throw on the whole results
    payload. Since F14 persists every model's score — failures included —
    these sentinels would otherwise become routine.
    """
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _rows_for_metric(
    job_id: str, sheet_name: str, metric_name: str, metric_data: dict
) -> list[tuple]:
    demand      = metric_data.get("demand_profile") or {}
    best_model  = metric_data.get("best_model")
    leaderboard = metric_data.get("model_leaderboard") or []

    if not leaderboard:
        # Pre-F14 pipeline output, or a path that produced no candidates at
        # all. Degrade to the old single-champion row rather than dropping
        # the run: a partially-upgraded deployment should lose the
        # leaderboard, not the result.
        leaderboard = [{
            "model_name": best_model,
            "stage": (
                "Multivariate" if metric_data.get("is_multivariate") else "Univariate"
            ),
            "wmape": metric_data.get("wmape"),
            "mae": metric_data.get("mae"),
            "mape": metric_data.get("mape"),
            "rmse": metric_data.get("rmse"),
            "accuracy": metric_data.get("accuracy"),
            "composite_score": metric_data.get("composite_score"),
            "status": "completed",
        }]

    # The champion is derived from best_model here rather than trusted from
    # the entry's own flag, so the leaderboard can never disagree with the
    # headline the user is shown.
    champion_seen = False
    rows: list[tuple] = []
    for entry in leaderboard:
        if not isinstance(entry, dict):
            continue
        model_name = entry.get("model_name")
        is_champion = (
            not champion_seen
            and best_model is not None
            and model_name == best_model
        )
        champion_seen = champion_seen or is_champion

        rows.append((
            str(uuid.uuid4()),
            job_id,
            sheet_name,
            metric_name,
            model_name,
            entry.get("stage") or "Univariate",
            _finite(entry.get("wmape")),
            _finite(entry.get("mae")),
            _finite(entry.get("mape")),
            _finite(entry.get("rmse")),
            _finite(entry.get("accuracy")),
            _finite(entry.get("composite_score")),
            demand.get("demand_type"),
            _finite(demand.get("adi")),
            _finite(demand.get("cv2")),
            is_champion,
            entry.get("status") or "completed",
            entry.get("error_message"),
        ))

    # The winner must always have a row, even if the pipeline somehow left
    # it out of its own leaderboard — the job-history summaries filter on
    # is_champion, so a group without one disappears from that page.
    if not champion_seen and best_model is not None:
        rows.append((
            str(uuid.uuid4()),
            job_id,
            sheet_name,
            metric_name,
            best_model,
            "Multivariate" if metric_data.get("is_multivariate") else "Univariate",
            _finite(metric_data.get("wmape")),
            _finite(metric_data.get("mae")),
            _finite(metric_data.get("mape")),
            _finite(metric_data.get("rmse")),
            _finite(metric_data.get("accuracy")),
            _finite(metric_data.get("composite_score")),
            demand.get("demand_type"),
            _finite(demand.get("adi")),
            _finite(demand.get("cv2")),
            True,
            "completed",
            None,
        ))

    return rows


def _leaderboard_rows(job_id: str, results: dict) -> list[tuple]:
    """Flatten a results payload into model_runs rows — one per model tried."""
    rows: list[tuple] = []
    if not isinstance(results, dict):
        return rows

    for sheet_name, sheet_data in results.items():
        if not isinstance(sheet_data, dict):
            continue
        # Handle nested {"metrics": {"HUFL": {...}}} structure
        metrics_dict = sheet_data.get("metrics", sheet_data)
        if not isinstance(metrics_dict, dict):
            continue
        for metric_name, metric_data in metrics_dict.items():
            if not isinstance(metric_data, dict):
                continue
            rows.extend(
                _rows_for_metric(job_id, sheet_name, metric_name, metric_data)
            )

    return rows


def _save_model_runs_sync(job_id: str, results: dict):
    """Persist one model_runs row per model tried, synchronously."""
    rows = _leaderboard_rows(job_id, results)
    if not rows:
        logger.warning(f"[{job_id}] no model_runs rows to persist")
        return

    try:
        conn = _get_sync_conn()
        cur = conn.cursor()
        cur.executemany(_MODEL_RUN_INSERT, rows)
        conn.commit()
        cur.close()
        conn.close()
        logger.info(f"[{job_id}] persisted {len(rows)} model_runs rows")
    except Exception as e:
        # The run itself succeeded and its results are already stored; a
        # failed leaderboard write must not fail the task. Log loudly so a
        # missing leaderboard is diagnosable rather than mysterious.
        logger.error(
            f"model_runs insert failed for job {job_id} ({len(rows)} rows): {e}",
            exc_info=True,
        )


@celery_app.task(
    bind=True,
    name="backend.tasks.forecast_task.run_forecast",
    max_retries=0,
    time_limit=3600,
    soft_time_limit=3300,
)
def run_forecast(
    self: Task,
    job_id: str,
    s3_input_key: str,
    config: dict,
):
    """
    Main Celery forecast task.

    Parameters
    ----------
    job_id       : ForecastJob UUID
    s3_input_key : S3 object key (or "local:"-prefixed filesystem path in
                   dev) for the uploaded input file — never a base64 blob
                   on the Celery/Redis wire.
    config       : forecast configuration dict

    Note: any direct unit test of this function must call it as a plain
    sync function, not from inside an `async def` test — asyncio.run()
    below raises if called from an already-running event loop. Not a
    concern for HTTP-triggered integration tests, which intercept
    apply_async via the mock_celery_delay fixture before this body runs.
    """
    logger.info(f"[{job_id}] Forecast task started")

    def progress_hook(percent: int, message: str):
        _update_job_status_sync(
            job_id, "running", progress=percent, message=message
        )
        logger.info(f"[{job_id}] {percent}% — {message}")

    try:
        _update_job_status_sync(
            job_id, "running", progress=0, message="Pipeline starting…"
        )

        # The module-level sys.path insert above (near the top of this file)
        # does not reliably survive to task-execution time inside the Celery
        # worker process — reproduced even under --pool=solo (no forking), so
        # this isn't a fork-inheritance issue; root cause not fully understood.
        # This call-site re-assertion is a verified fix — do not remove as
        # "redundant" without re-testing a real job end-to-end via /run-dmc --celery.
        if PROJECT_ROOT not in sys.path:
            sys.path.insert(0, PROJECT_ROOT)
        from services.processing_engine import processing_worker

        if s3_input_key.startswith("local:"):
            with open(s3_input_key.removeprefix("local:"), "rb") as f:
                file_bytes = f.read()
        else:
            from backend.storage.s3_client import download_file

            # asyncio.run() assumes a prefork/solo Celery worker pool —
            # breaks under eventlet/gevent, which already run a loop.
            file_bytes = asyncio.run(download_file(s3_input_key))

        file_content_b64 = base64.b64encode(file_bytes).decode("utf-8")
        file_content = f"data:application/octet-stream;base64,{file_content_b64}"

        results = processing_worker(
            job_id               = job_id,
            file_contents_norm   = file_content,
            selected_sheets_list = config.get("selected_sheets", []),
            selected_metrics     = config.get("selected_metrics", []),
            selected_x_cols      = config.get("selected_x_cols"),
            forecast_horizon     = config.get("forecast_horizon", 60),
            test_window          = config.get("test_window", 30),
            selected_regions     = config.get("selected_regions", ["US", "IN"]),
            # Pass settings.REDIS_URL explicitly rather than letting
            # processing_engine.py resolve its own via os.environ — those
            # two can silently diverge in a real deployment (pydantic-settings'
            # env_file loading doesn't populate os.environ), which would let
            # DELETE /forecast/{job_id} write a stop key to a different
            # Redis than the one this worker checks.
            redis_url            = settings.REDIS_URL,
        )

        # Upload to S3 if configured, else fall back to local storage (dev-only —
        # same pattern as upload.py's local fallback) so results are never
        # silently dropped just because S3 isn't configured.
        s3_key = None
        if settings.S3_BUCKET_NAME and settings.AWS_ACCESS_KEY_ID:
            try:
                from backend.storage.s3_client import upload_json

                s3_key = f"{settings.S3_OUTPUT_PREFIX}{job_id}/results.json"
                # asyncio.run() assumes a prefork/solo Celery worker pool —
                # breaks under eventlet/gevent, which already run a loop.
                asyncio.run(upload_json(results, s3_key))
                logger.info(f"[{job_id}] Results uploaded to S3: {s3_key}")
            except Exception as e:
                logger.warning(f"[{job_id}] S3 upload failed, falling back to local storage: {e}")
                s3_key = None

        if s3_key is None:
            s3_key = _store_results_locally(results, job_id)
            logger.info(f"[{job_id}] Results stored locally: {s3_key}")

        # Save model run metrics
        _save_model_runs_sync(job_id, results)

        _update_job_status_sync(
            job_id, "success",
            progress=100,
            message="Completed successfully",
            s3_output_key=s3_key,
        )

        logger.info(f"[{job_id}] Forecast task completed")
        return {"job_id": job_id, "status": "success"}

    except Exception as exc:
        error_msg = str(exc)
        logger.error(f"[{job_id}] Task failed: {error_msg}", exc_info=True)
        _update_job_status_sync(
            job_id, "failed",
            message="Pipeline failed",
            error=error_msg,
        )
        raise