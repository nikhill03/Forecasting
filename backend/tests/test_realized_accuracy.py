"""
backend/tests/test_realized_accuracy.py
========================================
F17 — realized accuracy: the pure maths (services/realized_accuracy.py), sheet
pairing, and the routes under /forecast/{id}/realized. A second, spec-driven
suite lives in test_p2_5_forecast_accuracy_tracking.py.
"""
from __future__ import annotations

import io
import json
import uuid
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest
from sqlalchemy import func, select

from backend.core.config import settings
from backend.models.db_models import ForecastEdit, ForecastEvaluation, ForecastJob, Upload
from backend.services.realized_accuracy import pair_sheets
from services.realized_accuracy import (
    actual_series,
    compare,
    forecast_series,
    status_for,
)


def _series(values: list[float | None], start: str = "2025-01-01") -> pd.Series:
    idx = pd.date_range(start, periods=len(values), freq="D")
    return pd.Series(values, index=idx, dtype=float)


# ── compare ───────────────────────────────────────────────────────────
class TestCompare:
    def test_known_values(self):
        out = compare(_series([100, 200]), _series([110, 180]))
        assert out["matched_points"] == 2
        assert out["wmape"]          == pytest.approx(30 / 300)
        assert out["mae"]            == pytest.approx(15.0)
        assert out["bias"]           == pytest.approx((290 - 300) / 300)
        assert out["actual_total"]   == 300
        assert out["forecast_total"] == 290

    def test_over_forecast_bias_is_positive(self):
        assert compare(_series([100]), _series([150]))["bias"] > 0

    def test_zero_actuals_give_null_wmape_and_bias(self):
        out = compare(_series([0, 0]), _series([5, 5]))
        assert out["wmape"] is None
        assert out["bias"]  is None
        assert out["mae"]   == pytest.approx(5.0)

    def test_only_overlapping_dates_are_compared(self):
        out = compare(_series([10, 20, 30], "2025-01-02"), _series([1, 2, 3], "2025-01-01"))
        assert [p["date"] for p in out["points"]] == ["2025-01-02", "2025-01-03"]

    def test_null_actuals_are_dropped(self):
        out = compare(_series([100, None, 100]), _series([100, 100, 100]))
        assert out["matched_points"] == 2

    def test_no_overlap(self):
        out = compare(_series([1], "2025-02-01"), _series([1], "2025-01-01"))
        assert out["matched_points"] == 0
        assert out["wmape"] is None
        assert out["points"] == []

    def test_negative_actuals_are_not_clipped(self):
        out = compare(_series([-10]), _series([0]))
        assert out["actual_total"] == -10
        assert out["wmape"]        == pytest.approx(1.0)


# ── status_for ────────────────────────────────────────────────────────
class TestStatusFor:
    @pytest.mark.parametrize(
        "forecast_points, matched, expected",
        [(10, 0, "no_overlap"), (10, 4, "partial"), (10, 10, "complete")],
    )
    def test_status(self, forecast_points: int, matched: int, expected: str):
        assert status_for(forecast_points, matched) == expected


# ── forecast_series ───────────────────────────────────────────────────
class TestForecastSeries:
    def test_skips_null_forecasts_and_normalises_dates(self):
        records = [
            {"Date": "2025-01-01T00:00:00", "Forecast": 5.0},
            {"Date": "2025-01-02", "Forecast": None},
            {"Date": "2025-01-03", "Forecast": 7},
        ]
        out = forecast_series(records)
        assert list(out.index) == [pd.Timestamp("2025-01-01"), pd.Timestamp("2025-01-03")]
        assert list(out.values) == [5.0, 7.0]

    def test_empty(self):
        assert forecast_series([]).empty


# ── actual_series ─────────────────────────────────────────────────────
class TestActualSeries:
    def test_duplicate_dates_keep_last(self):
        df = pd.DataFrame({
            "date" : ["2025-01-01", "2025-01-01", "2025-01-02"],
            "sales": [1, 9, 3],
        })
        out = actual_series(df, "sales")
        assert out.loc["2025-01-01"] == 9
        assert len(out) == 2

    def test_non_numeric_becomes_nan_and_unparseable_dates_drop(self):
        df = pd.DataFrame({
            "date" : [f"2025-01-{d:02d}" for d in range(1, 10)] + ["not a date"],
            "sales": ["x"] + list(range(2, 11)),
        })
        out = actual_series(df, "sales")
        assert len(out) == 9
        assert pd.isna(out.loc["2025-01-01"])

    def test_missing_metric_is_empty(self):
        df = pd.DataFrame({"date": ["2025-01-01"], "sales": [1]})
        assert actual_series(df, "revenue").empty


# ══════════════════════════════════════════════════════════════════
# Routes — GET/POST /forecast/{id}/realized, GET .../realized/candidates
# Jobs and uploads are seeded directly; no POST /forecast, so
# mock_celery_delay isn't needed.
# ══════════════════════════════════════════════════════════════════
HORIZON_START = "2025-02-01"
HORIZON       = 10   # forecast dates 2025-02-01 .. 2025-02-10, every forecast value 100


def _results(*metrics: str) -> dict:
    dates = pd.date_range(HORIZON_START, periods=HORIZON, freq="D")
    records = [{"Date": d.strftime("%Y-%m-%d"), "Forecast": 100.0} for d in dates]
    return {"Sheet1": {"metrics": {m: {"records": records} for m in (metrics or ("sales",))}}}


async def _seed_job(
    db, user, tmp_path, *, status: str = "success", upload_id: str | None = None,
    metrics: tuple[str, ...] = (),
):
    path = tmp_path / f"{uuid.uuid4()}.json"
    path.write_text(json.dumps(_results(*metrics)))
    job = ForecastJob(
        id=str(uuid.uuid4()), user_id=user.id, status=status, progress_pct=100,
        s3_output_key=f"local:{path}", s3_input_key="uploads/own-input.csv",
        config={"upload_id": upload_id} if upload_id else {},
        created_at=datetime.now(timezone.utc) - timedelta(days=10),
    )
    db.add(job)
    await db.flush()
    return job


async def _seed_upload(db, user, s3, rows: dict[str, float], *, column: str = "sales", name: str = "actuals.csv"):
    csv = f"date,{column}\n" + "\n".join(f"{d},{v}" for d, v in rows.items()) + "\n"
    key = f"uploads/{uuid.uuid4()}/{name}"
    s3.put_object(Bucket=settings.S3_BUCKET_NAME, Key=key, Body=csv.encode())
    upload = Upload(
        id=str(uuid.uuid4()), user_id=user.id, file_name=name, s3_key=key,
        sheets=["Sheet1"], columns={"Sheet1": ["date", column]},
        row_counts={"Sheet1": len(rows)}, file_size_bytes=len(csv),
    )
    db.add(upload)
    await db.flush()
    return upload


def _days(n: int, value: float = 110.0, start: str = HORIZON_START) -> dict[str, float]:
    return {d.strftime("%Y-%m-%d"): value for d in pd.date_range(start, periods=n, freq="D")}


class TestRealizedRoutes:
    async def test_unchecked_job_awaits_actuals_with_its_forecast_period(
        self, async_client, db_session, test_user, make_auth_headers, tmp_path
    ):
        job = await _seed_job(db_session, test_user, tmp_path)
        res = await async_client.get(f"/api/v1/forecast/{job.id}/realized", headers=make_auth_headers(test_user))
        assert res.status_code == 200
        (metric,) = res.json()["metrics"]
        assert metric["status"]          == "awaiting_actuals"
        assert metric["forecast_start"]  == HORIZON_START
        assert metric["forecast_end"]    == "2025-02-10"
        assert metric["forecast_points"] == HORIZON
        assert metric["model"] is None

    async def test_complete_evaluation(
        self, async_client, db_session, test_user, make_auth_headers, tmp_path, s3_client
    ):
        job    = await _seed_job(db_session, test_user, tmp_path)
        upload = await _seed_upload(db_session, test_user, s3_client, _days(HORIZON))
        res = await async_client.post(
            f"/api/v1/forecast/{job.id}/realized", json={"upload_id": upload.id},
            headers=make_auth_headers(test_user),
        )
        assert res.status_code == 200, res.text
        (metric,) = res.json()["metrics"]
        assert metric["status"]           == "complete"
        assert metric["model"]["wmape"]   == pytest.approx(10 / 110)
        assert metric["model"]["bias"]    == pytest.approx(-10 / 110)
        assert metric["upload_file_name"] == "actuals.csv"
        assert len(metric["points"])      == HORIZON
        assert metric["adjusted"] is None   # no edits → never a copy of `model`

    async def test_partial_evaluation(
        self, async_client, db_session, test_user, make_auth_headers, tmp_path, s3_client
    ):
        job    = await _seed_job(db_session, test_user, tmp_path)
        upload = await _seed_upload(db_session, test_user, s3_client, _days(4))
        res = await async_client.post(
            f"/api/v1/forecast/{job.id}/realized", json={"upload_id": upload.id},
            headers=make_auth_headers(test_user),
        )
        (metric,) = res.json()["metrics"]
        assert metric["status"] == "partial"
        assert metric["model"]["matched_points"] == 4

    async def test_no_overlap_reports_the_uploads_last_date(
        self, async_client, db_session, test_user, make_auth_headers, tmp_path, s3_client
    ):
        job    = await _seed_job(db_session, test_user, tmp_path)
        upload = await _seed_upload(db_session, test_user, s3_client, _days(5, start="2025-01-01"))
        res = await async_client.post(
            f"/api/v1/forecast/{job.id}/realized", json={"upload_id": upload.id},
            headers=make_auth_headers(test_user),
        )
        (metric,) = res.json()["metrics"]
        assert metric["status"]            == "no_overlap"
        assert metric["actuals_last_date"] == "2025-01-05"
        assert metric["model"] is None

    async def test_reevaluating_the_same_upload_replaces_its_row(
        self, async_client, db_session, test_user, make_auth_headers, tmp_path, s3_client
    ):
        job     = await _seed_job(db_session, test_user, tmp_path)
        upload  = await _seed_upload(db_session, test_user, s3_client, _days(HORIZON))
        headers = make_auth_headers(test_user)
        for _ in range(2):
            res = await async_client.post(
                f"/api/v1/forecast/{job.id}/realized", json={"upload_id": upload.id}, headers=headers
            )
            assert res.status_code == 200
        count = (await db_session.execute(
            select(func.count()).select_from(ForecastEvaluation).where(ForecastEvaluation.job_id == job.id)
        )).scalar_one()
        assert count == 1

    async def test_newer_upload_becomes_the_shown_evaluation(
        self, async_client, db_session, test_user, make_auth_headers, tmp_path, s3_client
    ):
        job     = await _seed_job(db_session, test_user, tmp_path)
        first   = await _seed_upload(db_session, test_user, s3_client, _days(HORIZON, 110.0), name="first.csv")
        second  = await _seed_upload(db_session, test_user, s3_client, _days(HORIZON, 100.0), name="second.csv")
        headers = make_auth_headers(test_user)
        for upload in (first, second):
            await async_client.post(
                f"/api/v1/forecast/{job.id}/realized", json={"upload_id": upload.id}, headers=headers
            )
        res = await async_client.get(f"/api/v1/forecast/{job.id}/realized", headers=headers)
        (metric,) = res.json()["metrics"]
        assert metric["upload_file_name"] == "second.csv"
        assert metric["model"]["wmape"]   == pytest.approx(0.0)

    async def test_adjusted_forecast_is_recomputed_from_the_live_edit_stack(
        self, async_client, db_session, test_user, make_auth_headers, tmp_path, s3_client
    ):
        job     = await _seed_job(db_session, test_user, tmp_path)
        upload  = await _seed_upload(db_session, test_user, s3_client, _days(HORIZON, 200.0))
        headers = make_auth_headers(test_user)
        await async_client.post(
            f"/api/v1/forecast/{job.id}/realized", json={"upload_id": upload.id}, headers=headers
        )

        # The user edits AFTER evaluating — nothing is stored, so it still shows up.
        db_session.add(ForecastEdit(
            job_id=job.id, user_id=test_user.id, sheet_name="Sheet1", metric_name="sales",
            sequence_no=1, instruction_text="set to 200",
            operation_type="set_value_range", params={"value": 200.0}, affected_points_before=[],
        ))
        await db_session.flush()

        res = await async_client.get(f"/api/v1/forecast/{job.id}/realized", headers=headers)
        (metric,) = res.json()["metrics"]
        assert metric["model"]["wmape"]    == pytest.approx(0.5)   # baseline 100 vs actual 200
        assert metric["adjusted"]["wmape"] == pytest.approx(0.0)   # edited to 200
        assert metric["points"][0]["adjusted_forecast"] == 200.0

    async def test_pre_f17_job_with_no_evaluations_is_just_awaiting(
        self, async_client, db_session, test_user, make_auth_headers, tmp_path
    ):
        job = await _seed_job(db_session, test_user, tmp_path)   # no config["upload_id"], no history
        res = await async_client.get(f"/api/v1/forecast/{job.id}/realized", headers=make_auth_headers(test_user))
        assert [m["status"] for m in res.json()["metrics"]] == ["awaiting_actuals"]

    # ── errors + ownership ────────────────────────────────────────────
    async def test_post_on_unfinished_job_is_409(
        self, async_client, db_session, test_user, make_auth_headers, tmp_path, s3_client
    ):
        job    = await _seed_job(db_session, test_user, tmp_path, status="running")
        upload = await _seed_upload(db_session, test_user, s3_client, _days(HORIZON))
        res = await async_client.post(
            f"/api/v1/forecast/{job.id}/realized", json={"upload_id": upload.id},
            headers=make_auth_headers(test_user),
        )
        assert res.status_code == 409

    async def test_upload_without_the_metric_column_is_422(
        self, async_client, db_session, test_user, make_auth_headers, tmp_path, s3_client
    ):
        job    = await _seed_job(db_session, test_user, tmp_path)
        upload = await _seed_upload(db_session, test_user, s3_client, _days(HORIZON), column="revenue")
        res = await async_client.post(
            f"/api/v1/forecast/{job.id}/realized", json={"upload_id": upload.id},
            headers=make_auth_headers(test_user),
        )
        assert res.status_code == 422

    async def test_other_users_job_and_upload_are_404(
        self, async_client, db_session, test_user, second_user, make_auth_headers, tmp_path, s3_client
    ):
        job        = await _seed_job(db_session, test_user, tmp_path)
        own_upload = await _seed_upload(db_session, test_user, s3_client, _days(HORIZON))
        theirs     = await _seed_upload(db_session, second_user, s3_client, _days(HORIZON))
        mine, other = make_auth_headers(test_user), make_auth_headers(second_user)

        assert (await async_client.get(f"/api/v1/forecast/{job.id}/realized", headers=other)).status_code == 404
        assert (await async_client.get(f"/api/v1/forecast/{job.id}/realized/candidates", headers=other)).status_code == 404
        assert (await async_client.post(
            f"/api/v1/forecast/{job.id}/realized", json={"upload_id": own_upload.id}, headers=other
        )).status_code == 404
        assert (await async_client.post(
            f"/api/v1/forecast/{job.id}/realized", json={"upload_id": theirs.id}, headers=mine
        )).status_code == 404

    async def test_malformed_ids_are_404_and_auth_is_required(
        self, async_client, test_user, make_auth_headers
    ):
        headers = make_auth_headers(test_user)
        assert (await async_client.get("/api/v1/forecast/not-a-uuid/realized", headers=headers)).status_code == 404
        assert (await async_client.post(
            f"/api/v1/forecast/{uuid.uuid4()}/realized", json={"upload_id": "nope"}, headers=headers
        )).status_code == 404
        assert (await async_client.get(f"/api/v1/forecast/{uuid.uuid4()}/realized")).status_code == 401


class TestRealizedCandidates:
    async def test_only_later_uploads_with_a_metric_column_that_arent_the_input(
        self, async_client, db_session, test_user, make_auth_headers, tmp_path, s3_client
    ):
        own_input = await _seed_upload(db_session, test_user, s3_client, _days(3), name="input.csv")
        job       = await _seed_job(db_session, test_user, tmp_path, upload_id=own_input.id)
        job.s3_input_key = own_input.s3_key
        match     = await _seed_upload(db_session, test_user, s3_client, _days(HORIZON), name="later.csv")
        await _seed_upload(db_session, test_user, s3_client, _days(HORIZON), column="revenue", name="other-metric.csv")
        old = await _seed_upload(db_session, test_user, s3_client, _days(HORIZON), name="before.csv")
        old.created_at = job.created_at - timedelta(days=1)
        await db_session.flush()

        res = await async_client.get(
            f"/api/v1/forecast/{job.id}/realized/candidates", headers=make_auth_headers(test_user)
        )
        assert res.status_code == 200
        assert [c["upload_id"] for c in res.json()["candidates"]] == [match.id]

    async def test_candidates_are_capped_at_twenty(
        self, async_client, db_session, test_user, make_auth_headers, tmp_path, s3_client
    ):
        job = await _seed_job(db_session, test_user, tmp_path)
        for i in range(23):
            await _seed_upload(db_session, test_user, s3_client, _days(2), name=f"f{i}.csv")
        res = await async_client.get(
            f"/api/v1/forecast/{job.id}/realized/candidates", headers=make_auth_headers(test_user)
        )
        assert len(res.json()["candidates"]) == 20


class TestPairSheets:
    def test_same_names_pair(self):
        assert pair_sheets(["A", "B"], ["B", "A", "C"]) == {"A": "A", "B": "B"}

    def test_a_lone_sheet_on_each_side_pairs_whatever_they_are_called(self):
        assert pair_sheets(["Sheet1"], ["Export"]) == {"Sheet1": "Export"}

    def test_several_sheets_are_never_guessed(self):
        assert pair_sheets(["A", "B"], ["X"]) == {}
        assert pair_sheets(["A", "B"], ["X", "Y"]) == {}

    def test_a_lone_job_sheet_does_not_pair_with_several_upload_sheets(self):
        assert pair_sheets(["Sheet1"], ["X", "Y"]) == {}


class TestRealizedEdgeCases:
    async def test_storage_failure_is_503(
        self, async_client, db_session, test_user, make_auth_headers, tmp_path, s3_client, monkeypatch
    ):
        job    = await _seed_job(db_session, test_user, tmp_path)
        upload = await _seed_upload(db_session, test_user, s3_client, _days(HORIZON))

        async def _gone(_key: str) -> bytes:
            raise FileNotFoundError("gone")

        monkeypatch.setattr("backend.services.realized_accuracy.load_upload_bytes", _gone)
        res = await async_client.post(
            f"/api/v1/forecast/{job.id}/realized", json={"upload_id": upload.id},
            headers=make_auth_headers(test_user),
        )
        assert res.status_code == 503

    async def test_a_newer_no_overlap_check_shadows_an_older_scored_one(
        self, async_client, db_session, test_user, make_auth_headers, tmp_path, s3_client
    ):
        job     = await _seed_job(db_session, test_user, tmp_path)
        scored  = await _seed_upload(db_session, test_user, s3_client, _days(HORIZON), name="scored.csv")
        early   = await _seed_upload(db_session, test_user, s3_client, _days(5, start="2025-01-01"), name="early.csv")
        headers = make_auth_headers(test_user)
        for upload in (scored, early):
            await async_client.post(
                f"/api/v1/forecast/{job.id}/realized", json={"upload_id": upload.id}, headers=headers
            )
        res = await async_client.get(f"/api/v1/forecast/{job.id}/realized", headers=headers)
        (metric,) = res.json()["metrics"]
        assert metric["status"]           == "no_overlap"
        assert metric["upload_file_name"] == "early.csv"
        assert metric["model"] is None

    async def test_rechecking_an_older_upload_makes_it_the_newest(
        self, async_client, db_session, test_user, make_auth_headers, tmp_path, s3_client
    ):
        job     = await _seed_job(db_session, test_user, tmp_path)
        first   = await _seed_upload(db_session, test_user, s3_client, _days(HORIZON, 110.0), name="first.csv")
        second  = await _seed_upload(db_session, test_user, s3_client, _days(HORIZON, 100.0), name="second.csv")
        headers = make_auth_headers(test_user)
        for upload in (first, second, first):
            await async_client.post(
                f"/api/v1/forecast/{job.id}/realized", json={"upload_id": upload.id}, headers=headers
            )
        res = await async_client.get(f"/api/v1/forecast/{job.id}/realized", headers=headers)
        (metric,) = res.json()["metrics"]
        assert metric["upload_file_name"] == "first.csv"

    async def test_a_file_with_only_one_of_two_metrics_measures_just_that_one(
        self, async_client, db_session, test_user, make_auth_headers, tmp_path, s3_client
    ):
        job    = await _seed_job(db_session, test_user, tmp_path, metrics=("sales", "returns"))
        upload = await _seed_upload(db_session, test_user, s3_client, _days(HORIZON))   # only "sales"
        res = await async_client.post(
            f"/api/v1/forecast/{job.id}/realized", json={"upload_id": upload.id},
            headers=make_auth_headers(test_user),
        )
        assert res.status_code == 200
        by_metric = {m["metric_name"]: m["status"] for m in res.json()["metrics"]}
        assert by_metric == {"sales": "complete", "returns": "awaiting_actuals"}

    async def test_metric_in_an_unpairable_sheet_is_awaiting_not_an_error(
        self, async_client, db_session, test_user, make_auth_headers, tmp_path, s3_client
    ):
        job = await _seed_job(db_session, test_user, tmp_path)
        # Two sheets in the upload, neither named like the job's lone sheet: nothing pairs,
        # yet the metric column is present, so this is not a "wrong file" 422.
        buf = io.BytesIO()
        frame = pd.DataFrame({"date": list(_days(HORIZON)), "sales": 110.0})
        with pd.ExcelWriter(buf) as writer:
            frame.to_excel(writer, sheet_name="X", index=False)
            frame.to_excel(writer, sheet_name="Y", index=False)
        key = f"uploads/{uuid.uuid4()}/two-sheets.xlsx"
        s3_client.put_object(Bucket=settings.S3_BUCKET_NAME, Key=key, Body=buf.getvalue())
        upload = Upload(
            id=str(uuid.uuid4()), user_id=test_user.id, file_name="two-sheets.xlsx", s3_key=key,
            sheets=["X", "Y"], columns={"X": ["date", "sales"], "Y": ["date", "sales"]},
            row_counts={"X": HORIZON, "Y": HORIZON}, file_size_bytes=len(buf.getvalue()),
        )
        db_session.add(upload)
        await db_session.flush()

        res = await async_client.post(
            f"/api/v1/forecast/{job.id}/realized", json={"upload_id": upload.id},
            headers=make_auth_headers(test_user),
        )
        assert res.status_code == 200, res.text
        assert [m["status"] for m in res.json()["metrics"]] == ["awaiting_actuals"]

    async def test_an_older_matching_upload_is_not_hidden_by_many_newer_ones(
        self, async_client, db_session, test_user, make_auth_headers, tmp_path
    ):
        job = await _seed_job(db_session, test_user, tmp_path)
        older = Upload(
            id=str(uuid.uuid4()), user_id=test_user.id, file_name="matching.csv", s3_key="k/match",
            sheets=["Sheet1"], columns={"Sheet1": ["date", "sales"]}, row_counts={"Sheet1": 1},
            file_size_bytes=1, created_at=job.created_at + timedelta(days=1),
        )
        db_session.add(older)
        for i in range(105):
            db_session.add(Upload(
                id=str(uuid.uuid4()), user_id=test_user.id, file_name=f"other{i}.csv", s3_key=f"k/o{i}",
                sheets=["Sheet1"], columns={"Sheet1": ["date", "revenue"]}, row_counts={"Sheet1": 1},
                file_size_bytes=1, created_at=job.created_at + timedelta(days=2, minutes=i),
            ))
        await db_session.flush()

        res = await async_client.get(
            f"/api/v1/forecast/{job.id}/realized/candidates", headers=make_auth_headers(test_user)
        )
        assert [c["upload_id"] for c in res.json()["candidates"]] == [older.id]

    async def test_a_metric_name_is_matched_literally_not_as_a_jsonpath(
        self, async_client, db_session, test_user, make_auth_headers, tmp_path
    ):
        job = await _seed_job(db_session, test_user, tmp_path, metrics=('sales" || true || "x',))
        db_session.add(Upload(
            id=str(uuid.uuid4()), user_id=test_user.id, file_name="a.csv", s3_key="k/a",
            sheets=["Sheet1"], columns={"Sheet1": ["date", "revenue"]}, row_counts={"Sheet1": 1},
            file_size_bytes=1, created_at=job.created_at + timedelta(days=1),
        ))
        await db_session.flush()

        res = await async_client.get(
            f"/api/v1/forecast/{job.id}/realized/candidates", headers=make_auth_headers(test_user)
        )
        assert res.status_code == 200
        assert res.json()["candidates"] == []
