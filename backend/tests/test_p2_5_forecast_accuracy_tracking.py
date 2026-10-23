"""
backend/tests/test_p2_5_forecast_accuracy_tracking.py
======================================================
Spec-driven tests for F17 "Forecast Accuracy Tracking" (realized accuracy),
written from .claude/specs/p2.5-forecast-accuracy-tracking.md only:

  GET  /api/v1/forecast/{job_id}/realized
  GET  /api/v1/forecast/{job_id}/realized/candidates
  POST /api/v1/forecast/{job_id}/realized        body {"upload_id": ...}
  GET  /api/v1/dashboard                          realized_wmape / realized_runs
  table forecast_evaluations                      DB side effects + cascade

Expected numbers are hand-computed here from the spec's pinned definitions,
never taken from the implementation:
  wmape = sum|a-f| / sum|a|        (null when sum|a| == 0)
  mae   = mean|a-f|
  bias  = (sum f - sum a) / sum|a| (positive = over-forecast; null when sum|a| == 0)

Seeding: ForecastJob rows with a local results.json, Upload rows whose CSV/XLSX
bytes live in the moto bucket. POST /forecast is never called, so
mock_celery_delay is not needed.

Assumptions (verify against the spec if a test fails for a reason that looks
like a spec ambiguity rather than a bug):
  - "forecast_start"/"forecast_end"/"actuals_last_date" are ISO dates that
    start with YYYY-MM-DD.
  - Edits are seeded as `set_value_range` ForecastEdit rows with params
    {date_from, date_to, days_of_week, value}; replay applies them in
    sequence_no order to the "Forecast" field of each record.
  - "Newest" evaluation is decided by forecast_evaluations.created_at. Because
    now() is the transaction start time inside a test, the older row is
    explicitly back-dated before the newer evaluation is made.

Filename note: no "." in the module name — `test_p2.5-*.py` would break
pytest's dotted import under backend/tests/__init__.py.
"""

from __future__ import annotations

import io
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import delete, func, select, update

from backend.core.config import settings
from backend.models.db_models import (
    ForecastEdit,
    ForecastEvaluation,
    ForecastJob,
    ModelRun,
    Upload,
)

BASE_TIME     = datetime(2026, 1, 1, tzinfo=timezone.utc)
METRIC        = "units"
FORECAST_DATES = [d.strftime("%Y-%m-%d") for d in pd.date_range("2025-01-01", periods=10, freq="D")]
FORECAST_VALS = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 160.0, 170.0, 180.0, 190.0]
# Smooth-ish actuals (no outliers, so any sanitising leaves them untouched).
ACTUAL_VALS   = [90.0, 115.0, 125.0, 120.0, 150.0, 140.0, 170.0, 180.0, 170.0, 200.0]
TOL           = 1e-9


# ── Hand-computed reference metrics ───────────────────────────────────
def expected_scores(actual: list[float], forecast: list[float]) -> dict:
    abs_err = [abs(a - f) for a, f in zip(actual, forecast)]
    denom   = sum(abs(a) for a in actual)
    return {
        "wmape": (sum(abs_err) / denom) if denom else None,
        "mae"  : sum(abs_err) / len(actual),
        "bias" : ((sum(forecast) - sum(actual)) / denom) if denom else None,
        "actual_total"  : sum(actual),
        "forecast_total": sum(forecast),
    }


# ── Seeding helpers ───────────────────────────────────────────────────
def _at(days: float) -> datetime:
    return BASE_TIME + timedelta(days=days)


def _csv_bytes(dates: list[str], values: list, column: str = METRIC) -> bytes:
    df  = pd.DataFrame({"date": dates, column: values})
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


def _history_plus(dates: list[str], values: list, history: int = 20) -> tuple[list[str], list]:
    """Prepend `history` days before 2025-01-01 (the forecast must ignore them)."""
    hist_dates = [d.strftime("%Y-%m-%d") for d in pd.date_range(end="2024-12-31", periods=history, freq="D")]
    return hist_dates + dates, [100.0 + (i % 5) for i in range(history)] + list(values)


def _xlsx_bytes(sheets: dict[str, tuple[list[str], list]], column: str = METRIC) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for name, (dates, values) in sheets.items():
            pd.DataFrame({"date": pd.to_datetime(dates), column: values}).to_excel(
                writer, sheet_name=name, index=False
            )
    return buf.getvalue()


async def make_upload(
    db, s3_client, user, *, content: bytes, file_name: str = "actuals.csv",
    days: float = 10, sheet_columns: dict[str, list[str]] | None = None,
) -> Upload:
    """Persist bytes in the moto bucket and an Upload row created `days` after BASE_TIME."""
    upload_id = str(uuid.uuid4())
    key       = f"uploads/{upload_id}/{file_name}"
    s3_client.put_object(Bucket=settings.S3_BUCKET_NAME, Key=key, Body=content)
    cols = sheet_columns or {"Sheet1": ["date", METRIC]}
    upload = Upload(
        id=upload_id,
        user_id=user.id,
        file_name=file_name,
        s3_key=key,
        sheets=list(cols.keys()),
        columns=cols,
        row_counts={name: 10 for name in cols},
        file_size_bytes=len(content),
        created_at=_at(days),
    )
    db.add(upload)
    await db.flush()
    return upload


def _records(dates: list[str], values: list) -> list[dict]:
    return [{"Date": d, "Forecast": v} for d, v in zip(dates, values)]


async def make_job(
    db, user, tmp_path: Path, *, results: dict | None = None, input_upload: Upload | None = None,
    status: str = "success", days: float = 0, name: str = "results",
) -> ForecastJob:
    """A finished job whose results.json is a local file (the dev-only `local:` scheme)."""
    if results is None:
        results = {"Sheet1": {"metrics": {METRIC: {"records": _records(FORECAST_DATES, FORECAST_VALS)}}}}
    path = tmp_path / f"{name}-{uuid.uuid4().hex}.json"
    path.write_text(json.dumps(results))
    job = ForecastJob(
        id=str(uuid.uuid4()),
        user_id=user.id,
        status=status,
        progress_pct=100 if status == "success" else 0,
        file_name="history.csv",
        s3_input_key=input_upload.s3_key if input_upload else None,
        s3_output_key=f"local:{path}" if status == "success" else None,
        config={"upload_id": input_upload.id if input_upload else None},
        created_at=_at(days),
    )
    db.add(job)
    await db.flush()
    return job


async def add_set_value_edit(db, job, user, *, value: float, seq: int) -> ForecastEdit:
    """An Action Center edit that sets every forecast value to `value`."""
    edit = ForecastEdit(
        id=str(uuid.uuid4()),
        job_id=job.id,
        user_id=user.id,
        sheet_name="Sheet1",
        metric_name=METRIC,
        sequence_no=seq,
        instruction_text=f"set everything to {value}",
        operation_type="set_value_range",
        params={"date_from": None, "date_to": None, "days_of_week": None, "value": value},
        affected_points_before=[],
    )
    db.add(edit)
    await db.flush()
    return edit


def _url(job_id: str, suffix: str = "") -> str:
    return f"/api/v1/forecast/{job_id}/realized{suffix}"


def _metric(body: dict, sheet: str = "Sheet1", metric: str = METRIC) -> dict:
    matches = [m for m in body["metrics"] if m["sheet_name"] == sheet and m["metric_name"] == metric]
    assert len(matches) == 1, f"expected exactly one entry for ({sheet}, {metric}): {body['metrics']}"
    return matches[0]


async def evaluate(async_client, headers, job, upload):
    return await async_client.post(_url(job.id), headers=headers, json={"upload_id": upload.id})


@pytest.fixture
def headers(test_user, make_auth_headers) -> dict[str, str]:
    return make_auth_headers(test_user)


@pytest.fixture
def full_actuals_csv() -> bytes:
    """History + all 10 forecast days + 5 days beyond the forecast end."""
    extra_dates = [d.strftime("%Y-%m-%d") for d in pd.date_range("2025-01-11", periods=5, freq="D")]
    dates, values = _history_plus(FORECAST_DATES + extra_dates, ACTUAL_VALS + [150.0] * 5)
    return _csv_bytes(dates, values)


# ══════════════════════════════════════════════════════════════════════
# Authentication
# ══════════════════════════════════════════════════════════════════════

class TestAuthentication:

    @pytest.mark.parametrize(
        "method, suffix, body",
        [
            ("get",  "",            None),
            ("get",  "/candidates", None),
            ("post", "",            {"upload_id": str(uuid.uuid4())}),
        ],
    )
    async def test_missing_token_returns_401(self, async_client, method, suffix, body):
        res = await getattr(async_client, method)(
            _url(str(uuid.uuid4()), suffix), **({"json": body} if body else {})
        )
        assert res.status_code == 401

    @pytest.mark.parametrize("method, suffix", [("get", ""), ("get", "/candidates"), ("post", "")])
    async def test_garbage_token_returns_401(self, async_client, method, suffix):
        kwargs = {"json": {"upload_id": str(uuid.uuid4())}} if method == "post" else {}
        res = await getattr(async_client, method)(
            _url(str(uuid.uuid4()), suffix),
            headers={"Authorization": "Bearer not-a-real-token"},
            **kwargs,
        )
        assert res.status_code == 401


# ══════════════════════════════════════════════════════════════════════
# Authorization / not found
# ══════════════════════════════════════════════════════════════════════

class TestOwnershipAndNotFound:

    async def test_get_other_users_job_is_404(
        self, async_client, db_session, test_user, second_user, make_auth_headers, tmp_path
    ):
        job = await make_job(db_session, test_user, tmp_path)
        res = await async_client.get(_url(job.id), headers=make_auth_headers(second_user))
        assert res.status_code == 404

    async def test_candidates_for_other_users_job_is_404(
        self, async_client, db_session, test_user, second_user, make_auth_headers, tmp_path
    ):
        job = await make_job(db_session, test_user, tmp_path)
        res = await async_client.get(_url(job.id, "/candidates"), headers=make_auth_headers(second_user))
        assert res.status_code == 404

    async def test_post_other_users_job_is_404_and_writes_nothing(
        self, async_client, db_session, s3_client, test_user, second_user, make_auth_headers,
        tmp_path, full_actuals_csv,
    ):
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, second_user, content=full_actuals_csv)
        res = await evaluate(async_client, make_auth_headers(second_user), job, upload)
        assert res.status_code == 404
        count = await db_session.scalar(select(func.count()).select_from(ForecastEvaluation))
        assert count == 0

    async def test_post_other_users_upload_is_404_and_writes_nothing(
        self, async_client, db_session, s3_client, test_user, second_user, headers, tmp_path,
        full_actuals_csv,
    ):
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, second_user, content=full_actuals_csv)
        res = await evaluate(async_client, headers, job, upload)
        assert res.status_code == 404
        count = await db_session.scalar(select(func.count()).select_from(ForecastEvaluation))
        assert count == 0

    @pytest.mark.parametrize("suffix", ["", "/candidates"])
    async def test_get_unknown_job_is_404(self, async_client, headers, suffix):
        res = await async_client.get(_url(str(uuid.uuid4()), suffix), headers=headers)
        assert res.status_code == 404

    async def test_post_unknown_job_is_404(self, async_client, headers):
        res = await async_client.post(
            _url(str(uuid.uuid4())), headers=headers, json={"upload_id": str(uuid.uuid4())}
        )
        assert res.status_code == 404

    @pytest.mark.parametrize("suffix", ["", "/candidates"])
    async def test_get_malformed_job_id_is_404(self, async_client, headers, suffix):
        res = await async_client.get(_url("not-a-uuid", suffix), headers=headers)
        assert res.status_code == 404

    async def test_post_malformed_job_id_is_404(self, async_client, headers):
        res = await async_client.post(
            _url("not-a-uuid"), headers=headers, json={"upload_id": str(uuid.uuid4())}
        )
        assert res.status_code == 404

    async def test_post_unknown_upload_is_404(self, async_client, db_session, headers, test_user, tmp_path):
        job = await make_job(db_session, test_user, tmp_path)
        res = await async_client.post(_url(job.id), headers=headers, json={"upload_id": str(uuid.uuid4())})
        assert res.status_code == 404

    async def test_post_malformed_upload_id_is_404(self, async_client, db_session, headers, test_user, tmp_path):
        job = await make_job(db_session, test_user, tmp_path)
        res = await async_client.post(_url(job.id), headers=headers, json={"upload_id": "not-a-uuid"})
        assert res.status_code == 404


# ══════════════════════════════════════════════════════════════════════
# Validation and error statuses
# ══════════════════════════════════════════════════════════════════════

class TestValidationAndErrors:

    @pytest.mark.parametrize("status", ["pending", "running", "failed"])
    async def test_post_for_job_that_is_not_success_returns_409(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path, full_actuals_csv, status
    ):
        job    = await make_job(db_session, test_user, tmp_path, status=status)
        upload = await make_upload(db_session, s3_client, test_user, content=full_actuals_csv)
        res = await evaluate(async_client, headers, job, upload)
        assert res.status_code == 409

    async def test_409_writes_no_evaluation_row(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path, full_actuals_csv
    ):
        job    = await make_job(db_session, test_user, tmp_path, status="pending")
        upload = await make_upload(db_session, s3_client, test_user, content=full_actuals_csv)
        await evaluate(async_client, headers, job, upload)
        count = await db_session.scalar(select(func.count()).select_from(ForecastEvaluation))
        assert count == 0

    async def test_upload_without_any_job_metric_column_returns_422(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path
    ):
        job    = await make_job(db_session, test_user, tmp_path)
        other  = _csv_bytes(FORECAST_DATES, ACTUAL_VALS, column="revenue")
        upload = await make_upload(
            db_session, s3_client, test_user, content=other,
            sheet_columns={"Sheet1": ["date", "revenue"]},
        )
        res = await evaluate(async_client, headers, job, upload)
        assert res.status_code == 422

    async def test_422_writes_no_evaluation_row(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path
    ):
        job    = await make_job(db_session, test_user, tmp_path)
        other  = _csv_bytes(FORECAST_DATES, ACTUAL_VALS, column="revenue")
        upload = await make_upload(
            db_session, s3_client, test_user, content=other,
            sheet_columns={"Sheet1": ["date", "revenue"]},
        )
        await evaluate(async_client, headers, job, upload)
        count = await db_session.scalar(select(func.count()).select_from(ForecastEvaluation))
        assert count == 0

    async def test_missing_body_returns_422(self, async_client, db_session, headers, test_user, tmp_path):
        job = await make_job(db_session, test_user, tmp_path)
        res = await async_client.post(_url(job.id), headers=headers)
        assert res.status_code == 422

    @pytest.mark.parametrize(
        "body",
        [{}, {"upload_id": None}, {"upload_id": 123}, {"wrong_field": "x"}, {"upload_id": ["a"]}],
    )
    async def test_invalid_body_returns_422(self, async_client, db_session, headers, test_user, tmp_path, body):
        job = await make_job(db_session, test_user, tmp_path)
        res = await async_client.post(_url(job.id), headers=headers, json=body)
        assert res.status_code == 422


# ══════════════════════════════════════════════════════════════════════
# GET — awaiting_actuals (never checked)
# ══════════════════════════════════════════════════════════════════════

class TestAwaitingActuals:

    async def test_unchecked_job_reports_awaiting_actuals_with_forecast_period(
        self, async_client, db_session, headers, test_user, tmp_path
    ):
        job = await make_job(db_session, test_user, tmp_path)
        res = await async_client.get(_url(job.id), headers=headers)
        assert res.status_code == 200
        body = res.json()
        assert body["job_id"] == job.id
        m = _metric(body)
        assert m["status"] == "awaiting_actuals"
        assert m["forecast_start"].startswith("2025-01-01")
        assert m["forecast_end"].startswith("2025-01-10")
        assert m["forecast_points"] == 10

    async def test_unchecked_job_has_no_scores_points_or_source(
        self, async_client, db_session, headers, test_user, tmp_path
    ):
        job = await make_job(db_session, test_user, tmp_path)
        m = _metric((await async_client.get(_url(job.id), headers=headers)).json())
        assert m["model"] is None
        assert m["adjusted"] is None
        assert m["points"] == []
        assert m["upload_id"] is None
        assert m["upload_file_name"] is None
        assert m["evaluated_at"] is None

    async def test_one_entry_per_sheet_and_metric(
        self, async_client, db_session, headers, test_user, tmp_path
    ):
        recs = _records(FORECAST_DATES, FORECAST_VALS)
        results = {
            "Alpha": {"metrics": {"units": {"records": recs}, "revenue": {"records": recs}}},
            "Beta" : {"metrics": {"units": {"records": recs}}},
        }
        job  = await make_job(db_session, test_user, tmp_path, results=results)
        body = (await async_client.get(_url(job.id), headers=headers)).json()
        pairs = sorted((m["sheet_name"], m["metric_name"]) for m in body["metrics"])
        assert pairs == [("Alpha", "revenue"), ("Alpha", "units"), ("Beta", "units")]

    async def test_null_forecast_values_are_not_counted_as_forecast_points(
        self, async_client, db_session, headers, test_user, tmp_path
    ):
        recs = _records(FORECAST_DATES, FORECAST_VALS) + [{"Date": "2025-01-11", "Forecast": None}]
        results = {"Sheet1": {"metrics": {METRIC: {"records": recs}}}}
        job = await make_job(db_session, test_user, tmp_path, results=results)
        m = _metric((await async_client.get(_url(job.id), headers=headers)).json())
        assert m["forecast_points"] == 10

    async def test_monthly_forecast_period_is_reported_as_stored(
        self, async_client, db_session, headers, test_user, tmp_path
    ):
        months = [d.strftime("%Y-%m-%d") for d in pd.date_range("2025-01-01", periods=6, freq="MS")]
        results = {"Sheet1": {"metrics": {METRIC: {"records": _records(months, [1.0] * 6)}}}}
        job = await make_job(db_session, test_user, tmp_path, results=results)
        m = _metric((await async_client.get(_url(job.id), headers=headers)).json())
        assert (m["forecast_points"], m["forecast_start"][:10], m["forecast_end"][:10]) == (
            6, "2025-01-01", "2025-06-01",
        )

    async def test_job_that_is_not_success_has_no_realized_view(
        self, async_client, db_session, headers, test_user, tmp_path
    ):
        job = await make_job(db_session, test_user, tmp_path, status="pending")
        res = await async_client.get(_url(job.id), headers=headers)
        # No results file exists yet: it must not be a server error, and it must not claim a score.
        assert res.status_code != 500
        if res.status_code == 200:
            assert all(m["model"] is None for m in res.json()["metrics"])


# ══════════════════════════════════════════════════════════════════════
# POST — complete / partial / no_overlap and the pinned metric definitions
# ══════════════════════════════════════════════════════════════════════

class TestCompleteEvaluation:

    async def test_full_coverage_is_complete(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path, full_actuals_csv
    ):
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, test_user, content=full_actuals_csv)
        res = await evaluate(async_client, headers, job, upload)
        assert res.status_code in (200, 201)
        m = _metric(res.json())
        assert m["status"] == "complete"
        assert m["model"]["matched_points"] == 10
        assert m["forecast_points"] == 10

    async def test_scores_match_hand_computed_fixture(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path, full_actuals_csv
    ):
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, test_user, content=full_actuals_csv)
        exp = expected_scores(ACTUAL_VALS, FORECAST_VALS)
        model = _metric((await evaluate(async_client, headers, job, upload)).json())["model"]
        assert model["wmape"] == pytest.approx(exp["wmape"], abs=TOL)
        assert model["mae"] == pytest.approx(exp["mae"], abs=TOL)
        assert model["bias"] == pytest.approx(exp["bias"], abs=TOL)
        assert model["actual_total"] == pytest.approx(exp["actual_total"], abs=TOL)
        assert model["forecast_total"] == pytest.approx(exp["forecast_total"], abs=TOL)

    async def test_history_and_dates_beyond_forecast_are_ignored(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path, full_actuals_csv
    ):
        # full_actuals_csv has 20 history rows and 5 post-horizon rows; neither is a forecast date.
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, test_user, content=full_actuals_csv)
        m = _metric((await evaluate(async_client, headers, job, upload)).json())
        assert [p["date"][:10] for p in m["points"]] == FORECAST_DATES

    async def test_points_carry_actual_and_forecast_on_matched_dates(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path, full_actuals_csv
    ):
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, test_user, content=full_actuals_csv)
        points = _metric((await evaluate(async_client, headers, job, upload)).json())["points"]
        assert [p["actual"] for p in points] == pytest.approx(ACTUAL_VALS)
        assert [p["forecast"] for p in points] == pytest.approx(FORECAST_VALS)

    async def test_response_names_the_source_upload(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path, full_actuals_csv
    ):
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, test_user, content=full_actuals_csv,
                                   file_name="january-actuals.csv")
        m = _metric((await evaluate(async_client, headers, job, upload)).json())
        assert (m["upload_id"], m["upload_file_name"]) == (upload.id, "january-actuals.csv")
        assert m["evaluated_at"] is not None

    async def test_subsequent_get_returns_the_stored_evaluation(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path, full_actuals_csv
    ):
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, test_user, content=full_actuals_csv)
        await evaluate(async_client, headers, job, upload)
        m = _metric((await async_client.get(_url(job.id), headers=headers)).json())
        assert m["status"] == "complete"
        assert m["model"]["wmape"] == pytest.approx(expected_scores(ACTUAL_VALS, FORECAST_VALS)["wmape"], abs=TOL)

    async def test_datetime_formatted_forecast_dates_still_match_by_calendar_day(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path, full_actuals_csv
    ):
        recs = _records([f"{d}T00:00:00" for d in FORECAST_DATES], FORECAST_VALS)
        results = {"Sheet1": {"metrics": {METRIC: {"records": recs}}}}
        job    = await make_job(db_session, test_user, tmp_path, results=results)
        upload = await make_upload(db_session, s3_client, test_user, content=full_actuals_csv)
        m = _metric((await evaluate(async_client, headers, job, upload)).json())
        assert (m["status"], m["model"]["matched_points"]) == ("complete", 10)

    async def test_perfect_forecast_has_zero_error(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path
    ):
        dates, vals = _history_plus(FORECAST_DATES, FORECAST_VALS)
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, test_user, content=_csv_bytes(dates, vals))
        model = _metric((await evaluate(async_client, headers, job, upload)).json())["model"]
        assert (model["wmape"], model["mae"], model["bias"]) == (
            pytest.approx(0.0, abs=TOL), pytest.approx(0.0, abs=TOL), pytest.approx(0.0, abs=TOL),
        )


class TestBiasSign:

    async def test_over_forecast_has_positive_bias(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path
    ):
        actual = [v - 10 for v in FORECAST_VALS]            # forecast is 10 too high everywhere
        dates, vals = _history_plus(FORECAST_DATES, actual)
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, test_user, content=_csv_bytes(dates, vals))
        model = _metric((await evaluate(async_client, headers, job, upload)).json())["model"]
        assert model["bias"] == pytest.approx(expected_scores(actual, FORECAST_VALS)["bias"], abs=TOL)
        assert model["bias"] > 0

    async def test_under_forecast_has_negative_bias(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path
    ):
        actual = [v + 10 for v in FORECAST_VALS]            # forecast is 10 too low everywhere
        dates, vals = _history_plus(FORECAST_DATES, actual)
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, test_user, content=_csv_bytes(dates, vals))
        model = _metric((await evaluate(async_client, headers, job, upload)).json())["model"]
        assert model["bias"] < 0


class TestPartialEvaluation:

    async def test_half_coverage_is_partial_with_matched_count(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path
    ):
        dates, vals = _history_plus(FORECAST_DATES[:5], ACTUAL_VALS[:5])
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, test_user, content=_csv_bytes(dates, vals))
        m = _metric((await evaluate(async_client, headers, job, upload)).json())
        assert (m["status"], m["model"]["matched_points"], m["forecast_points"]) == ("partial", 5, 10)

    async def test_partial_scores_use_only_matched_dates(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path
    ):
        dates, vals = _history_plus(FORECAST_DATES[:5], ACTUAL_VALS[:5])
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, test_user, content=_csv_bytes(dates, vals))
        exp = expected_scores(ACTUAL_VALS[:5], FORECAST_VALS[:5])
        model = _metric((await evaluate(async_client, headers, job, upload)).json())["model"]
        assert model["wmape"] == pytest.approx(exp["wmape"], abs=TOL)
        assert model["mae"] == pytest.approx(exp["mae"], abs=TOL)
        assert model["forecast_total"] == pytest.approx(exp["forecast_total"], abs=TOL)

    async def test_null_actual_on_a_forecast_date_is_not_compared(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path
    ):
        vals = list(ACTUAL_VALS)
        vals[3] = None                                       # empty CSV cell on 2025-01-04
        dates, all_vals = _history_plus(FORECAST_DATES, vals)
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, test_user, content=_csv_bytes(dates, all_vals))
        keep = [i for i in range(10) if i != 3]
        exp  = expected_scores([ACTUAL_VALS[i] for i in keep], [FORECAST_VALS[i] for i in keep])
        m = _metric((await evaluate(async_client, headers, job, upload)).json())
        assert (m["status"], m["model"]["matched_points"]) == ("partial", 9)
        assert m["model"]["wmape"] == pytest.approx(exp["wmape"], abs=TOL)

    async def test_gap_in_actual_dates_matches_only_present_dates(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path
    ):
        keep = [0, 1, 2, 7, 8, 9]                            # dates 3..6 absent from the file
        dates, vals = _history_plus([FORECAST_DATES[i] for i in keep], [ACTUAL_VALS[i] for i in keep])
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, test_user, content=_csv_bytes(dates, vals))
        m = _metric((await evaluate(async_client, headers, job, upload)).json())
        assert (m["status"], m["model"]["matched_points"]) == ("partial", 6)

    async def test_partial_response_gives_total_forecast_points_not_matched(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path
    ):
        dates, vals = _history_plus(FORECAST_DATES[:2], ACTUAL_VALS[:2])
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, test_user, content=_csv_bytes(dates, vals))
        m = _metric((await evaluate(async_client, headers, job, upload)).json())
        assert len(m["points"]) == 2 and m["forecast_points"] == 10


class TestNoOverlap:

    async def test_upload_ending_before_forecast_is_no_overlap(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path
    ):
        old_dates = [d.strftime("%Y-%m-%d") for d in pd.date_range("2024-11-01", periods=30, freq="D")]
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, test_user,
                                   content=_csv_bytes(old_dates, [100.0 + (i % 7) for i in range(30)]))
        res = await evaluate(async_client, headers, job, upload)
        assert res.status_code in (200, 201)
        m = _metric(res.json())
        assert m["status"] == "no_overlap"
        assert m["actuals_last_date"].startswith("2024-11-30")

    async def test_no_overlap_carries_no_scores_and_keeps_forecast_period(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path
    ):
        old_dates = [d.strftime("%Y-%m-%d") for d in pd.date_range("2024-11-01", periods=30, freq="D")]
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, test_user,
                                   content=_csv_bytes(old_dates, [100.0 + (i % 7) for i in range(30)]))
        m = _metric((await evaluate(async_client, headers, job, upload)).json())
        assert m["model"] is None and m["adjusted"] is None and m["points"] == []
        assert (m["forecast_start"][:10], m["forecast_end"][:10]) == ("2025-01-01", "2025-01-10")

    async def test_no_overlap_is_remembered_on_get_and_names_the_file(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path
    ):
        old_dates = [d.strftime("%Y-%m-%d") for d in pd.date_range("2024-11-01", periods=30, freq="D")]
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, test_user, file_name="too-early.csv",
                                   content=_csv_bytes(old_dates, [100.0 + (i % 7) for i in range(30)]))
        await evaluate(async_client, headers, job, upload)
        m = _metric((await async_client.get(_url(job.id), headers=headers)).json())
        assert (m["status"], m["upload_file_name"]) == ("no_overlap", "too-early.csv")

    async def test_no_overlap_row_is_stored_with_zero_matched_points(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path
    ):
        old_dates = [d.strftime("%Y-%m-%d") for d in pd.date_range("2024-11-01", periods=30, freq="D")]
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, test_user,
                                   content=_csv_bytes(old_dates, [100.0 + (i % 7) for i in range(30)]))
        await evaluate(async_client, headers, job, upload)
        row = (await db_session.execute(select(ForecastEvaluation))).scalar_one()
        assert row.matched_points == 0 and row.forecast_points == 10


class TestPinnedMetricDefinitions:

    async def test_all_zero_actuals_give_null_wmape_and_bias_not_a_huge_number(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path
    ):
        dates, vals = _history_plus(FORECAST_DATES, [0.0] * 10)
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, test_user, content=_csv_bytes(dates, vals))
        m = _metric((await evaluate(async_client, headers, job, upload)).json())
        assert m["status"] == "complete"
        assert m["model"]["wmape"] is None
        assert m["model"]["bias"] is None

    async def test_all_zero_actuals_still_report_mae(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path
    ):
        dates, vals = _history_plus(FORECAST_DATES, [0.0] * 10)
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, test_user, content=_csv_bytes(dates, vals))
        model = _metric((await evaluate(async_client, headers, job, upload)).json())["model"]
        assert model["mae"] == pytest.approx(sum(FORECAST_VALS) / 10, abs=TOL)

    async def test_all_zero_actuals_store_null_not_a_number_in_db(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path
    ):
        dates, vals = _history_plus(FORECAST_DATES, [0.0] * 10)
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, test_user, content=_csv_bytes(dates, vals))
        await evaluate(async_client, headers, job, upload)
        row = (await db_session.execute(select(ForecastEvaluation))).scalar_one()
        assert row.wmape is None and row.bias is None

    async def test_negative_actuals_are_not_clipped_at_zero(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path
    ):
        # Roughly symmetric around 20 so no sanitising rule treats -5 as an outlier.
        actual   = [-5.0, 5.0, 10.0, 15.0, 20.0, 25.0, 30.0, 35.0, 40.0, 45.0]
        forecast = [10.0] * 10
        results  = {"Sheet1": {"metrics": {METRIC: {"records": _records(FORECAST_DATES, forecast)}}}}
        job    = await make_job(db_session, test_user, tmp_path, results=results)
        upload = await make_upload(db_session, s3_client, test_user,
                                   content=_csv_bytes(FORECAST_DATES, actual))
        exp = expected_scores(actual, forecast)
        m = _metric((await evaluate(async_client, headers, job, upload)).json())
        assert m["model"]["actual_total"] == pytest.approx(exp["actual_total"], abs=TOL)
        assert m["model"]["wmape"] == pytest.approx(exp["wmape"], abs=TOL)
        assert m["points"][0]["actual"] == pytest.approx(-5.0)

    async def test_wmape_is_ratio_of_sums_not_mean_of_ratios(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path
    ):
        # Per-point ratios would be 0.5 and 0.01 (mean 0.255); ratio of sums is 51/1010... computed below.
        actual   = [10.0, 1000.0]
        forecast = [15.0, 1010.0]
        dates    = FORECAST_DATES[:2]
        results  = {"Sheet1": {"metrics": {METRIC: {"records": _records(dates, forecast)}}}}
        job    = await make_job(db_session, test_user, tmp_path, results=results)
        upload = await make_upload(db_session, s3_client, test_user, content=_csv_bytes(dates, actual))
        model = _metric((await evaluate(async_client, headers, job, upload)).json())["model"]
        assert model["wmape"] == pytest.approx((5 + 10) / 1010, abs=TOL)


# ══════════════════════════════════════════════════════════════════════
# Sheet matching
# ══════════════════════════════════════════════════════════════════════

class TestSheetMatching:

    @staticmethod
    def _two_sheet_results() -> dict:
        recs = _records(FORECAST_DATES, FORECAST_VALS)
        return {
            "Alpha": {"metrics": {METRIC: {"records": recs}}},
            "Beta" : {"metrics": {METRIC: {"records": recs}}},
        }

    async def test_same_name_sheets_are_paired_and_unmatched_sheet_awaits(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path
    ):
        content = _xlsx_bytes({
            "Beta"  : (FORECAST_DATES, ACTUAL_VALS),
            "Gamma" : (FORECAST_DATES, ACTUAL_VALS),
        })
        job    = await make_job(db_session, test_user, tmp_path, results=self._two_sheet_results())
        upload = await make_upload(
            db_session, s3_client, test_user, content=content, file_name="actuals.xlsx",
            sheet_columns={"Beta": ["date", METRIC], "Gamma": ["date", METRIC]},
        )
        res = await evaluate(async_client, headers, job, upload)
        assert res.status_code in (200, 201)
        body = res.json()
        assert _metric(body, "Beta")["status"] == "complete"
        assert _metric(body, "Alpha")["status"] == "awaiting_actuals"

    async def test_unmatched_sheet_is_never_guessed(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path
    ):
        # Two job sheets, one differently-named upload sheet: the "lone sheet" rule needs
        # exactly one sheet on BOTH sides, so nothing may be paired.
        content = _xlsx_bytes({"Gamma": (FORECAST_DATES, ACTUAL_VALS)})
        job    = await make_job(db_session, test_user, tmp_path, results=self._two_sheet_results())
        upload = await make_upload(
            db_session, s3_client, test_user, content=content, file_name="actuals.xlsx",
            sheet_columns={"Gamma": ["date", METRIC]},
        )
        res = await evaluate(async_client, headers, job, upload)
        assert res.status_code in (200, 201)
        body = res.json()
        assert {m["status"] for m in body["metrics"]} == {"awaiting_actuals"}
        assert all(m["model"] is None for m in body["metrics"])

    async def test_unmatched_sheets_on_both_sides_stay_awaiting(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path
    ):
        content = _xlsx_bytes({"X": (FORECAST_DATES, ACTUAL_VALS), "Y": (FORECAST_DATES, ACTUAL_VALS)})
        job    = await make_job(db_session, test_user, tmp_path, results=self._two_sheet_results())
        upload = await make_upload(
            db_session, s3_client, test_user, content=content, file_name="actuals.xlsx",
            sheet_columns={"X": ["date", METRIC], "Y": ["date", METRIC]},
        )
        body = (await evaluate(async_client, headers, job, upload)).json()
        assert {m["status"] for m in body["metrics"]} == {"awaiting_actuals"}

    async def test_lone_job_sheet_pairs_with_lone_upload_sheet_whatever_their_names(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path
    ):
        results = {"Sales": {"metrics": {METRIC: {"records": _records(FORECAST_DATES, FORECAST_VALS)}}}}
        content = _xlsx_bytes({"Renamed Export": (FORECAST_DATES, ACTUAL_VALS)})
        job    = await make_job(db_session, test_user, tmp_path, results=results)
        upload = await make_upload(
            db_session, s3_client, test_user, content=content, file_name="actuals.xlsx",
            sheet_columns={"Renamed Export": ["date", METRIC]},
        )
        m = _metric((await evaluate(async_client, headers, job, upload)).json(), "Sales")
        assert m["status"] == "complete"
        assert m["model"]["wmape"] == pytest.approx(expected_scores(ACTUAL_VALS, FORECAST_VALS)["wmape"], abs=TOL)

    async def test_csv_sheet1_pairs_with_a_differently_named_lone_job_sheet(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path
    ):
        results = {"Monthly": {"metrics": {METRIC: {"records": _records(FORECAST_DATES, FORECAST_VALS)}}}}
        job    = await make_job(db_session, test_user, tmp_path, results=results)
        upload = await make_upload(db_session, s3_client, test_user,
                                   content=_csv_bytes(FORECAST_DATES, ACTUAL_VALS))
        m = _metric((await evaluate(async_client, headers, job, upload)).json(), "Monthly")
        assert m["status"] == "complete"

    async def test_metric_missing_from_one_matched_sheet_stays_awaiting(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path
    ):
        recs = _records(FORECAST_DATES, FORECAST_VALS)
        results = {"Sheet1": {"metrics": {METRIC: {"records": recs}, "revenue": {"records": recs}}}}
        job    = await make_job(db_session, test_user, tmp_path, results=results)
        upload = await make_upload(db_session, s3_client, test_user,
                                   content=_csv_bytes(FORECAST_DATES, ACTUAL_VALS))
        body = (await evaluate(async_client, headers, job, upload)).json()
        assert _metric(body, "Sheet1", METRIC)["status"] == "complete"
        assert _metric(body, "Sheet1", "revenue")["status"] == "awaiting_actuals"


# ══════════════════════════════════════════════════════════════════════
# DB side effects, upsert, newest-wins, cascade
# ══════════════════════════════════════════════════════════════════════

class TestEvaluationPersistence:

    async def test_post_writes_one_row_with_expected_columns(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path, full_actuals_csv
    ):
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, test_user, content=full_actuals_csv,
                                   file_name="january-actuals.csv")
        await evaluate(async_client, headers, job, upload)
        rows = (await db_session.execute(select(ForecastEvaluation))).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert (row.job_id, row.user_id, row.upload_id) == (job.id, test_user.id, upload.id)
        assert (row.upload_file_name, row.sheet_name, row.metric_name) == (
            "january-actuals.csv", "Sheet1", METRIC,
        )
        assert (row.forecast_points, row.matched_points) == (10, 10)

    async def test_stored_scores_match_hand_computed_values(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path, full_actuals_csv
    ):
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, test_user, content=full_actuals_csv)
        await evaluate(async_client, headers, job, upload)
        row = (await db_session.execute(select(ForecastEvaluation))).scalar_one()
        exp = expected_scores(ACTUAL_VALS, FORECAST_VALS)
        assert row.wmape == pytest.approx(exp["wmape"], abs=TOL)
        assert row.mae == pytest.approx(exp["mae"], abs=TOL)
        assert row.bias == pytest.approx(exp["bias"], abs=TOL)

    async def test_stored_points_hold_actual_and_forecast_per_matched_date(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path, full_actuals_csv
    ):
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, test_user, content=full_actuals_csv)
        await evaluate(async_client, headers, job, upload)
        row = (await db_session.execute(select(ForecastEvaluation))).scalar_one()
        assert [p["date"][:10] for p in row.points] == FORECAST_DATES
        assert [p["actual"] for p in row.points] == pytest.approx(ACTUAL_VALS)
        assert [p["forecast"] for p in row.points] == pytest.approx(FORECAST_VALS)

    async def test_stored_points_contain_no_adjusted_forecast(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path, full_actuals_csv
    ):
        job    = await make_job(db_session, test_user, tmp_path)
        await add_set_value_edit(db_session, job, test_user, value=50.0, seq=1)
        upload = await make_upload(db_session, s3_client, test_user, content=full_actuals_csv)
        await evaluate(async_client, headers, job, upload)
        row = (await db_session.execute(select(ForecastEvaluation))).scalar_one()
        assert all("adjusted_forecast" not in p or p["adjusted_forecast"] is None for p in row.points)

    async def test_re_evaluating_same_upload_replaces_the_row(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path, full_actuals_csv
    ):
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, test_user, content=full_actuals_csv)
        await evaluate(async_client, headers, job, upload)
        res = await evaluate(async_client, headers, job, upload)
        assert res.status_code in (200, 201)
        count = await db_session.scalar(
            select(func.count()).select_from(ForecastEvaluation).where(ForecastEvaluation.job_id == job.id)
        )
        assert count == 1

    async def test_re_evaluating_same_upload_picks_up_changed_file_contents(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path, full_actuals_csv
    ):
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, test_user, content=full_actuals_csv)
        await evaluate(async_client, headers, job, upload)
        # Same upload id, now with only half the forecast period present.
        dates, vals = _history_plus(FORECAST_DATES[:5], ACTUAL_VALS[:5])
        s3_client.put_object(Bucket=settings.S3_BUCKET_NAME, Key=upload.s3_key, Body=_csv_bytes(dates, vals))
        m = _metric((await evaluate(async_client, headers, job, upload)).json())
        assert (m["status"], m["model"]["matched_points"]) == ("partial", 5)

    async def test_different_upload_adds_a_row_and_get_shows_the_newest(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path, full_actuals_csv
    ):
        job   = await make_job(db_session, test_user, tmp_path)
        first = await make_upload(db_session, s3_client, test_user, content=full_actuals_csv,
                                  file_name="first.csv", days=5)
        await evaluate(async_client, headers, job, first)
        # now() is the transaction start inside a test; back-date the first row so "newest" is unambiguous.
        await db_session.execute(
            update(ForecastEvaluation).where(ForecastEvaluation.upload_id == first.id)
            .values(created_at=BASE_TIME - timedelta(days=1))
        )
        await db_session.flush()

        half_dates, half_vals = _history_plus(FORECAST_DATES[:5], ACTUAL_VALS[:5])
        second = await make_upload(db_session, s3_client, test_user, file_name="second.csv", days=6,
                                   content=_csv_bytes(half_dates, half_vals))
        await evaluate(async_client, headers, job, second)

        count = await db_session.scalar(
            select(func.count()).select_from(ForecastEvaluation).where(ForecastEvaluation.job_id == job.id)
        )
        assert count == 2
        m = _metric((await async_client.get(_url(job.id), headers=headers)).json())
        assert (m["upload_file_name"], m["status"]) == ("second.csv", "partial")

    async def test_get_returns_a_single_entry_per_metric_after_several_evaluations(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path, full_actuals_csv
    ):
        job = await make_job(db_session, test_user, tmp_path)
        for i, name in enumerate(["a.csv", "b.csv"]):
            up = await make_upload(db_session, s3_client, test_user, content=full_actuals_csv,
                                   file_name=name, days=5 + i)
            await evaluate(async_client, headers, job, up)
        body = (await async_client.get(_url(job.id), headers=headers)).json()
        assert len(body["metrics"]) == 1

    async def test_evaluation_is_scoped_to_its_own_job(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path, full_actuals_csv
    ):
        job_a  = await make_job(db_session, test_user, tmp_path, name="a")
        job_b  = await make_job(db_session, test_user, tmp_path, name="b")
        upload = await make_upload(db_session, s3_client, test_user, content=full_actuals_csv)
        await evaluate(async_client, headers, job_a, upload)
        m = _metric((await async_client.get(_url(job_b.id), headers=headers)).json())
        assert m["status"] == "awaiting_actuals"

    async def test_deleting_the_job_removes_its_evaluations(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path, full_actuals_csv
    ):
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, test_user, content=full_actuals_csv)
        await evaluate(async_client, headers, job, upload)
        await db_session.execute(delete(ForecastJob).where(ForecastJob.id == job.id))
        await db_session.flush()
        count = await db_session.scalar(select(func.count()).select_from(ForecastEvaluation))
        assert count == 0

    async def test_deleting_the_upload_keeps_the_evaluation_and_file_name(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path, full_actuals_csv
    ):
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, test_user, content=full_actuals_csv,
                                   file_name="gone-soon.csv")
        await evaluate(async_client, headers, job, upload)
        await db_session.execute(delete(Upload).where(Upload.id == upload.id))
        await db_session.flush()
        db_session.expire_all()
        row = (await db_session.execute(select(ForecastEvaluation))).scalar_one()
        assert row.upload_id is None and row.upload_file_name == "gone-soon.csv"

    async def test_pre_f17_job_without_any_evaluation_can_be_evaluated(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path, full_actuals_csv
    ):
        # Seeded jobs have only a results.json and no evaluation rows: exactly a pre-F17 run.
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, test_user, content=full_actuals_csv)
        assert (await evaluate(async_client, headers, job, upload)).status_code in (200, 201)


# ══════════════════════════════════════════════════════════════════════
# Adjusted forecast (Action Center edit stack, computed at read time)
# ══════════════════════════════════════════════════════════════════════

class TestAdjustedForecast:

    async def test_adjusted_is_null_without_edits(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path, full_actuals_csv
    ):
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, test_user, content=full_actuals_csv)
        m = _metric((await evaluate(async_client, headers, job, upload)).json())
        assert m["adjusted"] is None

    async def test_points_have_null_adjusted_forecast_without_edits(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path, full_actuals_csv
    ):
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, test_user, content=full_actuals_csv)
        m = _metric((await evaluate(async_client, headers, job, upload)).json())
        assert all(p["adjusted_forecast"] is None for p in m["points"])

    async def test_adjusted_is_present_and_differs_from_model_when_edits_exist(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path, full_actuals_csv
    ):
        job = await make_job(db_session, test_user, tmp_path)
        await add_set_value_edit(db_session, job, test_user, value=ACTUAL_VALS[0], seq=1)
        upload = await make_upload(db_session, s3_client, test_user, content=full_actuals_csv)
        m = _metric((await evaluate(async_client, headers, job, upload)).json())
        assert m["adjusted"] is not None
        assert m["adjusted"] != m["model"]
        assert m["adjusted"]["wmape"] != pytest.approx(m["model"]["wmape"], abs=1e-6)

    async def test_adjusted_scores_follow_the_edited_forecast(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path, full_actuals_csv
    ):
        job = await make_job(db_session, test_user, tmp_path)
        await add_set_value_edit(db_session, job, test_user, value=130.0, seq=1)
        upload = await make_upload(db_session, s3_client, test_user, content=full_actuals_csv)
        exp = expected_scores(ACTUAL_VALS, [130.0] * 10)
        adjusted = _metric((await evaluate(async_client, headers, job, upload)).json())["adjusted"]
        assert adjusted["wmape"] == pytest.approx(exp["wmape"], abs=TOL)
        assert adjusted["mae"] == pytest.approx(exp["mae"], abs=TOL)
        assert adjusted["bias"] == pytest.approx(exp["bias"], abs=TOL)

    async def test_points_expose_adjusted_forecast_when_edits_exist(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path, full_actuals_csv
    ):
        job = await make_job(db_session, test_user, tmp_path)
        await add_set_value_edit(db_session, job, test_user, value=130.0, seq=1)
        upload = await make_upload(db_session, s3_client, test_user, content=full_actuals_csv)
        points = _metric((await evaluate(async_client, headers, job, upload)).json())["points"]
        assert [p["adjusted_forecast"] for p in points] == pytest.approx([130.0] * 10)
        assert [p["forecast"] for p in points] == pytest.approx(FORECAST_VALS)

    async def test_model_scores_are_not_changed_by_edits(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path, full_actuals_csv
    ):
        job = await make_job(db_session, test_user, tmp_path)
        await add_set_value_edit(db_session, job, test_user, value=130.0, seq=1)
        upload = await make_upload(db_session, s3_client, test_user, content=full_actuals_csv)
        model = _metric((await evaluate(async_client, headers, job, upload)).json())["model"]
        assert model["wmape"] == pytest.approx(expected_scores(ACTUAL_VALS, FORECAST_VALS)["wmape"], abs=TOL)

    async def test_edit_added_after_evaluating_changes_adjusted_on_next_get(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path, full_actuals_csv
    ):
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, test_user, content=full_actuals_csv)
        before = _metric((await evaluate(async_client, headers, job, upload)).json())
        assert before["adjusted"] is None

        await add_set_value_edit(db_session, job, test_user, value=130.0, seq=1)
        after = _metric((await async_client.get(_url(job.id), headers=headers)).json())
        assert after["adjusted"] is not None
        assert after["adjusted"]["wmape"] == pytest.approx(
            expected_scores(ACTUAL_VALS, [130.0] * 10)["wmape"], abs=TOL
        )

    async def test_further_edit_after_evaluating_replaces_the_previous_adjusted_numbers(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path, full_actuals_csv
    ):
        job = await make_job(db_session, test_user, tmp_path)
        await add_set_value_edit(db_session, job, test_user, value=130.0, seq=1)
        upload = await make_upload(db_session, s3_client, test_user, content=full_actuals_csv)
        await evaluate(async_client, headers, job, upload)

        await add_set_value_edit(db_session, job, test_user, value=300.0, seq=2)
        m = _metric((await async_client.get(_url(job.id), headers=headers)).json())
        assert m["adjusted"]["wmape"] == pytest.approx(
            expected_scores(ACTUAL_VALS, [300.0] * 10)["wmape"], abs=TOL
        )
        assert m["model"]["wmape"] == pytest.approx(
            expected_scores(ACTUAL_VALS, FORECAST_VALS)["wmape"], abs=TOL
        )

    async def test_removing_all_edits_makes_adjusted_null_again(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path, full_actuals_csv
    ):
        job  = await make_job(db_session, test_user, tmp_path)
        edit = await add_set_value_edit(db_session, job, test_user, value=130.0, seq=1)
        upload = await make_upload(db_session, s3_client, test_user, content=full_actuals_csv)
        await evaluate(async_client, headers, job, upload)
        await db_session.execute(delete(ForecastEdit).where(ForecastEdit.id == edit.id))
        await db_session.flush()
        m = _metric((await async_client.get(_url(job.id), headers=headers)).json())
        assert m["adjusted"] is None

    async def test_edits_on_another_metric_do_not_produce_adjusted(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path, full_actuals_csv
    ):
        job = await make_job(db_session, test_user, tmp_path)
        edit = await add_set_value_edit(db_session, job, test_user, value=130.0, seq=1)
        await db_session.execute(
            update(ForecastEdit).where(ForecastEdit.id == edit.id).values(metric_name="some_other_metric")
        )
        await db_session.flush()
        upload = await make_upload(db_session, s3_client, test_user, content=full_actuals_csv)
        m = _metric((await evaluate(async_client, headers, job, upload)).json())
        assert m["adjusted"] is None


# ══════════════════════════════════════════════════════════════════════
# Candidates
# ══════════════════════════════════════════════════════════════════════

class TestCandidates:

    async def _candidates(self, async_client, headers, job) -> list[dict]:
        res = await async_client.get(_url(job.id, "/candidates"), headers=headers)
        assert res.status_code == 200
        return res.json()["candidates"]

    async def test_no_uploads_gives_empty_list(self, async_client, db_session, headers, test_user, tmp_path):
        job = await make_job(db_session, test_user, tmp_path)
        assert await self._candidates(async_client, headers, job) == []

    async def test_newer_upload_with_job_metric_is_listed_with_expected_fields(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path
    ):
        job = await make_job(db_session, test_user, tmp_path, days=0)
        up  = await make_upload(db_session, s3_client, test_user, content=b"date,units\n",
                                file_name="later.csv", days=3)
        [cand] = await self._candidates(async_client, headers, job)
        assert (cand["upload_id"], cand["file_name"]) == (up.id, "later.csv")
        assert cand["created_at"]

    async def test_upload_older_than_the_job_is_excluded(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path
    ):
        job = await make_job(db_session, test_user, tmp_path, days=10)
        await make_upload(db_session, s3_client, test_user, content=b"date,units\n", days=2)
        assert await self._candidates(async_client, headers, job) == []

    async def test_jobs_own_input_upload_is_excluded_even_if_created_after_the_job(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path
    ):
        own = await make_upload(db_session, s3_client, test_user, content=b"date,units\n",
                                file_name="own-input.csv", days=2)
        job = await make_job(db_session, test_user, tmp_path, input_upload=own, days=0)
        assert await self._candidates(async_client, headers, job) == []

    async def test_other_users_upload_is_excluded(
        self, async_client, db_session, s3_client, headers, test_user, second_user, tmp_path
    ):
        job = await make_job(db_session, test_user, tmp_path, days=0)
        await make_upload(db_session, s3_client, second_user, content=b"date,units\n", days=3)
        assert await self._candidates(async_client, headers, job) == []

    async def test_upload_without_any_job_metric_column_is_excluded(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path
    ):
        job = await make_job(db_session, test_user, tmp_path, days=0)
        await make_upload(db_session, s3_client, test_user, content=b"date,revenue\n", days=3,
                          sheet_columns={"Sheet1": ["date", "revenue"]})
        assert await self._candidates(async_client, headers, job) == []

    async def test_upload_matching_only_one_of_several_job_metrics_is_included(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path
    ):
        recs = _records(FORECAST_DATES, FORECAST_VALS)
        results = {"Sheet1": {"metrics": {"units": {"records": recs}, "revenue": {"records": recs}}}}
        job = await make_job(db_session, test_user, tmp_path, results=results, days=0)
        up  = await make_upload(db_session, s3_client, test_user, content=b"date,revenue\n", days=3,
                                sheet_columns={"Sheet1": ["date", "revenue"]})
        assert [c["upload_id"] for c in await self._candidates(async_client, headers, job)] == [up.id]

    async def test_candidates_are_ordered_newest_first(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path
    ):
        job = await make_job(db_session, test_user, tmp_path, days=0)
        a = await make_upload(db_session, s3_client, test_user, content=b"date,units\n", days=2, file_name="a.csv")
        c = await make_upload(db_session, s3_client, test_user, content=b"date,units\n", days=9, file_name="c.csv")
        b = await make_upload(db_session, s3_client, test_user, content=b"date,units\n", days=5, file_name="b.csv")
        ids = [x["upload_id"] for x in await self._candidates(async_client, headers, job)]
        assert ids == [c.id, b.id, a.id]

    async def test_candidates_are_capped_at_20_keeping_the_newest(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path
    ):
        job = await make_job(db_session, test_user, tmp_path, days=0)
        uploads = [
            await make_upload(db_session, s3_client, test_user, content=b"date,units\n",
                              days=1 + i, file_name=f"u{i}.csv")
            for i in range(22)
        ]
        ids = [x["upload_id"] for x in await self._candidates(async_client, headers, job)]
        assert len(ids) == 20
        assert ids[0] == uploads[-1].id
        assert uploads[0].id not in ids

    async def test_listing_candidates_does_not_require_the_file_to_exist_in_storage(
        self, async_client, db_session, headers, test_user, tmp_path
    ):
        # Filtering uses Upload.columns only, so no S3 access (s3_client fixture deliberately absent
        # from the mocked bucket contents) is needed.
        job = await make_job(db_session, test_user, tmp_path, days=0)
        db_session.add(Upload(
            id=str(uuid.uuid4()), user_id=test_user.id, file_name="ghost.csv",
            s3_key="uploads/ghost/ghost.csv", sheets=["Sheet1"],
            columns={"Sheet1": ["date", METRIC]}, row_counts={"Sheet1": 1},
            file_size_bytes=1, created_at=_at(3),
        ))
        await db_session.flush()
        assert len(await self._candidates(async_client, headers, job)) == 1


# ══════════════════════════════════════════════════════════════════════
# Dashboard: realized_wmape / realized_runs
# ══════════════════════════════════════════════════════════════════════

async def _dash_job(db, user, *, minute: int, backtest_wmape: float = 0.1) -> ForecastJob:
    job = ForecastJob(
        id=str(uuid.uuid4()), user_id=user.id, status="success", progress_pct=100,
        file_name="sales.csv", created_at=BASE_TIME + timedelta(minutes=minute),
        completed_at=BASE_TIME + timedelta(minutes=minute, seconds=30),
        started_at=BASE_TIME + timedelta(minutes=minute),
    )
    db.add(job)
    await db.flush()
    db.add(ModelRun(
        id=str(uuid.uuid4()), job_id=job.id, sheet_name="Sheet1", metric_name=METRIC,
        model_name="Prophet", stage="Univariate", wmape=backtest_wmape,
        demand_type="Smooth", is_champion=True, status="completed",
    ))
    await db.flush()
    return job


async def _dash_eval(
    db, job, *, wmape: float | None, matched: int = 10, minute: int = 0, user=None,
    metric: str = METRIC,
) -> ForecastEvaluation:
    row = ForecastEvaluation(
        id=str(uuid.uuid4()), job_id=job.id, user_id=(user.id if user else job.user_id),
        upload_id=None, upload_file_name="actuals.csv", sheet_name="Sheet1", metric_name=metric,
        forecast_points=10, matched_points=matched, wmape=wmape, mae=1.0, bias=0.0,
        actual_total=100.0, forecast_total=100.0, points=[],
        created_at=BASE_TIME + timedelta(minutes=minute),
    )
    db.add(row)
    await db.flush()
    return row


class TestDashboardRealizedHeadline:

    async def _summary(self, async_client, headers) -> dict:
        res = await async_client.get("/api/v1/dashboard", headers=headers)
        assert res.status_code == 200
        return res.json()

    async def test_no_evaluations_gives_null_realized_wmape_and_zero_runs(
        self, async_client, db_session, headers, test_user
    ):
        await _dash_job(db_session, test_user, minute=1)
        body = await self._summary(async_client, headers)
        assert body["realized_wmape"] is None
        assert body["realized_runs"] == 0

    async def test_empty_account_has_the_realized_fields(self, async_client, headers):
        body = await self._summary(async_client, headers)
        assert body["realized_wmape"] is None
        assert body["realized_runs"] == 0

    async def test_realized_wmape_is_median_over_measured_runs(
        self, async_client, db_session, headers, test_user
    ):
        for minute, w in [(1, 0.2), (2, 0.4), (3, 0.9)]:
            job = await _dash_job(db_session, test_user, minute=minute)
            await _dash_eval(db_session, job, wmape=w)
        body = await self._summary(async_client, headers)
        assert body["realized_runs"] == 3
        assert body["realized_wmape"] == pytest.approx(0.4)

    async def test_even_count_median_averages_the_two_middle_runs(
        self, async_client, db_session, headers, test_user
    ):
        for minute, w in [(1, 0.2), (2, 0.4)]:
            job = await _dash_job(db_session, test_user, minute=minute)
            await _dash_eval(db_session, job, wmape=w)
        body = await self._summary(async_client, headers)
        assert body["realized_wmape"] == pytest.approx(0.3)

    async def test_partial_evaluations_count_toward_the_headline(
        self, async_client, db_session, headers, test_user
    ):
        job = await _dash_job(db_session, test_user, minute=1)
        await _dash_eval(db_session, job, wmape=0.25, matched=4)       # 4 of 10 dates: partial
        body = await self._summary(async_client, headers)
        assert (body["realized_runs"], body["realized_wmape"]) == (1, pytest.approx(0.25))

    async def test_no_overlap_evaluations_are_not_counted(
        self, async_client, db_session, headers, test_user
    ):
        job = await _dash_job(db_session, test_user, minute=1)
        await _dash_eval(db_session, job, wmape=None, matched=0)
        body = await self._summary(async_client, headers)
        assert body["realized_runs"] == 0 and body["realized_wmape"] is None

    async def test_run_counted_once_using_its_newest_evaluation(
        self, async_client, db_session, headers, test_user
    ):
        job = await _dash_job(db_session, test_user, minute=1)
        await _dash_eval(db_session, job, wmape=0.9, minute=10)        # older
        await _dash_eval(db_session, job, wmape=0.1, minute=20)        # newer
        body = await self._summary(async_client, headers)
        assert body["realized_runs"] == 1
        assert body["realized_wmape"] == pytest.approx(0.1)

    async def test_realized_headline_is_separate_from_backtest_median(
        self, async_client, db_session, headers, test_user
    ):
        job = await _dash_job(db_session, test_user, minute=1, backtest_wmape=0.07)
        await _dash_eval(db_session, job, wmape=0.31)
        body = await self._summary(async_client, headers)
        assert body["median_wmape"] == pytest.approx(0.07)
        assert body["realized_wmape"] == pytest.approx(0.31)

    async def test_realized_evaluations_do_not_change_the_backtest_median(
        self, async_client, db_session, headers, test_user
    ):
        await _dash_job(db_session, test_user, minute=1, backtest_wmape=0.07)
        before = (await self._summary(async_client, headers))["median_wmape"]
        job = await _dash_job(db_session, test_user, minute=2, backtest_wmape=0.07)
        await _dash_eval(db_session, job, wmape=0.9)
        after = (await self._summary(async_client, headers))["median_wmape"]
        assert before == pytest.approx(0.07) and after == pytest.approx(0.07)

    async def test_other_users_evaluations_are_not_counted(
        self, async_client, db_session, headers, test_user, second_user
    ):
        mine   = await _dash_job(db_session, test_user, minute=1)
        theirs = await _dash_job(db_session, second_user, minute=2)
        await _dash_eval(db_session, mine, wmape=0.2)
        await _dash_eval(db_session, theirs, wmape=0.8)
        body = await self._summary(async_client, headers)
        assert (body["realized_runs"], body["realized_wmape"]) == (1, pytest.approx(0.2))

    async def test_realized_headline_requires_auth(self, async_client):
        res = await async_client.get("/api/v1/dashboard")
        assert res.status_code == 401

    async def test_posting_an_evaluation_updates_the_dashboard_headline(
        self, async_client, db_session, s3_client, headers, test_user, tmp_path, full_actuals_csv
    ):
        job    = await make_job(db_session, test_user, tmp_path)
        upload = await make_upload(db_session, s3_client, test_user, content=full_actuals_csv)
        await evaluate(async_client, headers, job, upload)
        body = (await async_client.get("/api/v1/dashboard", headers=headers)).json()
        assert body["realized_runs"] == 1
        assert body["realized_wmape"] == pytest.approx(expected_scores(ACTUAL_VALS, FORECAST_VALS)["wmape"], abs=TOL)
