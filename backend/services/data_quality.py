"""
backend/services/data_quality.py
=================================
Async glue for the data-quality report (F16): load a stored upload, parse
it, and run the pure profiler in services/data_quality.py — off the event
loop, since pandas on a 50 MB workbook would otherwise stall every request
this worker is serving.

Used by POST /upload/{id}/quality-report (preview at configure time) and
POST /forecast (authoritative check + persistence). Both go through
build_quality_report so the preview and the enforced check can't disagree.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import structlog
from fastapi import HTTPException, status

from backend.models.db_models import Upload
from backend.models.schemas import DataQualityReport, SeriesSelection
from backend.services.file_parsing import parse_file
from services.data_quality import build_report

logger = structlog.get_logger("forecasting.data_quality")

_LOCAL_PREFIX = "local:"


# ── Storage ───────────────────────────────────────────────────────────
async def load_upload_bytes(s3_key: str) -> bytes:
    """Read an upload's bytes from S3 or the dev-only local fallback.

    Same branch as backend/tasks/forecast_task.py. Raises FileNotFoundError
    if the object is gone and RuntimeError if S3 itself fails.
    """
    if s3_key.startswith(_LOCAL_PREFIX):
        return await asyncio.to_thread(Path(s3_key.removeprefix(_LOCAL_PREFIX)).read_bytes)

    from backend.storage.s3_client import download_file

    return await download_file(s3_key)


# ── Report ────────────────────────────────────────────────────────────
async def build_quality_report(upload: Upload, selection: SeriesSelection) -> DataQualityReport:
    """Raises HTTPException: 503 if the stored file can't be read, 422 if it
    can't be parsed (from parse_file)."""
    started = time.perf_counter()
    try:
        content = await load_upload_bytes(upload.s3_key)
    except (FileNotFoundError, RuntimeError):
        logger.error("quality_report_storage_failed", upload_id=upload.id, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Upload storage unavailable",
        )

    def _profile() -> dict:
        sheets = parse_file(content, upload.file_name)
        return build_report(
            sheets,
            selection.selected_sheets,
            selection.selected_metrics,
            selection.forecast_horizon,
            selection.test_window,
        )

    report = DataQualityReport.model_validate(await asyncio.to_thread(_profile))

    issues = [i for s in report.series for i in s.issues] + report.issues
    logger.info(
        "quality_report_built",
        upload_id   = upload.id,
        series      = len(report.series),
        blocking    = sum(1 for i in issues if i.severity == "blocking"),
        warnings    = sum(1 for i in issues if i.severity == "warning"),
        duration_ms = round((time.perf_counter() - started) * 1000),
    )
    return report
