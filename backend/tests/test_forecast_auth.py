"""
backend/tests/test_forecast_auth.py
=====================================
Integration tests for F3 (auth-enforcement): every forecast route requires
a user, and users may only touch their own jobs. A job that exists but
belongs to someone else must be indistinguishable from a job that doesn't
exist at all — both return 404, never 403.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from functools import partial

from backend.models.db_models import ForecastJob
from conftest import make_csv_bytes

_make_csv_bytes = partial(make_csv_bytes, rows=10, sales=range(10))


async def _make_job(db_session, owner_id: str, **overrides) -> ForecastJob:
    job = ForecastJob(
        id=str(uuid.uuid4()),
        user_id=owner_id,
        status=overrides.pop("status", "success"),
        progress_pct=overrides.pop("progress_pct", 100),
        progress_message=overrides.pop("progress_message", "Completed successfully"),
        s3_output_key=overrides.pop("s3_output_key", None),
        created_at=datetime.now(timezone.utc),
        **overrides,
    )
    db_session.add(job)
    await db_session.flush()
    return job


class TestForecastOwnership:
    """User B must never be able to read or stop User A's job."""

    async def test_cross_tenant_get_job_returns_404(
        self, async_client, db_session, test_user, second_user, make_auth_headers
    ):
        job = await _make_job(db_session, owner_id=test_user.id)
        res = await async_client.get(
            f"/api/v1/forecast/{job.id}", headers=make_auth_headers(second_user)
        )
        assert res.status_code == 404
        assert res.json()["detail"] == f"Job '{job.id}' not found"

    async def test_cross_tenant_get_progress_returns_404(
        self, async_client, db_session, test_user, second_user, make_auth_headers
    ):
        job = await _make_job(db_session, owner_id=test_user.id)
        res = await async_client.get(
            f"/api/v1/forecast/{job.id}/progress", headers=make_auth_headers(second_user)
        )
        assert res.status_code == 404
        assert res.json()["detail"] == f"Job '{job.id}' not found"

    async def test_cross_tenant_stop_job_returns_404(
        self, async_client, db_session, test_user, second_user, make_auth_headers
    ):
        job = await _make_job(db_session, owner_id=test_user.id, status="pending")
        res = await async_client.delete(
            f"/api/v1/forecast/{job.id}", headers=make_auth_headers(second_user)
        )
        assert res.status_code == 404
        assert res.json()["detail"] == f"Job '{job.id}' not found"

    async def test_nonexistent_job_returns_identical_404(
        self, async_client, test_user, make_auth_headers
    ):
        """A job that never existed must 404 with the same shape as a foreign job."""
        fake_id = str(uuid.uuid4())
        res = await async_client.get(
            f"/api/v1/forecast/{fake_id}", headers=make_auth_headers(test_user)
        )
        assert res.status_code == 404
        assert res.json()["detail"] == f"Job '{fake_id}' not found"

    async def test_owner_can_get_own_job(
        self, async_client, db_session, test_user, make_auth_headers
    ):
        job = await _make_job(db_session, owner_id=test_user.id)
        res = await async_client.get(
            f"/api/v1/forecast/{job.id}", headers=make_auth_headers(test_user)
        )
        assert res.status_code == 200
        assert res.json()["job_id"] == job.id

    async def test_success_job_without_output_key_returns_no_results(
        self, async_client, db_session, test_user, make_auth_headers
    ):
        """Regression test for the code-review fix: a job with no job-scoped
        s3_output_key must never fall back to the shared global
        outputs/predictions/predictions_all.json file. That file is written
        by every job on the box (the F5 defect), so reading it here would
        leak another tenant's forecast output through this job's own,
        correctly-authorized job_id."""
        global_predictions_path = os.path.join(
            os.getcwd(), "outputs", "predictions", "predictions_all.json"
        )
        os.makedirs(os.path.dirname(global_predictions_path), exist_ok=True)
        with open(global_predictions_path, "w") as f:
            json.dump({"Sheet1": {"metrics": {"sales": {"records": [1, 2, 3]}}}}, f)

        job = await _make_job(db_session, owner_id=test_user.id, s3_output_key=None)
        res = await async_client.get(
            f"/api/v1/forecast/{job.id}", headers=make_auth_headers(test_user)
        )
        assert res.status_code == 200
        assert res.json()["results"] is None

    async def test_owner_can_stop_own_job(
        self, async_client, db_session, test_user, make_auth_headers
    ):
        job = await _make_job(db_session, owner_id=test_user.id, status="pending")
        res = await async_client.delete(
            f"/api/v1/forecast/{job.id}", headers=make_auth_headers(test_user)
        )
        assert res.status_code == 200

        # Soft-stop, not deletion: the row still exists with status="stopped".
        follow_up = await async_client.get(
            f"/api/v1/forecast/{job.id}", headers=make_auth_headers(test_user)
        )
        assert follow_up.status_code == 200
        assert follow_up.json()["status"] == "stopped"


class TestForecastAuthRequired:
    """Every forecast route must reject an unauthenticated caller with 401."""

    async def test_submit_forecast_requires_auth(self, async_client, mock_celery_delay):
        res = await async_client.post(
            "/api/v1/forecast",
            json={
                "upload_id": "does-not-matter",
                "selected_sheets": ["Sheet1"],
                "selected_metrics": ["sales"],
            },
        )
        assert res.status_code == 401
        assert len(mock_celery_delay) == 0

    async def test_get_job_requires_auth(self, async_client):
        res = await async_client.get(f"/api/v1/forecast/{uuid.uuid4()}")
        assert res.status_code == 401

    async def test_get_progress_requires_auth(self, async_client):
        res = await async_client.get(f"/api/v1/forecast/{uuid.uuid4()}/progress")
        assert res.status_code == 401

    async def test_stop_job_requires_auth(self, async_client):
        res = await async_client.delete(f"/api/v1/forecast/{uuid.uuid4()}")
        assert res.status_code == 401


class TestForecastSubmitRequiresAuth:
    """POST /forecast still works end-to-end once authenticated, and the
    created job is owned by the caller."""

    async def test_submit_forecast_with_auth_creates_owned_job(
        self, async_client, db_session, test_user, make_auth_headers, mock_celery_delay, s3_client
    ):
        upload_res = await async_client.post(
            "/api/v1/upload",
            files={"file": ("test.csv", _make_csv_bytes(), "text/csv")},
            headers=make_auth_headers(test_user),
        )
        assert upload_res.status_code == 201
        upload_id = upload_res.json()["upload_id"]

        res = await async_client.post(
            "/api/v1/forecast",
            headers=make_auth_headers(test_user),
            json={
                "upload_id": upload_id,
                "selected_sheets": ["Sheet1"],
                "selected_metrics": ["sales"],
            },
        )
        assert res.status_code == 202
        job_id = res.json()["job_id"]
        assert len(mock_celery_delay) == 1

        row = await db_session.get(ForecastJob, job_id)
        assert row is not None
        assert row.user_id == test_user.id
