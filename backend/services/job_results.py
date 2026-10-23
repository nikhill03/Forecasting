"""
backend/services/job_results.py
================================
Loads and normalizes a completed forecast job's results.json (job-scoped
local file or S3). Lives in services/ so other services (e.g. realized
accuracy) can read a job's baseline forecast without importing a route module.
"""
from __future__ import annotations

import asyncio
import json
import os

import structlog

from backend.models.db_models import ForecastJob

logger = structlog.get_logger("forecasting.job_results")


# ── Normalization + file reads ────────────────────────────────────────
def normalize_results(results: dict | None) -> dict | None:
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


def read_json_file(path: str) -> dict | None:
    """Sync helper — run via asyncio.to_thread so callers don't block the event loop."""
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)



# ── Job results loader ─────────────────────────────────────────────
async def load_job_results(job: ForecastJob) -> dict | None:
    """Loads and normalizes a completed job's results.json from wherever
    s3_output_key points (job-scoped local file or S3) — shared by
    _job_to_response and the AI Action Center's baseline-record loader."""
    if job.status != "success":
        return None

    if job.s3_output_key and job.s3_output_key.startswith("local:"):
        path = job.s3_output_key.replace("local:", "")
        try:
            raw = await asyncio.to_thread(read_json_file, path)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("job_results_load_failed", job_id=job.id, error=str(exc))
            return None
        return normalize_results(raw) if raw is not None else None

    if job.s3_output_key:
        try:
            from backend.storage.s3_client import download_json
            raw = await download_json(job.s3_output_key)
            return normalize_results(raw)
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
