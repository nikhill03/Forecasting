"""
backend/tests/test_dashboard.py
================================
Tests for the dashboard summary (F15): the metric definitions as pure
functions, the owner-scoped endpoint, and the fixed statement count.

Timestamps: ForecastJob.created_at defaults to Postgres now(), which is the
*transaction* start time — every job created inside one test would share it,
so ordering assertions would pass or fail by accident. Every job here gets an
explicit created_at.

Filename note: no "." in the module name — `test_p2.5-*.py` would break
pytest's dotted import under backend/tests/__init__.py.
"""

from __future__ import annotations

import math
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event

from backend.models.db_models import ForecastJob, ModelRun
from backend.services.dashboard import (
    ACTIVE_RUNS_LIMIT,
    RECENT_RUNS_LIMIT,
    RUN_TIME_WINDOW,
    SLOWEST_RUNS_LIMIT,
    TREND_WINDOW,
    build_dashboard_summary,
    median_or_none,
    per_run_wmape,
    success_rate,
)

BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _at(minutes: int) -> datetime:
    return BASE_TIME + timedelta(minutes=minutes)


async def _job(
    db, user_id, *, minute, status="success", file_name="sales.csv", name=None,
    run_seconds=None, started_at=None, completed_at=None,
):
    """`run_seconds` is a shortcut: started at the job's minute, finished
    that many seconds later. Pass started_at/completed_at to set them freely."""
    if run_seconds is not None:
        started_at = _at(minute)
        completed_at = started_at + timedelta(seconds=run_seconds)
    job = ForecastJob(
        id=str(uuid.uuid4()),
        user_id=user_id,
        status=status,
        progress_pct=100,
        file_name=file_name,
        name=name,
        created_at=_at(minute),
        started_at=started_at,
        completed_at=completed_at,
    )
    db.add(job)
    await db.flush()
    return job


async def _run(
    db, job_id, model_name="Prophet", *, champion=True, wmape=0.1,
    demand_type="Smooth", sheet="Sheet1", metric="Sales",
):
    run = ModelRun(
        id=str(uuid.uuid4()),
        job_id=job_id,
        sheet_name=sheet,
        metric_name=metric,
        model_name=model_name,
        stage="Univariate",
        wmape=wmape,
        demand_type=demand_type,
        is_champion=champion,
        status="completed",
    )
    db.add(run)
    await db.flush()
    return run


@contextmanager
def count_statements():
    """Counts SQL statements issued on the test engine while active."""
    from backend.core.database import engine

    counter = {"n": 0}

    def _on_execute(conn, cursor, statement, parameters, context, executemany):
        counter["n"] += 1

    event.listen(engine.sync_engine, "before_cursor_execute", _on_execute)
    try:
        yield counter
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _on_execute)


# ══════════════════════════════════════════════════════════════════
# Pure arithmetic
# ══════════════════════════════════════════════════════════════════

class TestMedianOrNone:

    def test_odd_count(self):
        assert median_or_none([0.3, 0.1, 0.2]) == 0.2

    def test_even_count(self):
        assert median_or_none([0.1, 0.3]) == pytest.approx(0.2)

    def test_ignores_none(self):
        assert median_or_none([None, 0.4, None]) == 0.4

    @pytest.mark.parametrize("bad", [math.inf, -math.inf, math.nan])
    def test_ignores_non_finite(self, bad):
        assert median_or_none([bad, 0.5]) == 0.5

    @pytest.mark.parametrize("values", [[], [None], [math.nan, None]])
    def test_nothing_usable_is_none(self, values):
        assert median_or_none(values) is None

    def test_zero_is_a_real_score(self):
        assert median_or_none([0.0]) == 0.0

    def test_median_resists_one_outlier(self):
        # Real champion WMAPEs span 0.0012–2.54; the mean of this set would
        # be ~0.9 and describe none of the runs.
        assert median_or_none([0.05, 0.07, 2.54]) == 0.07


class TestPerRunWmape:

    def test_single_metric(self):
        assert per_run_wmape([0.12]) == 0.12

    def test_multi_metric_is_median(self):
        assert per_run_wmape([0.1, 0.3]) == pytest.approx(0.2)


class TestSuccessRate:

    def test_basic(self):
        assert success_rate(3, 1) == 0.75

    def test_nothing_finished_is_none(self):
        assert success_rate(0, 0) is None

    def test_all_failed(self):
        assert success_rate(0, 4) == 0.0


# ══════════════════════════════════════════════════════════════════
# Endpoint
# ══════════════════════════════════════════════════════════════════

class TestDashboardEndpoint:

    async def test_requires_auth(self, async_client):
        res = await async_client.get("/api/v1/dashboard")
        assert res.status_code == 401

    async def test_empty_account(self, async_client, test_user, make_auth_headers):
        res = await async_client.get("/api/v1/dashboard", headers=make_auth_headers(test_user))
        assert res.status_code == 200

        body = res.json()
        assert body["total_runs"] == 0
        assert body["success_rate"] is None
        assert body["median_wmape"] is None
        assert body["last_run_at"] is None
        assert body["recent_runs"] == []
        assert body["accuracy_trend"] == []
        assert body["demand_mix"] == {
            "Smooth": 0, "Erratic": 0, "Intermittent": 0, "Lumpy": 0, "unclassified": 0,
        }
        assert body["active_runs"] == []
        assert body["median_run_seconds"] is None
        assert body["slowest_runs"] == []
        assert body["model_wins"] == []

    async def test_populated_shape(
        self, async_client, db_session, test_user, make_auth_headers
    ):
        job = await _job(db_session, test_user.id, minute=1, name="Q3 sales")
        await _run(db_session, job.id, "Prophet", wmape=0.07)

        res = await async_client.get("/api/v1/dashboard", headers=make_auth_headers(test_user))
        body = res.json()

        assert body["total_runs"] == 1
        assert body["success_rate"] == 1.0
        assert body["median_wmape"] == pytest.approx(0.07)
        assert body["recent_runs"][0]["champion_model"] == "Prophet"
        assert body["recent_runs"][0]["name"] == "Q3 sales"
        assert body["demand_mix"]["Smooth"] == 1

    async def test_owner_scoped(
        self, async_client, db_session, test_user, second_user, make_auth_headers
    ):
        for i in range(3):
            job = await _job(db_session, test_user.id, minute=i)
            await _run(db_session, job.id)

        res = await async_client.get(
            "/api/v1/dashboard", headers=make_auth_headers(second_user)
        )
        body = res.json()
        assert body["total_runs"] == 0
        assert body["recent_runs"] == []
        assert body["demand_mix"]["Smooth"] == 0


# ══════════════════════════════════════════════════════════════════
# Aggregation semantics (service called directly)
# ══════════════════════════════════════════════════════════════════

class TestChampionOnly:

    async def test_losers_do_not_count(self, db_session, test_user):
        """One champion + 13 losers must read as one run, one score, one series."""
        job = await _job(db_session, test_user.id, minute=1)
        await _run(db_session, job.id, "Prophet", champion=True, wmape=0.1)
        for i in range(13):
            await _run(db_session, job.id, f"Loser{i}", champion=False, wmape=0.9,
                       demand_type="Lumpy")

        s = await build_dashboard_summary(db_session, test_user.id)

        assert s.median_wmape == pytest.approx(0.1)
        assert len(s.accuracy_trend) == 1
        assert s.recent_runs[0].champion_model == "Prophet"
        assert s.recent_runs[0].metric_count == 1
        assert s.demand_mix.Smooth == 1
        assert s.demand_mix.Lumpy == 0


class TestStatusCounting:

    async def test_success_rate_ignores_stopped_and_running(self, db_session, test_user):
        statuses = ["success"] * 3 + ["failed"] + ["stopped"] * 2 + ["running"]
        for i, st in enumerate(statuses):
            await _job(db_session, test_user.id, minute=i, status=st)

        s = await build_dashboard_summary(db_session, test_user.id)

        assert s.total_runs == 7
        assert s.success_rate == 0.75
        assert s.status_counts.stopped == 2
        assert s.status_counts.running == 1

    async def test_success_rate_none_when_nothing_finished(self, db_session, test_user):
        await _job(db_session, test_user.id, minute=1, status="running")
        await _job(db_session, test_user.id, minute=2, status="stopped")

        s = await build_dashboard_summary(db_session, test_user.id)
        assert s.total_runs == 2
        assert s.success_rate is None

    async def test_last_run_at_is_newest_any_status(self, db_session, test_user):
        await _job(db_session, test_user.id, minute=1, status="success")
        await _job(db_session, test_user.id, minute=9, status="failed")

        s = await build_dashboard_summary(db_session, test_user.id)
        assert s.last_run_at == _at(9)


class TestRecentRuns:

    async def test_capped_and_newest_first(self, db_session, test_user):
        jobs = [await _job(db_session, test_user.id, minute=i) for i in range(8)]

        s = await build_dashboard_summary(db_session, test_user.id)

        assert len(s.recent_runs) == RECENT_RUNS_LIMIT
        assert [r.job_id for r in s.recent_runs] == [j.id for j in reversed(jobs)][:5]

    async def test_includes_unsuccessful_runs(self, db_session, test_user):
        await _job(db_session, test_user.id, minute=1, status="failed")

        s = await build_dashboard_summary(db_session, test_user.id)
        run = s.recent_runs[0]
        assert run.status == "failed"
        assert run.champion_model is None
        assert run.metric_count == 0
        assert run.wmape is None

    async def test_multi_metric_run(self, db_session, test_user):
        job = await _job(db_session, test_user.id, minute=1)
        await _run(db_session, job.id, "Ridge", metric="Units", wmape=0.3)
        await _run(db_session, job.id, "Prophet", metric="Sales", wmape=0.1)

        s = await build_dashboard_summary(db_session, test_user.id)
        run = s.recent_runs[0]
        assert run.champion_model == "Prophet"   # "Sales" sorts before "Units"
        assert run.metric_count == 2
        assert run.wmape == pytest.approx(0.2)


class TestAccuracyTrend:

    async def test_oldest_to_newest_and_capped(self, db_session, test_user):
        jobs = []
        for i in range(25):
            job = await _job(db_session, test_user.id, minute=i)
            await _run(db_session, job.id, wmape=0.01 * (i + 1))
            jobs.append(job)

        s = await build_dashboard_summary(db_session, test_user.id)

        assert len(s.accuracy_trend) == TREND_WINDOW
        # The newest 20 runs, i.e. minutes 5..24, oldest first.
        assert [p.job_id for p in s.accuracy_trend] == [j.id for j in jobs[5:]]
        assert [p.created_at for p in s.accuracy_trend] == sorted(
            p.created_at for p in s.accuracy_trend
        )

    async def test_unsuccessful_and_unscored_runs_excluded(self, db_session, test_user):
        good = await _job(db_session, test_user.id, minute=1)
        await _run(db_session, good.id, wmape=0.2)

        failed = await _job(db_session, test_user.id, minute=2, status="failed")
        await _run(db_session, failed.id, wmape=0.9)

        unscored = await _job(db_session, test_user.id, minute=3)
        await _run(db_session, unscored.id, wmape=None)

        s = await build_dashboard_summary(db_session, test_user.id)

        assert [p.job_id for p in s.accuracy_trend] == [good.id]
        assert s.median_wmape == pytest.approx(0.2)

    async def test_null_scores_do_not_count_as_zero(self, db_session, test_user):
        job = await _job(db_session, test_user.id, minute=1)
        await _run(db_session, job.id, metric="Sales", wmape=0.4)
        await _run(db_session, job.id, metric="Units", wmape=None)

        s = await build_dashboard_summary(db_session, test_user.id)
        assert s.accuracy_trend[0].wmape == pytest.approx(0.4)


class TestDemandMix:

    async def test_same_series_counted_once_latest_wins(self, db_session, test_user):
        old = await _job(db_session, test_user.id, minute=1, file_name="parts.csv")
        await _run(db_session, old.id, demand_type="Smooth")
        new = await _job(db_session, test_user.id, minute=2, file_name="parts.csv")
        await _run(db_session, new.id, demand_type="Lumpy")

        s = await build_dashboard_summary(db_session, test_user.id)
        assert s.demand_mix.Lumpy == 1
        assert s.demand_mix.Smooth == 0

    async def test_different_metrics_are_different_series(self, db_session, test_user):
        job = await _job(db_session, test_user.id, minute=1)
        await _run(db_session, job.id, metric="Sales", demand_type="Smooth")
        await _run(db_session, job.id, metric="Units", demand_type="Erratic")

        s = await build_dashboard_summary(db_session, test_user.id)
        assert (s.demand_mix.Smooth, s.demand_mix.Erratic) == (1, 1)

    async def test_null_demand_type_is_unclassified(self, db_session, test_user):
        job = await _job(db_session, test_user.id, minute=1)
        await _run(db_session, job.id, demand_type=None)

        s = await build_dashboard_summary(db_session, test_user.id)
        assert s.demand_mix.unclassified == 1

    async def test_missing_file_name_is_not_merged(self, db_session, test_user):
        """Pre-F6 jobs have no file_name; they must not collapse into one series."""
        for i in range(2):
            job = await _job(db_session, test_user.id, minute=i, file_name=None)
            await _run(db_session, job.id, demand_type="Smooth")

        s = await build_dashboard_summary(db_session, test_user.id)
        assert s.demand_mix.Smooth == 2


class TestActiveRuns:

    async def test_only_pending_and_running_newest_first(self, db_session, test_user):
        await _job(db_session, test_user.id, minute=1, status="success")
        running = await _job(db_session, test_user.id, minute=2, status="running")
        pending = await _job(db_session, test_user.id, minute=3, status="pending")
        await _job(db_session, test_user.id, minute=4, status="failed")
        await _job(db_session, test_user.id, minute=5, status="stopped")

        s = await build_dashboard_summary(db_session, test_user.id)
        assert [r.job_id for r in s.active_runs] == [pending.id, running.id]

    async def test_capped(self, db_session, test_user):
        jobs = [
            await _job(db_session, test_user.id, minute=i, status="running")
            for i in range(ACTIVE_RUNS_LIMIT + 2)
        ]

        s = await build_dashboard_summary(db_session, test_user.id)
        assert [r.job_id for r in s.active_runs] == [
            j.id for j in reversed(jobs)
        ][:ACTIVE_RUNS_LIMIT]

    async def test_owner_scoped(self, db_session, user_factory):
        owner, other = await user_factory(), await user_factory()
        await _job(db_session, owner.id, minute=1, status="running")
        await _job(db_session, other.id, minute=2, status="success")

        s = await build_dashboard_summary(db_session, other.id)
        assert s.active_runs == []


class TestRunTime:

    async def test_median_and_slowest(self, db_session, test_user):
        for i, secs in enumerate([60, 240, 120]):
            await _job(db_session, test_user.id, minute=i, run_seconds=secs)

        s = await build_dashboard_summary(db_session, test_user.id)
        assert s.median_run_seconds == pytest.approx(120)
        assert [r.duration_seconds for r in s.slowest_runs] == [240, 120, 60]

    async def test_slowest_capped(self, db_session, test_user):
        for i in range(SLOWEST_RUNS_LIMIT + 3):
            await _job(db_session, test_user.id, minute=i, run_seconds=10 * (i + 1))

        s = await build_dashboard_summary(db_session, test_user.id)
        assert len(s.slowest_runs) == SLOWEST_RUNS_LIMIT
        assert s.slowest_runs[0].duration_seconds == pytest.approx(60)

    async def test_unusable_rows_excluded(self, db_session, test_user):
        good = await _job(db_session, test_user.id, minute=1, run_seconds=100)
        # started but never finished
        await _job(db_session, test_user.id, minute=2, started_at=_at(2))
        # finished without a start
        await _job(db_session, test_user.id, minute=3, completed_at=_at(3))
        # clock problem: finished before it started
        await _job(db_session, test_user.id, minute=4,
                   started_at=_at(10), completed_at=_at(4))
        # a failed run with timing is not a completed run
        await _job(db_session, test_user.id, minute=5, status="failed", run_seconds=900)

        s = await build_dashboard_summary(db_session, test_user.id)
        assert s.median_run_seconds == pytest.approx(100)
        assert [r.job_id for r in s.slowest_runs] == [good.id]

    async def test_window_is_newest_runs(self, db_session, test_user):
        # Durations grow with age of creation: minute i ran for i+1 seconds.
        for i in range(RUN_TIME_WINDOW + 5):
            await _job(db_session, test_user.id, minute=i, run_seconds=i + 1)

        s = await build_dashboard_summary(db_session, test_user.id)
        # Newest 20 are minutes 5..24 → 6..25 seconds.
        assert s.median_run_seconds == pytest.approx(15.5)
        assert s.slowest_runs[0].duration_seconds == pytest.approx(25)

    async def test_no_timing_is_none(self, db_session, test_user):
        await _job(db_session, test_user.id, minute=1)

        s = await build_dashboard_summary(db_session, test_user.id)
        assert s.median_run_seconds is None
        assert s.slowest_runs == []


class TestModelWins:

    async def test_champion_only_every_run_counts(self, db_session, test_user):
        for i in range(3):
            job = await _job(db_session, test_user.id, minute=i)
            await _run(db_session, job.id, "Prophet", champion=True)
            await _run(db_session, job.id, "Theta", champion=False)
        job = await _job(db_session, test_user.id, minute=9)
        await _run(db_session, job.id, "Ridge", champion=True)

        s = await build_dashboard_summary(db_session, test_user.id)
        assert [(w.model_name, w.wins) for w in s.model_wins] == [
            ("Prophet", 3), ("Ridge", 1),
        ]

    async def test_null_model_excluded(self, db_session, test_user):
        job = await _job(db_session, test_user.id, minute=1)
        await _run(db_session, job.id, None, champion=True)

        s = await build_dashboard_summary(db_session, test_user.id)
        assert s.model_wins == []

    async def test_ties_sorted_by_name(self, db_session, test_user):
        for i, name in enumerate(["B", "A", "B", "A", "C"]):
            job = await _job(db_session, test_user.id, minute=i)
            await _run(db_session, job.id, name)

        s = await build_dashboard_summary(db_session, test_user.id)
        assert [w.model_name for w in s.model_wins] == ["A", "B", "C"]


class TestNoNPlusOne:

    async def test_statement_count_does_not_grow_with_runs(
        self, db_session, user_factory
    ):
        small = await user_factory()
        job = await _job(db_session, small.id, minute=1)
        await _run(db_session, job.id)

        large = await user_factory()
        for i in range(25):
            job = await _job(db_session, large.id, minute=i, run_seconds=30 + i)
            await _run(db_session, job.id, f"Model{i % 4}", sheet=f"S{i}")
        for i in range(3):
            await _job(db_session, large.id, minute=100 + i, status="running")

        # Everything above is already flushed, so the counter only sees reads.
        with count_statements() as small_count:
            await build_dashboard_summary(db_session, small.id)
        with count_statements() as large_count:
            await build_dashboard_summary(db_session, large.id)

        assert small_count["n"] == large_count["n"]
        assert large_count["n"] == 8
