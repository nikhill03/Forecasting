"""
backend/services/dashboard.py
==============================
Aggregates for the dashboard home page (F15): headline numbers, recent runs,
accuracy over time and demand mix — for one user, in one request.

Two rules hold for every query here:

  * Champion rows only. Since F14, model_runs holds one row per model *tried*
    (~14 per run). Without `is_champion` every aggregate would count each run
    many times over.
  * A fixed number of statements, however many jobs the user has. No query is
    issued per job; backend/tests/test_dashboard.py asserts the count.

The arithmetic lives in small pure functions so the metric definitions can be
tested without a database.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter, defaultdict
from typing import Iterable, Optional

from sqlalchemy import String, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.db_models import ForecastJob, ModelRun
from backend.models.schemas import (
    ActiveRun,
    DashboardSummary,
    DemandMix,
    ModelWin,
    RecentRun,
    RunDuration,
    StatusCounts,
    TrendPoint,
)

# ── Tunables ──────────────────────────────────────────────────────────
RECENT_RUNS_LIMIT  = 5
TREND_WINDOW       = 20
ACTIVE_RUNS_LIMIT  = 5
RUN_TIME_WINDOW    = 20
SLOWEST_RUNS_LIMIT = 3

ACTIVE_STATUSES = ("pending", "running")

_DEMAND_TYPES = ("Smooth", "Erratic", "Intermittent", "Lumpy")


# ── Pure arithmetic ───────────────────────────────────────────────────
def median_or_none(values: Iterable[Optional[float]]) -> Optional[float]:
    """Median of the finite values, or None if there are none.

    Median, not mean: champion WMAPEs span three orders of magnitude, and one
    intermittent series would dominate an average. Nulls and non-finite values
    are skipped — a missing score is not a zero.
    """
    clean = [
        float(v) for v in values
        if v is not None and math.isfinite(float(v))
    ]
    return statistics.median(clean) if clean else None


def per_run_wmape(wmapes: Iterable[Optional[float]]) -> Optional[float]:
    """One WMAPE for a run: the median across its champion rows (one per
    sheet/metric)."""
    return median_or_none(wmapes)


def success_rate(success: int, failed: int) -> Optional[float]:
    """success / (success + failed), or None when no run has finished.

    Stopped runs are excluded — a user cancelling is not a pipeline failure —
    and so are pending/running ones, which have no outcome yet.
    """
    finished = success + failed
    return success / finished if finished else None


def _empty_summary() -> DashboardSummary:
    return DashboardSummary(
        total_runs=0,
        status_counts=StatusCounts(),
        demand_mix=DemandMix(),
    )


# ── Aggregation ───────────────────────────────────────────────────────
async def build_dashboard_summary(db: AsyncSession, user_id: str) -> DashboardSummary:
    # 1 ─ status counts, total and newest run
    status_rows = (await db.execute(
        select(ForecastJob.status, func.count(), func.max(ForecastJob.created_at))
        .where(ForecastJob.user_id == user_id)
        .group_by(ForecastJob.status)
    )).all()

    total = sum(n for _, n, _ in status_rows)
    if total == 0:
        return _empty_summary()

    by_status = {status: n for status, n, _ in status_rows}
    status_counts = StatusCounts(
        **{k: by_status.get(k, 0) for k in StatusCounts.model_fields}
    )
    last_run_at = max(newest for _, _, newest in status_rows)

    # 2 ─ newest jobs, any status
    recent_jobs = (await db.execute(
        select(ForecastJob)
        .where(ForecastJob.user_id == user_id)
        .order_by(ForecastJob.created_at.desc(), ForecastJob.id.desc())
        .limit(RECENT_RUNS_LIMIT)
    )).scalars().all()

    # 3 ─ their champion rows. The ids come from an owner-scoped query, so
    #     this read is owner-scoped too.
    recent_champions = (await db.execute(
        select(
            ModelRun.job_id, ModelRun.sheet_name, ModelRun.metric_name,
            ModelRun.model_name, ModelRun.wmape,
        )
        .where(
            ModelRun.job_id.in_([job.id for job in recent_jobs]),
            ModelRun.is_champion.is_(True),
        )
    )).all()

    champions_by_job: dict[str, list] = defaultdict(list)
    for row in recent_champions:
        champions_by_job[row.job_id].append(row)

    recent_runs = []
    for job in recent_jobs:
        rows = sorted(
            champions_by_job.get(job.id, []),
            key=lambda r: (r.sheet_name or "", r.metric_name or ""),
        )
        recent_runs.append(RecentRun(
            job_id=job.id,
            name=job.name,
            file_name=job.file_name,
            status=job.status,
            created_at=job.created_at,
            champion_model=rows[0].model_name if rows else None,
            metric_count=len(rows),
            wmape=per_run_wmape(r.wmape for r in rows),
        ))

    # 4 ─ accuracy trend: champion scores for the newest successful runs that
    #     have at least one score, limited in SQL.
    scored_jobs = (
        select(
            ForecastJob.id.label("job_id"),
            ForecastJob.created_at.label("created_at"),
        )
        .join(ModelRun, ModelRun.job_id == ForecastJob.id)
        .where(
            ForecastJob.user_id == user_id,
            ForecastJob.status == "success",
            ModelRun.is_champion.is_(True),
            ModelRun.wmape.is_not(None),
        )
        .group_by(ForecastJob.id, ForecastJob.created_at)
        .order_by(ForecastJob.created_at.desc(), ForecastJob.id.desc())
        .limit(TREND_WINDOW)
        .subquery()
    )
    trend_rows = (await db.execute(
        select(scored_jobs.c.job_id, scored_jobs.c.created_at, ModelRun.wmape)
        .join(ModelRun, ModelRun.job_id == scored_jobs.c.job_id)
        .where(ModelRun.is_champion.is_(True), ModelRun.wmape.is_not(None))
    )).all()

    trend_wmapes: dict[str, list] = defaultdict(list)
    trend_created: dict[str, object] = {}
    for job_id, created_at, wmape in trend_rows:
        trend_wmapes[job_id].append(wmape)
        trend_created[job_id] = created_at

    accuracy_trend = []
    for job_id, wmapes in trend_wmapes.items():
        value = per_run_wmape(wmapes)
        if value is not None:
            accuracy_trend.append(
                TrendPoint(job_id=job_id, created_at=trend_created[job_id], wmape=value)
            )
    accuracy_trend.sort(key=lambda p: (p.created_at, p.job_id))

    # 5 ─ demand mix over distinct series, latest run wins. A series is
    #     (file, sheet, metric); jobs with no file_name (pre-F6 rows) fall back
    #     to their own id so they aren't merged with each other.
    series_file = func.coalesce(ForecastJob.file_name, cast(ForecastJob.id, String))
    mix_rows = (await db.execute(
        select(ModelRun.demand_type)
        .join(ForecastJob, ForecastJob.id == ModelRun.job_id)
        .where(ForecastJob.user_id == user_id, ModelRun.is_champion.is_(True))
        .distinct(series_file, ModelRun.sheet_name, ModelRun.metric_name)
        .order_by(
            series_file, ModelRun.sheet_name, ModelRun.metric_name,
            ForecastJob.created_at.desc(), ForecastJob.id.desc(),
        )
    )).scalars().all()

    mix = Counter(dt if dt in _DEMAND_TYPES else "unclassified" for dt in mix_rows)

    # 6 ─ active runs. Only the list comes from here: progress_pct is written
    #     at start and finish only, so live percentages are polled per row
    #     from GET /forecast/{job_id}/progress.
    active_jobs = (await db.execute(
        select(ForecastJob)
        .where(
            ForecastJob.user_id == user_id,
            ForecastJob.status.in_(ACTIVE_STATUSES),
        )
        .order_by(ForecastJob.created_at.desc(), ForecastJob.id.desc())
        .limit(ACTIVE_RUNS_LIMIT)
    )).scalars().all()

    active_runs = [
        ActiveRun(
            job_id=job.id,
            name=job.name,
            file_name=job.file_name,
            status=job.status,
            created_at=job.created_at,
            started_at=job.started_at,
        )
        for job in active_jobs
    ]

    # 7 ─ run time over the newest successful runs with a usable duration.
    #     A completed_at before started_at is a clock problem, not a run.
    duration = func.extract("epoch", ForecastJob.completed_at - ForecastJob.started_at)
    timed_rows = (await db.execute(
        select(
            ForecastJob.id, ForecastJob.name, ForecastJob.file_name,
            ForecastJob.created_at, duration,
        )
        .where(
            ForecastJob.user_id == user_id,
            ForecastJob.status == "success",
            ForecastJob.started_at.is_not(None),
            ForecastJob.completed_at.is_not(None),
            ForecastJob.completed_at >= ForecastJob.started_at,
        )
        .order_by(ForecastJob.created_at.desc(), ForecastJob.id.desc())
        .limit(RUN_TIME_WINDOW)
    )).all()

    timed_runs = [
        RunDuration(
            job_id=job_id, name=name, file_name=file_name,
            created_at=created_at, duration_seconds=float(seconds),
        )
        for job_id, name, file_name, created_at, seconds in timed_rows
    ]
    slowest_runs = sorted(
        timed_runs, key=lambda r: (-r.duration_seconds, r.job_id)
    )[:SLOWEST_RUNS_LIMIT]

    # 8 ─ which models win. Every run-metric a model won counts, so re-running
    #     a file counts again — "won 7 of your 10 runs" is the honest reading.
    win_rows = (await db.execute(
        select(ModelRun.model_name, func.count())
        .join(ForecastJob, ForecastJob.id == ModelRun.job_id)
        .where(
            ForecastJob.user_id == user_id,
            ModelRun.is_champion.is_(True),
            ModelRun.model_name.is_not(None),
        )
        .group_by(ModelRun.model_name)
    )).all()

    model_wins = sorted(
        (ModelWin(model_name=name, wins=count) for name, count in win_rows),
        key=lambda w: (-w.wins, w.model_name),
    )

    return DashboardSummary(
        total_runs=total,
        status_counts=status_counts,
        success_rate=success_rate(status_counts.success, status_counts.failed),
        median_wmape=median_or_none(p.wmape for p in accuracy_trend),
        last_run_at=last_run_at,
        recent_runs=recent_runs,
        accuracy_trend=accuracy_trend,
        demand_mix=DemandMix(**mix),
        active_runs=active_runs,
        median_run_seconds=median_or_none(r.duration_seconds for r in timed_runs),
        slowest_runs=slowest_runs,
        model_wins=model_wins,
    )
