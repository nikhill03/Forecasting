"""
backend/tests/test_model_leaderboard.py
========================================
Tests for the model leaderboard (F14).

Two halves:

1. `_leaderboard_rows` and friends in backend/tasks/forecast_task.py, tested
   as pure functions. The row builder was deliberately split out of
   `_save_model_runs_sync` so the interesting logic — the champion
   invariant, the pre-F14 fallback, non-finite handling — is testable
   without a DB connection. That matters here because the Celery task writes
   through its own psycopg2 connection, which bypasses db_session's SAVEPOINT
   and would leak committed rows across tests.

2. The job-history regression. `GET /forecast` maps every ModelRun row to a
   metric summary; since this table now holds one row per model *tried*, the
   query must filter on is_champion or each job reports ~10 "metrics" per
   metric.

Filename note: no "." in the module name — `test_p2.5-*.py` would break
pytest's dotted import under backend/tests/__init__.py.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from backend.models.db_models import ForecastJob, ModelRun
from backend.tasks.forecast_task import _finite, _leaderboard_rows, _rows_for_metric

# Column order of the INSERT in forecast_task._MODEL_RUN_INSERT.
COL = {
    "id": 0, "job_id": 1, "sheet_name": 2, "metric_name": 3, "model_name": 4,
    "stage": 5, "wmape": 6, "mae": 7, "mape": 8, "rmse": 9, "accuracy": 10,
    "composite_score": 11, "demand_type": 12, "adi": 13, "cv2": 14,
    "is_champion": 15, "status": 16, "error_message": 17,
}


def _entry(name, **over):
    base = {
        "model_name": name,
        "stage": "Univariate",
        "wmape": 0.1,
        "mae": 1.0,
        "mape": 2.0,
        "rmse": 3.0,
        "accuracy": 90.0,
        "composite_score": 0.2,
        "status": "completed",
        "error_message": None,
    }
    base.update(over)
    return base


def _metric(best="Prophet", leaderboard=None, **over):
    data = {
        "best_model": best,
        "wmape": 0.1,
        "mae": 1.0,
        "mape": 2.0,
        "rmse": 3.0,
        "accuracy": 90.0,
        "composite_score": 0.2,
        "demand_profile": {"demand_type": "Smooth", "adi": 1.0, "cv2": 0.01},
    }
    if leaderboard is not None:
        data["model_leaderboard"] = leaderboard
    data.update(over)
    return data


def _results(metric_data, sheet="Sheet1", metric="Sales"):
    return {sheet: {"metrics": {metric: metric_data}}}


# ══════════════════════════════════════════════════════════════════
# _finite — non-finite sanitisation
# ══════════════════════════════════════════════════════════════════

class TestFinite:

    @pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
    def test_non_finite_becomes_none(self, value):
        """Both engines use inf as a "no valid points" sentinel. json.dump
        emits it as a bare `Infinity`, which JSON.parse rejects — so it must
        never reach the stored payload or the DB."""
        assert _finite(value) is None

    @pytest.mark.parametrize("value,expected", [(0.0, 0.0), (1.5, 1.5), (-2.0, -2.0)])
    def test_finite_values_pass_through(self, value, expected):
        assert _finite(value) == expected

    def test_zero_is_preserved_not_treated_as_missing(self):
        # A perfect score is a real score.
        assert _finite(0.0) == 0.0
        assert _finite(0.0) is not None

    @pytest.mark.parametrize("value", [None, "abc", object()])
    def test_unusable_values_become_none(self, value):
        assert _finite(value) is None


# ══════════════════════════════════════════════════════════════════
# Row building
# ══════════════════════════════════════════════════════════════════

class TestRowsForMetric:

    def test_one_row_per_model_tried(self):
        lb = [_entry("Prophet"), _entry("TBATS"), _entry("Ridge")]
        rows = _rows_for_metric("job-1", "Sheet1", "Sales", _metric(leaderboard=lb))

        assert len(rows) == 3
        assert {r[COL["model_name"]] for r in rows} == {"Prophet", "TBATS", "Ridge"}

    def test_exactly_one_champion(self):
        lb = [_entry("Prophet"), _entry("TBATS"), _entry("Ridge")]
        rows = _rows_for_metric("job-1", "Sheet1", "Sales", _metric(leaderboard=lb))

        champions = [r for r in rows if r[COL["is_champion"]]]
        assert len(champions) == 1

    def test_champion_matches_best_model(self):
        """The leaderboard must never disagree with the headline."""
        lb = [_entry("Prophet"), _entry("TBATS")]
        rows = _rows_for_metric(
            "job-1", "Sheet1", "Sales", _metric(best="TBATS", leaderboard=lb)
        )

        champion = next(r for r in rows if r[COL["is_champion"]])
        assert champion[COL["model_name"]] == "TBATS"

    def test_champion_flag_is_derived_not_trusted(self):
        """An entry that claims to be champion but isn't best_model loses the
        flag — derivation from best_model is what guarantees agreement."""
        lb = [_entry("Prophet", is_champion=True), _entry("TBATS")]
        rows = _rows_for_metric(
            "job-1", "Sheet1", "Sales", _metric(best="TBATS", leaderboard=lb)
        )

        champion = next(r for r in rows if r[COL["is_champion"]])
        assert champion[COL["model_name"]] == "TBATS"

    def test_duplicate_model_names_yield_one_champion(self):
        lb = [_entry("Prophet"), _entry("Prophet")]
        rows = _rows_for_metric("job-1", "Sheet1", "Sales", _metric(leaderboard=lb))

        assert sum(1 for r in rows if r[COL["is_champion"]]) == 1

    def test_champion_row_synthesised_when_missing_from_leaderboard(self):
        """Job history filters on is_champion, so a group with no champion
        would vanish from that page entirely."""
        lb = [_entry("TBATS"), _entry("Ridge")]
        rows = _rows_for_metric(
            "job-1", "Sheet1", "Sales", _metric(best="Prophet", leaderboard=lb)
        )

        assert len(rows) == 3
        champion = next(r for r in rows if r[COL["is_champion"]])
        assert champion[COL["model_name"]] == "Prophet"

    def test_failed_and_skipped_statuses_survive(self):
        lb = [
            _entry("Prophet"),
            _entry("TBATS", status="failed", error_message="timeout", wmape=None),
            _entry("Croston", status="skipped", error_message="Insufficient overlap"),
        ]
        rows = _rows_for_metric("job-1", "Sheet1", "Sales", _metric(leaderboard=lb))

        by_name = {r[COL["model_name"]]: r for r in rows}
        assert by_name["TBATS"][COL["status"]] == "failed"
        assert by_name["TBATS"][COL["error_message"]] == "timeout"
        assert by_name["Croston"][COL["status"]] == "skipped"
        assert by_name["Prophet"][COL["status"]] == "completed"

    def test_non_finite_scores_are_sanitised(self):
        lb = [_entry("Prophet", wmape=float("inf"), composite_score=float("nan"))]
        rows = _rows_for_metric("job-1", "Sheet1", "Sales", _metric(leaderboard=lb))

        assert rows[0][COL["wmape"]] is None
        assert rows[0][COL["composite_score"]] is None

    def test_demand_profile_is_copied_onto_every_row(self):
        lb = [_entry("Prophet"), _entry("TBATS")]
        rows = _rows_for_metric("job-1", "Sheet1", "Sales", _metric(leaderboard=lb))

        for row in rows:
            assert row[COL["demand_type"]] == "Smooth"
            assert row[COL["adi"]] == 1.0

    def test_stage_defaults_to_univariate(self):
        lb = [{"model_name": "Prophet"}]
        rows = _rows_for_metric("job-1", "Sheet1", "Sales", _metric(leaderboard=lb))
        assert rows[0][COL["stage"]] == "Univariate"

    def test_multivariate_stage_preserved(self):
        lb = [_entry("Ridge", stage="Multivariate")]
        rows = _rows_for_metric(
            "job-1", "Sheet1", "Sales", _metric(best="Ridge", leaderboard=lb)
        )
        assert rows[0][COL["stage"]] == "Multivariate"


class TestPreF14Fallback:
    """A partially-upgraded pipeline should lose the leaderboard, not the run."""

    def test_missing_leaderboard_degrades_to_single_champion_row(self):
        rows = _rows_for_metric("job-1", "Sheet1", "Sales", _metric())

        assert len(rows) == 1
        assert rows[0][COL["model_name"]] == "Prophet"
        assert rows[0][COL["is_champion"]] is True
        assert rows[0][COL["wmape"]] == 0.1

    def test_empty_leaderboard_degrades_the_same_way(self):
        rows = _rows_for_metric("job-1", "Sheet1", "Sales", _metric(leaderboard=[]))
        assert len(rows) == 1
        assert rows[0][COL["is_champion"]] is True

    def test_fallback_marks_multivariate_stage(self):
        data = _metric(is_multivariate=True)
        rows = _rows_for_metric("job-1", "Sheet1", "Sales", data)
        assert rows[0][COL["stage"]] == "Multivariate"

    def test_no_best_model_and_no_leaderboard_yields_no_champion(self):
        rows = _rows_for_metric("job-1", "Sheet1", "Sales", _metric(best=None))
        assert all(not r[COL["is_champion"]] for r in rows)


class TestLeaderboardRows:

    def test_walks_sheets_and_metrics(self):
        results = {
            "Sheet1": {"metrics": {
                "Sales": _metric(leaderboard=[_entry("Prophet"), _entry("TBATS")]),
                "Units": _metric(leaderboard=[_entry("Prophet")]),
            }},
            "Sheet2": {"metrics": {
                "Sales": _metric(leaderboard=[_entry("Prophet")]),
            }},
        }
        rows = _leaderboard_rows("job-1", results)

        assert len(rows) == 4
        assert sum(1 for r in rows if r[COL["is_champion"]]) == 3   # one per group

    def test_handles_flat_structure_without_metrics_key(self):
        results = {"Sheet1": {"Sales": _metric(leaderboard=[_entry("Prophet")])}}
        rows = _leaderboard_rows("job-1", results)
        assert len(rows) == 1

    def test_job_id_stamped_on_every_row(self):
        results = _results(_metric(leaderboard=[_entry("A"), _entry("B")]))
        rows = _leaderboard_rows("job-xyz", results)
        assert all(r[COL["job_id"]] == "job-xyz" for r in rows)

    def test_row_ids_are_unique(self):
        results = _results(
            _metric(best="A", leaderboard=[_entry("A"), _entry("B"), _entry("C")])
        )
        rows = _leaderboard_rows("job-1", results)
        assert len(rows) == 3
        assert len({r[COL["id"]] for r in rows}) == len(rows)

    @pytest.mark.parametrize("results", [None, {}, "nonsense", {"Sheet1": None}])
    def test_malformed_results_yield_no_rows(self, results):
        assert _leaderboard_rows("job-1", results) == []

    def test_non_dict_entries_are_skipped(self):
        data = _metric(leaderboard=[_entry("Prophet"), "garbage", None])
        rows = _rows_for_metric("job-1", "Sheet1", "Sales", data)
        assert len(rows) == 1

    def test_row_width_matches_insert_column_count(self):
        rows = _leaderboard_rows("job-1", _results(_metric(leaderboard=[_entry("A")])))
        assert len(rows[0]) == len(COL)


# ══════════════════════════════════════════════════════════════════
# Job-history regression — GET /forecast must return champions only
# ══════════════════════════════════════════════════════════════════

async def _make_job(db_session, owner_id: str) -> ForecastJob:
    job = ForecastJob(
        id=str(uuid.uuid4()),
        user_id=owner_id,
        status="success",
        progress_pct=100,
        created_at=datetime.now(timezone.utc),
    )
    db_session.add(job)
    await db_session.flush()
    return job


async def _add_run(db_session, job_id, model_name, *, champion=False, status="completed"):
    run = ModelRun(
        id=str(uuid.uuid4()),
        job_id=job_id,
        sheet_name="Sheet1",
        metric_name="Sales",
        model_name=model_name,
        stage="Univariate",
        wmape=0.1,
        is_champion=champion,
        status=status,
    )
    db_session.add(run)
    await db_session.flush()
    return run


class TestJobHistoryChampionFilter:

    async def test_only_champion_appears_in_job_summary(
        self, async_client, db_session, test_user, make_auth_headers
    ):
        """One champion + nine losers must still read as ONE metric summary.
        Without the is_champion filter the history page would show ten."""
        job = await _make_job(db_session, test_user.id)
        await _add_run(db_session, job.id, "Prophet", champion=True)
        for name in ["TBATS", "Ridge", "Lasso", "LightGBM", "HistGB",
                     "Croston", "SES", "Holt", "ARIMA"]:
            await _add_run(db_session, job.id, name)

        res = await async_client.get(
            "/api/v1/forecast", headers=make_auth_headers(test_user)
        )
        assert res.status_code == 200

        target = next(j for j in res.json()["jobs"] if j["job_id"] == job.id)
        assert len(target["metrics"]) == 1
        assert target["metrics"][0]["model_name"] == "Prophet"

    async def test_failed_models_do_not_leak_into_summary(
        self, async_client, db_session, test_user, make_auth_headers
    ):
        job = await _make_job(db_session, test_user.id)
        await _add_run(db_session, job.id, "Prophet", champion=True)
        await _add_run(db_session, job.id, "TBATS", status="failed")

        res = await async_client.get(
            "/api/v1/forecast", headers=make_auth_headers(test_user)
        )
        target = next(j for j in res.json()["jobs"] if j["job_id"] == job.id)
        assert len(target["metrics"]) == 1

    async def test_job_with_no_champion_reports_no_metrics(
        self, async_client, db_session, test_user, make_auth_headers
    ):
        job = await _make_job(db_session, test_user.id)
        await _add_run(db_session, job.id, "TBATS")

        res = await async_client.get(
            "/api/v1/forecast", headers=make_auth_headers(test_user)
        )
        target = next(j for j in res.json()["jobs"] if j["job_id"] == job.id)
        assert target["metrics"] == []

    async def test_multiple_metrics_each_contribute_their_champion(
        self, async_client, db_session, test_user, make_auth_headers
    ):
        job = await _make_job(db_session, test_user.id)
        for metric_name, winner in [("Sales", "Prophet"), ("Units", "Ridge")]:
            for name in [winner, "TBATS", "Lasso"]:
                run = ModelRun(
                    id=str(uuid.uuid4()),
                    job_id=job.id,
                    sheet_name="Sheet1",
                    metric_name=metric_name,
                    model_name=name,
                    stage="Univariate",
                    wmape=0.1,
                    is_champion=(name == winner),
                )
                db_session.add(run)
        await db_session.flush()

        res = await async_client.get(
            "/api/v1/forecast", headers=make_auth_headers(test_user)
        )
        target = next(j for j in res.json()["jobs"] if j["job_id"] == job.id)
        assert len(target["metrics"]) == 2
        assert {m["model_name"] for m in target["metrics"]} == {"Prophet", "Ridge"}


class TestModelRunDefaults:

    async def test_new_rows_default_to_non_champion_completed(
        self, db_session, test_user
    ):
        """Defaults matter: the migration relies on them for existing rows."""
        job = await _make_job(db_session, test_user.id)
        run = ModelRun(id=str(uuid.uuid4()), job_id=job.id, model_name="Prophet")
        db_session.add(run)
        await db_session.flush()
        await db_session.refresh(run)

        assert run.is_champion is False
        assert run.status == "completed"
        assert run.error_message is None
