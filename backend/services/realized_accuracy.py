"""
backend/services/realized_accuracy.py
======================================
Async glue for realized accuracy (F17): check a finished job's stored
forecast against a later upload, persist the result, and build the response.

The maths lives in services/realized_accuracy.py (pure pandas). Forecast
values are read from the job's results.json — the immutable baseline — and
never copied. The Action Center's adjusted forecast is recomputed on every
read from the stored actuals plus the live edit stack, so it cannot go stale.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import structlog
from fastapi import HTTPException, status
from sqlalchemy import cast, func, literal, or_, select
from sqlalchemy.dialects.postgresql import JSONB, JSONPATH, insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.db_models import ForecastEdit, ForecastEvaluation, ForecastJob, Upload
from backend.models.schemas import (
    RealizedAccuracyResponse,
    RealizedMetric,
    RealizedPoint,
    RealizedScores,
)
from backend.services.data_quality import load_upload_bytes
from backend.services.file_parsing import parse_file
from backend.services.forecast_edits import replay_edits
from backend.services.job_results import load_job_results
from services.realized_accuracy import actual_series, compare, forecast_series, status_for

logger = structlog.get_logger("forecasting.realized_accuracy")

MAX_CANDIDATES = 20

_UNIQUE_EVALUATION = "uq_forecast_evaluations_job_upload_sheet_metric"

# Upload.columns is {sheet: [column, ...]}; this matches a column name in any sheet.
# The name travels as a jsonpath variable, never spliced into the path text.
_COLUMN_PATH = "$.*[*] ? (@ == $col)"


# ── Sheet pairing ─────────────────────────────────────────────────────
def pair_sheets(job_sheets: list[str], upload_sheets: list[str]) -> dict[str, str]:
    """Map each job sheet to the upload sheet holding its actuals.

    Same name pairs. As a special case a lone job sheet pairs with a lone
    upload sheet whatever they are called (a CSV is always "Sheet1", and a
    re-exported workbook often renames its only sheet). Anything else is
    left unpaired — never guessed.
    """
    if len(job_sheets) == 1 and len(upload_sheets) == 1:
        return {job_sheets[0]: upload_sheets[0]}
    return {name: name for name in job_sheets if name in upload_sheets}


# ── Candidates ────────────────────────────────────────────────────────
async def list_candidate_uploads(
    db: AsyncSession, job: ForecastJob, metric_names: set[str]
) -> list[Upload]:
    """The caller's uploads that could supply actuals: made after the job, not
    the job's own input, and holding at least one of its metric columns. The
    column test runs in SQL against the stored `Upload.columns`, so no file is
    read and an older matching upload is never hidden by newer ones that don't
    match."""
    has_metric = or_(*[
        func.jsonb_path_exists(
            Upload.columns,
            cast(_COLUMN_PATH, JSONPATH),
            literal({"col": name}, JSONB),
        )
        for name in sorted(metric_names)
    ])
    stmt = (
        select(Upload)
        .where(
            Upload.user_id == job.user_id,
            Upload.created_at > job.created_at,
            Upload.s3_key != job.s3_input_key,
            has_metric,
        )
        .order_by(Upload.created_at.desc(), Upload.id.desc())
        .limit(MAX_CANDIDATES)
    )
    own_upload_id = (job.config or {}).get("upload_id")
    if own_upload_id:
        stmt = stmt.where(Upload.id != own_upload_id)
    return list((await db.execute(stmt)).scalars().all())


# ── Evaluate ──────────────────────────────────────────────────────────
def _evaluate_sheets(
    results: dict, sheets: dict[str, pd.DataFrame]
) -> tuple[list[dict[str, Any]], list[dict[str, str]], bool]:
    """Compare every paired (sheet, metric) of the job with the upload.

    Returns (rows, skipped, metric_present). `skipped` lists job metrics that
    could not be compared and why; `metric_present` says whether ANY of the
    job's metric columns exists in ANY upload sheet, which is what separates
    "wrong file" from "right file, sheets that don't pair".
    Sync pandas — run via asyncio.to_thread."""
    pairing = pair_sheets(list(results), list(sheets))
    rows: list[dict[str, Any]]    = []
    skipped: list[dict[str, str]] = []
    upload_columns = {c for df in sheets.values() for c in df.columns}
    metric_present = False

    for job_sheet, sheet in results.items():
        for metric_name, metric in sheet.get("metrics", {}).items():
            metric_present = metric_present or metric_name in upload_columns

            upload_sheet = pairing.get(job_sheet)
            if upload_sheet is None:
                skipped.append({"sheet": job_sheet, "metric": metric_name, "reason": "sheet_unpaired"})
                continue
            df = sheets[upload_sheet]
            if metric_name not in df.columns:
                skipped.append({"sheet": job_sheet, "metric": metric_name, "reason": "metric_missing"})
                continue

            forecast = forecast_series(metric.get("records", []))
            actuals  = actual_series(df, metric_name)
            outcome  = compare(actuals, forecast)
            observed = actuals.dropna()

            rows.append({
                "sheet_name"       : job_sheet,
                "metric_name"      : metric_name,
                "forecast_points"  : int(len(forecast)),
                "actuals_last_date": observed.index.max().date() if len(observed) else None,
                **outcome,
            })
    return rows, skipped, metric_present


async def evaluate_job(
    db: AsyncSession, job: ForecastJob, upload: Upload, results: dict | None = None
) -> dict:
    """Evaluate `job` against `upload` and upsert one row per (sheet, metric).
    Returns the job's results so the caller can reuse them rather than read
    results.json a second time. The caller commits.

    Metrics whose sheet doesn't pair, or that the paired sheet lacks, are
    left without a row: they stay `awaiting_actuals`, and the reason is logged.

    Raises HTTPException: 409 results unavailable, 503 storage unavailable,
    422 if none of the job's metric columns appear in the upload (or it
    can't be parsed)."""
    if results is None:
        results = await load_job_results(job)
    if not results:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The results for this job could not be loaded",
        )

    try:
        content = await load_upload_bytes(upload.s3_key)
    except (FileNotFoundError, RuntimeError):
        logger.error("realized_storage_failed", upload_id=upload.id, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Upload storage unavailable"
        )

    def _work() -> tuple[list[dict[str, Any]], list[dict[str, str]], bool]:
        return _evaluate_sheets(results, parse_file(content, upload.file_name))

    rows, skipped, metric_present = await asyncio.to_thread(_work)
    if not metric_present:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="This file has none of the forecast's metric columns",
        )

    if skipped:
        logger.info(
            "realized_metrics_skipped",
            job_id=job.id, upload_id=upload.id, skipped=skipped,
        )

    if rows:
        # One atomic upsert: two simultaneous checks of the same upload cannot
        # both insert and trip the unique constraint. created_at is rewritten
        # on every check so it means "last evaluated", which is what makes a
        # re-check outrank older evaluations of the same metric.
        now  = datetime.now(timezone.utc)
        stmt = insert(ForecastEvaluation).values([
            {
                "id"               : str(uuid.uuid4()),
                "job_id"           : job.id,
                "user_id"          : job.user_id,
                "upload_id"        : upload.id,
                "upload_file_name" : upload.file_name,
                "sheet_name"       : row["sheet_name"],
                "metric_name"      : row["metric_name"],
                "forecast_points"  : row["forecast_points"],
                "matched_points"   : row["matched_points"],
                "wmape"            : row["wmape"],
                "mae"              : row["mae"],
                "bias"             : row["bias"],
                "actual_total"     : row["actual_total"],
                "forecast_total"   : row["forecast_total"],
                "actuals_last_date": row["actuals_last_date"],
                "points"           : row["points"],
                "created_at"       : now,
            }
            for row in rows
        ])
        refreshed = (
            "upload_file_name", "forecast_points", "matched_points", "wmape", "mae", "bias",
            "actual_total", "forecast_total", "actuals_last_date", "points", "created_at",
        )
        await db.execute(stmt.on_conflict_do_update(
            constraint=_UNIQUE_EVALUATION,
            set_={col: getattr(stmt.excluded, col) for col in refreshed},
        ))

    logger.info(
        "realized_accuracy_evaluated",
        job_id         = job.id,
        upload_id      = upload.id,
        metrics        = len(rows),
        matched_points = sum(r["matched_points"] for r in rows),
    )
    return results


# ── Read ──────────────────────────────────────────────────────────────
def _scores(outcome: dict[str, Any]) -> RealizedScores:
    return RealizedScores(
        wmape=outcome["wmape"], mae=outcome["mae"], bias=outcome["bias"],
        matched_points=outcome["matched_points"],
        actual_total=outcome["actual_total"], forecast_total=outcome["forecast_total"],
    )


def _adjusted_view(
    evaluation: ForecastEvaluation, baseline: list[dict], edits: list[ForecastEdit]
) -> tuple[RealizedScores, dict[str, float]]:
    """Score the post-edit forecast against the stored actuals. Edits are
    replayed over the full baseline (as the Action Center does), then read
    back on the matched dates."""
    adjusted = forecast_series(replay_edits(baseline, edits))
    actuals  = pd.Series(
        {pd.Timestamp(p["date"]): p["actual"] for p in evaluation.points}, dtype=float
    )
    outcome = compare(actuals, adjusted)
    return _scores(outcome), {p["date"]: p["forecast"] for p in outcome["points"]}


async def build_realized_response(
    db: AsyncSession, job: ForecastJob, results: dict | None = None
) -> RealizedAccuracyResponse:
    """One entry per (sheet, metric) in the job's results: the newest
    evaluation, or `awaiting_actuals` with the dates the forecast needs.
    Pass `results` when the caller already loaded them."""
    if results is None:
        results = await load_job_results(job) or {}

    evaluations = (
        await db.execute(
            select(ForecastEvaluation)
            .where(ForecastEvaluation.job_id == job.id)
            .order_by(ForecastEvaluation.created_at.desc(), ForecastEvaluation.id.desc())
            # The upsert above is a Core statement, so instances this session
            # already holds can be stale; always take the stored values.
            .execution_options(populate_existing=True)
        )
    ).scalars().all()
    newest: dict[tuple[str, str], ForecastEvaluation] = {}
    for evaluation in evaluations:
        newest.setdefault((evaluation.sheet_name, evaluation.metric_name), evaluation)

    edits_by_key: dict[tuple[str, str], list[ForecastEdit]] = {}
    if newest:
        edit_rows = (
            await db.execute(
                select(ForecastEdit)
                .where(ForecastEdit.job_id == job.id)
                .order_by(ForecastEdit.sequence_no.asc())
            )
        ).scalars().all()
        for edit in edit_rows:
            edits_by_key.setdefault((edit.sheet_name, edit.metric_name), []).append(edit)

    metrics: list[RealizedMetric] = []
    for sheet_name, sheet in results.items():
        for metric_name, metric in sheet.get("metrics", {}).items():
            baseline = metric.get("records", [])
            forecast = forecast_series(baseline)
            period   = {
                "sheet_name"     : sheet_name,
                "metric_name"    : metric_name,
                "forecast_points": int(len(forecast)),
                "forecast_start" : forecast.index.min().strftime("%Y-%m-%d") if len(forecast) else None,
                "forecast_end"   : forecast.index.max().strftime("%Y-%m-%d") if len(forecast) else None,
            }

            evaluation = newest.get((sheet_name, metric_name))
            if evaluation is None:
                metrics.append(RealizedMetric(status="awaiting_actuals", **period))
                continue

            measured = evaluation.matched_points > 0
            edits    = edits_by_key.get((sheet_name, metric_name), [])
            adjusted, adjusted_by_date = None, {}
            if measured and edits:
                adjusted, adjusted_by_date = _adjusted_view(evaluation, baseline, edits)

            metrics.append(RealizedMetric(
                status            = status_for(evaluation.forecast_points, evaluation.matched_points),
                model             = _scores({
                    "wmape": evaluation.wmape, "mae": evaluation.mae, "bias": evaluation.bias,
                    "matched_points": evaluation.matched_points,
                    "actual_total": evaluation.actual_total,
                    "forecast_total": evaluation.forecast_total,
                }) if measured else None,
                adjusted          = adjusted,
                points            = [
                    RealizedPoint(**p, adjusted_forecast=adjusted_by_date.get(p["date"]))
                    for p in evaluation.points
                ],
                actuals_last_date = evaluation.actuals_last_date.isoformat() if evaluation.actuals_last_date else None,
                evaluated_at      = evaluation.created_at,
                upload_id         = evaluation.upload_id,
                upload_file_name  = evaluation.upload_file_name,
                **period,
            ))

    return RealizedAccuracyResponse(job_id=job.id, metrics=metrics)
