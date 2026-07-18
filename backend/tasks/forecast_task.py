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

import json
import logging
import os
import sys
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
    except Exception as e:
        logger.error(f"DB update failed for job {job_id}: {e}")


def _save_model_runs_sync(job_id: str, results: dict):
    """Persist model metrics to model_runs table synchronously."""
    try:
        import uuid as _uuid
        conn = _get_sync_conn()
        cur = conn.cursor()

        for sheet_name, sheet_data in results.items():
            if not isinstance(sheet_data, dict):
                continue
            # Handle nested {"metrics": {"HUFL": {...}}} structure
            metrics_dict = sheet_data.get("metrics", sheet_data)
            for metric_name, metric_data in metrics_dict.items():
                if not isinstance(metric_data, dict):
                    continue
                demand = metric_data.get("demand_profile") or {}
                cur.execute("""
                    INSERT INTO model_runs (
                        id, job_id, sheet_name, metric_name, model_name,
                        stage, wmape, mae, mape, rmse, accuracy,
                        composite_score, demand_type, adi, cv2
                    ) VALUES (
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s
                    )
                """, (
                    str(_uuid.uuid4()),
                    job_id,
                    sheet_name,
                    metric_name,
                    metric_data.get("best_model"),
                    "Multivariate" if metric_data.get("is_multivariate") else "Univariate",
                    metric_data.get("wmape"),
                    metric_data.get("mae"),
                    metric_data.get("mape"),
                    metric_data.get("rmse"),
                    metric_data.get("accuracy"),
                    metric_data.get("composite_score"),
                    demand.get("demand_type"),
                    demand.get("adi"),
                    demand.get("cv2"),
                ))

        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        logger.error(f"model_runs insert failed for job {job_id}: {e}")


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
    file_content_b64: str,
    config: dict,
):
    """
    Main Celery forecast task.

    Parameters
    ----------
    job_id          : ForecastJob UUID
    file_content_b64: base64-encoded file bytes
    config          : forecast configuration dict
    """
    logger.info(f"[{job_id}] Forecast task started")

    _update_job_status_sync(
        job_id, "running", progress=0, message="Pipeline starting…"
    )

    def progress_hook(percent: int, message: str):
        _update_job_status_sync(
            job_id, "running", progress=percent, message=message
        )
        logger.info(f"[{job_id}] {percent}% — {message}")

    try:
        from services.processing_engine import processing_worker

        file_content = f"data:application/octet-stream;base64,{file_content_b64}"

        processing_worker(
            file_contents_norm   = file_content,
            selected_sheets_list = config.get("selected_sheets", []),
            selected_metrics     = config.get("selected_metrics", []),
            selected_x_cols      = config.get("selected_x_cols"),
            forecast_horizon     = config.get("forecast_horizon", 60),
            test_window          = config.get("test_window", 30),
            selected_regions     = config.get("selected_regions", ["US", "IN"]),
        )

        # Read results from file-based output
        predictions_path = os.path.join(
            PROJECT_ROOT, "outputs", "predictions", "predictions_all.json"
        )
        results = {}
        if os.path.exists(predictions_path):
            with open(predictions_path) as f:
                results = json.load(f)

        # Upload to S3 if configured
        s3_key = None
        if settings.S3_BUCKET_NAME and settings.AWS_ACCESS_KEY_ID:
            try:
                import boto3
                s3 = boto3.client(
                    "s3",
                    aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                    region_name=settings.AWS_DEFAULT_REGION,
                )
                s3_key = f"{settings.S3_OUTPUT_PREFIX}{job_id}/results.json"
                s3.put_object(
                    Bucket=settings.S3_BUCKET_NAME,
                    Key=s3_key,
                    Body=json.dumps(results, default=str).encode(),
                    ContentType="application/json",
                )
                logger.info(f"[{job_id}] Results uploaded to S3: {s3_key}")
            except Exception as e:
                logger.warning(f"[{job_id}] S3 upload skipped: {e}")
                s3_key = None

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