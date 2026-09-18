"""
backend/tests/test_data_quality.py
===================================
Tests for the data-quality report (F16): the pure profiler in
services/data_quality.py, its parity with DataHandling.sanitize, the
POST /upload/{id}/quality-report route, and the blocking/persistence
behaviour added to POST /forecast.

Filename note: no "." in the module name — `test_p2.5-*.py` would break
pytest's dotted import under backend/tests/__init__.py.
"""

from __future__ import annotations

import io
import uuid

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import func, select

from backend.models.db_models import ForecastJob
from backend.services.sample_datasets import SAMPLE_CATALOG, load_sample_bytes
from services.data_handling import DataHandling
from services.data_quality import build_report, profile_series
from utils.forecasting import MIN_SERIES_POINTS

HORIZON     = 14
TEST_WINDOW = 30


# ── Fixture builders ──────────────────────────────────────────────────
def _daily(n: int, values=None, start: str = "2024-01-01", freq: str = "D") -> pd.DataFrame:
    dates = pd.date_range(start, periods=n, freq=freq)
    if values is None:
        values = 100 + np.sin(np.arange(n) / 3.0) * 10
    return pd.DataFrame({"date": dates.astype(str), "sales": list(values)})


def _codes(profile: dict) -> set[str]:
    return {i["code"] for i in profile["issues"]}


def _profile(df: pd.DataFrame, horizon: int = HORIZON, test_window: int = TEST_WINDOW) -> dict:
    return profile_series(df, "Sheet1", "sales", horizon, test_window)


def _csv(df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════════════
# Profiler — pure functions
# ══════════════════════════════════════════════════════════════════════

class TestBlocking:

    def test_29_points_is_blocking(self):
        profile = _profile(_daily(MIN_SERIES_POINTS - 1))
        assert "insufficient_history" in _codes(profile)
        assert all(i["severity"] == "blocking" for i in profile["issues"]
                   if i["code"] == "insufficient_history")

    def test_30_points_is_not_blocking(self):
        profile = _profile(_daily(MIN_SERIES_POINTS))
        assert "insufficient_history" not in _codes(profile)

    def test_null_values_do_not_count_as_usable(self):
        values = [1.0] * 40
        for i in range(0, 40, 3):
            values[i] = None   # 14 nulls → 26 usable
        profile = _profile(_daily(40, values))
        assert profile["usable_points"] == 26
        assert "insufficient_history" in _codes(profile)

    def test_blocking_skips_series_level_checks(self):
        profile = _profile(_daily(10), horizon=365)
        assert _codes(profile) == {"insufficient_history"}

    def test_blocked_series_still_reports_its_date_range(self):
        profile = _profile(_daily(20))
        assert profile["start"] is not None and profile["span_days"] == 19
        # Never reached for a blocked series — left unset, not guessed.
        assert profile["test_split_size"] == 0

    def test_report_has_blocking_flag(self):
        report = build_report({"Sheet1": _daily(10)}, ["Sheet1"], ["sales"], HORIZON, TEST_WINDOW)
        assert report["has_blocking"] is True

    def test_no_existing_pair_is_blocking(self):
        report = build_report({"Sheet1": _daily(100)}, ["Sheet1"], ["missing"], HORIZON, TEST_WINDOW)
        assert report["has_blocking"] is True
        assert report["series"] == []

    def test_only_insufficient_history_ever_blocks(self):
        messy = _daily(120, [(-5 if i % 10 == 0 else 0 if i > 100 else 50) for i in range(120)])
        messy = pd.concat([messy, messy.iloc[:5]], ignore_index=True)   # duplicates
        messy.loc[3, "date"] = "not a date"
        messy.loc[4, "sales"] = "n/a"
        report = build_report({"Sheet1": messy}, ["Sheet1"], ["sales", "x"], 365, 180)
        assert report["has_blocking"] is False
        assert all(i["severity"] == "warning" for p in report["series"] for i in p["issues"])


class TestRowLevelWarnings:

    def test_unparseable_dates(self):
        df = _daily(60)
        df.loc[[5, 6], "date"] = "garbage"
        profile = _profile(df)
        assert profile["unparseable_dates"] == 2
        assert "unparseable_dates" in _codes(profile)

    def test_non_numeric_values(self):
        df = _daily(60)
        df["sales"] = df["sales"].astype(object)
        df.loc[[1, 2, 3], "sales"] = "n/a"
        profile = _profile(df)
        assert profile["non_numeric_values"] == 3
        assert "non_numeric_values" in _codes(profile)

    def test_missing_values_are_not_non_numeric(self):
        df = _daily(60)
        df.loc[[1, 2], "sales"] = None
        assert "non_numeric_values" not in _codes(_profile(df))

    def test_duplicate_timestamps_message_says_not_summed(self):
        df = pd.concat([_daily(60), _daily(60).iloc[:4]], ignore_index=True)
        profile = _profile(df)
        assert profile["duplicate_timestamps"] == 4
        issue = next(i for i in profile["issues"] if i["code"] == "duplicate_timestamps")
        assert "not summed" in issue["message"]

    def test_clean_series_has_no_issues(self):
        assert _profile(_daily(200))["issues"] == []


class TestFrequencyAndGaps:

    def test_weekly_series_is_non_daily(self):
        profile = _profile(_daily(60, freq="W"))
        assert "non_daily_frequency" in _codes(profile)
        assert profile["imputed_pct"] == pytest.approx(6 / 7, abs=0.01)

    def test_non_daily_suppresses_date_gaps(self):
        assert "date_gaps" not in _codes(_profile(_daily(60, freq="W")))

    def test_sub_daily_series_is_non_daily(self):
        profile = _profile(_daily(24 * 40, freq="h"))
        issue = next(i for i in profile["issues"] if i["code"] == "non_daily_frequency")
        assert "one reading per day" in issue["message"]

    def test_daily_gaps_over_threshold_warn(self):
        df = _daily(200).drop(index=range(50, 80))   # 30 of 200 days missing = 15%
        profile = _profile(df)
        assert "date_gaps" in _codes(profile)
        assert profile["imputed_pct"] == pytest.approx(0.15, abs=0.001)

    def test_daily_gaps_under_threshold_do_not_warn(self):
        df = _daily(200).drop(index=range(50, 60))   # 5%
        assert "date_gaps" not in _codes(_profile(df))


class TestValueWarnings:

    def test_negative_values(self):
        values = [50.0] * 60
        values[10] = -3
        profile = _profile(_daily(60, values))
        assert profile["negative_values"] == 1
        assert "negative_values" in _codes(profile)

    def test_outliers_clipped_when_skewed(self):
        rng = np.random.default_rng(0)
        values = list(rng.normal(100, 5, 200))
        values[50] = 10_000   # one extreme spike → |skew| >> 2
        issue = next(i for i in _profile(_daily(200, values))["issues"] if i["code"] == "outliers")
        assert "will be clipped" in issue["message"]

    def test_outliers_left_when_not_skewed(self):
        # Symmetric heavy tails: outliers on both sides keep skew near 0,
        # so the pipeline does not clip.
        rng = np.random.default_rng(1)
        values = list(rng.normal(100, 1, 200))
        for i in range(0, 20):
            values[i * 10] = 200 if i % 2 == 0 else 0
        profile = _profile(_daily(200, values))
        issue = next(i for i in profile["issues"] if i["code"] == "outliers")
        assert "left as-is" in issue["message"]

    def test_constant_series_has_no_outliers(self):
        assert _profile(_daily(60, [5.0] * 60))["outliers"] == 0


class TestRunConfigurationWarnings:

    def test_horizon_capped(self):
        profile = _profile(_daily(100), horizon=60)   # cap = max(14, 30) = 30
        assert profile["effective_horizon"] == 30
        assert "horizon_capped" in _codes(profile)

    def test_horizon_within_cap(self):
        assert "horizon_capped" not in _codes(_profile(_daily(100), horizon=30))

    def test_sparse_test_window(self):
        values = [10.0] * 170 + [0.0] * 30
        profile = _profile(_daily(200, values))
        assert profile["test_split_size"] == 30
        assert "sparse_test_window" in _codes(profile)

    def test_dense_test_window(self):
        assert "sparse_test_window" not in _codes(_profile(_daily(200)))

    def test_short_history(self):
        assert "short_history" in _codes(_profile(_daily(60)))

    def test_long_history(self):
        assert "short_history" not in _codes(_profile(_daily(120)))


class TestReportShape:

    def test_missing_metric_is_report_level_warning(self):
        report = build_report({"Sheet1": _daily(100)}, ["Sheet1"], ["sales", "units"], HORIZON, TEST_WINDOW)
        assert [i["code"] for i in report["issues"]] == ["metric_missing_in_sheet"]
        assert len(report["series"]) == 1
        assert report["has_blocking"] is False

    def test_missing_sheet_is_report_level_warning(self):
        report = build_report({"Sheet1": _daily(100)}, ["Sheet1", "Nope"], ["sales"], HORIZON, TEST_WINDOW)
        assert any("Nope" in i["message"] for i in report["issues"])


class TestSanitizeParity:
    """usable_points must equal what DataHandling.sanitize keeps, after the
    same per-sheet prep processing_worker does. If sanitize changes, this
    must fail."""

    @staticmethod
    def _pipeline_count(df_raw: pd.DataFrame) -> int:
        df = df_raw.copy()
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"]).set_index("date").sort_index()
        series, _ = DataHandling(min_points=0).sanitize(df.reset_index(), date_col="date", metric_col="sales")
        return int(series.notna().sum())

    @pytest.mark.parametrize("builder", [
        lambda: _daily(60),
        lambda: _daily(29),
        lambda: pd.concat([_daily(60), _daily(60).iloc[:7]], ignore_index=True),
        lambda: _daily(60).assign(sales=lambda d: d["sales"].astype(object).where(d.index % 4 != 0, "x")),
        lambda: _daily(60).assign(date=lambda d: d["date"].where(d.index % 9 != 0, "bad")),
        lambda: _daily(60, freq="W"),
    ])
    def test_usable_points_match_sanitize(self, builder):
        df = builder()
        assert _profile(df)["usable_points"] == self._pipeline_count(df)


class TestSampleDatasets:

    @pytest.mark.parametrize("sample_id", list(SAMPLE_CATALOG))
    def test_samples_are_never_blocked(self, sample_id):
        df = pd.read_csv(io.BytesIO(load_sample_bytes(sample_id)))
        metric = df.columns[1]
        report = build_report({"Sheet1": df}, ["Sheet1"], [metric], 60, 30)
        assert report["has_blocking"] is False


# ══════════════════════════════════════════════════════════════════════
# API — POST /upload/{id}/quality-report and POST /forecast
# ══════════════════════════════════════════════════════════════════════

def _warnings_only_csv() -> bytes:
    """60 daily rows with duplicates and a negative: warnings, no blocking."""
    df = _daily(60, [(-2.0 if i == 5 else 40.0 + i) for i in range(60)])
    df = pd.concat([df, df.iloc[:3]], ignore_index=True)
    return _csv(df)


async def _upload(async_client, headers, content: bytes) -> str:
    res = await async_client.post(
        "/api/v1/upload",
        files={"file": ("data.csv", content, "text/csv")},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()["upload_id"]


def _selection(**overrides) -> dict:
    body = {"selected_sheets": ["Sheet1"], "selected_metrics": ["sales"],
            "forecast_horizon": 14, "test_window": 30}
    body.update(overrides)
    return body


async def _job_count(db_session) -> int:
    return (await db_session.execute(select(func.count()).select_from(ForecastJob))).scalar_one()


class TestQualityReportRoute:

    async def test_returns_report(self, async_client, test_user, make_auth_headers, s3_client):
        headers   = make_auth_headers(test_user)
        upload_id = await _upload(async_client, headers, _warnings_only_csv())

        res = await async_client.post(
            f"/api/v1/upload/{upload_id}/quality-report", json=_selection(), headers=headers
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["has_blocking"] is False
        assert set(body) == {"generated_at", "has_blocking", "series", "issues"}
        series = body["series"][0]
        assert series["usable_points"] == 60
        assert {i["code"] for i in series["issues"]} >= {"duplicate_timestamps", "negative_values"}

    async def test_requires_auth(self, async_client):
        res = await async_client.post(
            f"/api/v1/upload/{uuid.uuid4()}/quality-report", json=_selection()
        )
        assert res.status_code == 401

    async def test_foreign_upload_is_404(
        self, async_client, test_user, second_user, make_auth_headers, s3_client
    ):
        upload_id = await _upload(async_client, make_auth_headers(test_user), _csv(_daily(60)))
        res = await async_client.post(
            f"/api/v1/upload/{upload_id}/quality-report",
            json=_selection(),
            headers=make_auth_headers(second_user),
        )
        assert res.status_code == 404

    async def test_malformed_id_is_404(self, async_client, test_user, make_auth_headers):
        res = await async_client.post(
            "/api/v1/upload/not-a-uuid/quality-report",
            json=_selection(),
            headers=make_auth_headers(test_user),
        )
        assert res.status_code == 404

    async def test_persists_nothing(
        self, async_client, db_session, test_user, make_auth_headers, s3_client
    ):
        headers   = make_auth_headers(test_user)
        upload_id = await _upload(async_client, headers, _csv(_daily(20)))
        before    = await _job_count(db_session)
        res = await async_client.post(
            f"/api/v1/upload/{upload_id}/quality-report", json=_selection(), headers=headers
        )
        assert res.status_code == 200
        assert res.json()["has_blocking"] is True
        assert await _job_count(db_session) == before


class TestForecastSubmitQualityGate:

    async def test_blocking_series_returns_422_and_creates_no_job(
        self, async_client, db_session, test_user, make_auth_headers, s3_client, mock_celery_delay
    ):
        headers   = make_auth_headers(test_user)
        upload_id = await _upload(async_client, headers, _csv(_daily(20)))
        before    = await _job_count(db_session)

        res = await async_client.post(
            "/api/v1/forecast", json={"upload_id": upload_id, **_selection()}, headers=headers
        )
        assert res.status_code == 422
        detail = res.json()["detail"]
        assert detail["quality_report"]["has_blocking"] is True
        assert isinstance(detail["message"], str)
        assert await _job_count(db_session) == before
        assert mock_celery_delay == []

    async def test_warnings_do_not_block_and_report_is_persisted(
        self, async_client, db_session, test_user, make_auth_headers, s3_client, mock_celery_delay
    ):
        headers   = make_auth_headers(test_user)
        upload_id = await _upload(async_client, headers, _warnings_only_csv())

        res = await async_client.post(
            "/api/v1/forecast", json={"upload_id": upload_id, **_selection()}, headers=headers
        )
        assert res.status_code == 202, res.text
        assert len(mock_celery_delay) == 1
        assert res.json()["quality_report"]["has_blocking"] is False

        job_id = res.json()["job_id"]
        job    = await db_session.get(ForecastJob, job_id)
        assert job.quality_report["has_blocking"] is False

        got = await async_client.get(f"/api/v1/forecast/{job_id}", headers=headers)
        assert got.status_code == 200
        codes = {i["code"] for i in got.json()["quality_report"]["series"][0]["issues"]}
        assert "duplicate_timestamps" in codes

    async def test_job_without_report_returns_null(
        self, async_client, db_session, test_user, make_auth_headers
    ):
        job = ForecastJob(
            id=str(uuid.uuid4()), user_id=test_user.id, status="success", progress_pct=100,
        )
        db_session.add(job)
        await db_session.flush()

        res = await async_client.get(
            f"/api/v1/forecast/{job.id}", headers=make_auth_headers(test_user)
        )
        assert res.status_code == 200
        assert res.json()["quality_report"] is None
