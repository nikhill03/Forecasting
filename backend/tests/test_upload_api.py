"""
backend/tests/test_upload_api.py
==================================
Integration tests for POST/GET /api/v1/upload and the upload-ownership
boundary enforced on POST /api/v1/forecast.

Uses async_client (not the sync `client` fixture) because these routes now
require auth and persist to the DB via the injected AsyncSession — the
`client` fixture's own docstring in conftest.py says it's only safe for
DB-agnostic routes, which upload.py no longer is. The `s3_client` moto
fixture is required on every test that hits POST /upload: conftest.py
forces S3_BUCKET_NAME/AWS_* env vars unconditionally, so the S3 branch in
upload.py always fires in the test process.
"""

from __future__ import annotations

from sqlalchemy import select

from backend.models.db_models import ForecastJob
from conftest import make_csv_bytes as _make_csv_bytes
from conftest import make_excel_bytes as _make_excel_bytes
from conftest import make_no_date_csv_bytes as _make_no_date_csv_bytes


class TestUploadEndpoint:

    async def test_health_check(self, async_client):
        res = await async_client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "healthy"

    async def test_upload_csv_success(self, async_client, test_user, make_auth_headers, s3_client):
        csv_bytes = _make_csv_bytes()
        res = await async_client.post(
            "/api/v1/upload",
            files={"file": ("test.csv", csv_bytes, "text/csv")},
            headers=make_auth_headers(test_user),
        )
        assert res.status_code == 201
        data = res.json()
        assert "upload_id" in data
        assert "Sheet1" in data["sheets"]
        assert "date" in data["columns"]["Sheet1"]
        assert data["row_counts"]["Sheet1"] == 50

    async def test_upload_excel_success(self, async_client, test_user, make_auth_headers, s3_client):
        xlsx_bytes = _make_excel_bytes()
        res = await async_client.post(
            "/api/v1/upload",
            files={"file": ("test.xlsx", xlsx_bytes,
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=make_auth_headers(test_user),
        )
        assert res.status_code == 201
        data = res.json()
        assert "upload_id" in data

    async def test_upload_unsupported_type(self, async_client, test_user, make_auth_headers):
        res = await async_client.post(
            "/api/v1/upload",
            files={"file": ("test.txt", b"some text", "text/plain")},
            headers=make_auth_headers(test_user),
        )
        assert res.status_code == 415

    async def test_upload_no_date_column(self, async_client, test_user, make_auth_headers):
        res = await async_client.post(
            "/api/v1/upload",
            files={"file": ("nodate.csv", _make_no_date_csv_bytes(), "text/csv")},
            headers=make_auth_headers(test_user),
        )
        assert res.status_code == 422
        assert "date column" in res.json()["detail"].lower()

    async def test_get_upload_metadata(self, async_client, test_user, make_auth_headers, s3_client):
        headers = make_auth_headers(test_user)
        csv_bytes = _make_csv_bytes()
        upload_res = await async_client.post(
            "/api/v1/upload",
            files={"file": ("test.csv", csv_bytes, "text/csv")},
            headers=headers,
        )
        upload_id = upload_res.json()["upload_id"]

        get_res = await async_client.get(f"/api/v1/upload/{upload_id}", headers=headers)
        assert get_res.status_code == 200
        assert get_res.json()["upload_id"] == upload_id

    async def test_get_nonexistent_upload(self, async_client, test_user, make_auth_headers):
        res = await async_client.get(
            "/api/v1/upload/nonexistent-id", headers=make_auth_headers(test_user)
        )
        assert res.status_code == 404

    async def test_upload_requires_auth(self, async_client):
        res = await async_client.post(
            "/api/v1/upload",
            files={"file": ("test.csv", _make_csv_bytes(), "text/csv")},
        )
        assert res.status_code == 401

    async def test_get_upload_requires_auth(self, async_client):
        res = await async_client.get("/api/v1/upload/some-id")
        assert res.status_code == 401


class TestUploadOwnership:

    async def test_cross_tenant_get_upload_returns_404(
        self, async_client, test_user, second_user, make_auth_headers, s3_client
    ):
        csv_bytes = _make_csv_bytes()
        upload_res = await async_client.post(
            "/api/v1/upload",
            files={"file": ("test.csv", csv_bytes, "text/csv")},
            headers=make_auth_headers(test_user),
        )
        upload_id = upload_res.json()["upload_id"]

        res = await async_client.get(
            f"/api/v1/upload/{upload_id}", headers=make_auth_headers(second_user)
        )
        assert res.status_code == 404

    async def test_forecast_submit_against_foreign_upload_returns_404(
        self, async_client, db_session, test_user, second_user, make_auth_headers, s3_client
    ):
        csv_bytes = _make_csv_bytes()
        upload_res = await async_client.post(
            "/api/v1/upload",
            files={"file": ("test.csv", csv_bytes, "text/csv")},
            headers=make_auth_headers(test_user),
        )
        upload_id = upload_res.json()["upload_id"]

        jobs_before = (await db_session.execute(select(ForecastJob))).scalars().all()

        res = await async_client.post(
            "/api/v1/forecast",
            json={
                "upload_id": upload_id,
                "selected_sheets": ["Sheet1"],
                "selected_metrics": ["sales"],
            },
            headers=make_auth_headers(second_user),
        )
        assert res.status_code == 404

        jobs_after = (await db_session.execute(select(ForecastJob))).scalars().all()
        assert len(jobs_after) == len(jobs_before)

    async def test_forecast_submit_no_base64_on_celery_wire(
        self, async_client, test_user, make_auth_headers, s3_client, mock_celery_delay
    ):
        headers = make_auth_headers(test_user)
        csv_bytes = _make_csv_bytes()
        upload_res = await async_client.post(
            "/api/v1/upload",
            files={"file": ("test.csv", csv_bytes, "text/csv")},
            headers=headers,
        )
        upload_body = upload_res.json()
        upload_id = upload_body["upload_id"]
        expected_s3_key = upload_body["s3_key"]

        res = await async_client.post(
            "/api/v1/forecast",
            json={
                "upload_id": upload_id,
                "selected_sheets": ["Sheet1"],
                "selected_metrics": ["sales"],
            },
            headers=headers,
        )
        assert res.status_code == 202

        assert len(mock_celery_delay) == 1
        dispatched_key = mock_celery_delay[0]["args"][1]
        assert dispatched_key == expected_s3_key
        # A base64-encoded 50-row CSV would be well over a thousand
        # characters; a storage key is short. This is the "no base64 blob
        # on the Celery wire" assertion.
        assert len(dispatched_key) < 200


class TestUploadFilenameSanitization:
    """Regression coverage for the path-traversal fix: filename is
    client-supplied and previously flowed unsanitized into both the local
    fallback's os.path.join and the S3 key string."""

    async def test_relative_traversal_filename_rejected(
        self, async_client, test_user, make_auth_headers, s3_client
    ):
        res = await async_client.post(
            "/api/v1/upload",
            files={"file": ("../../../../tmp/evil.csv", _make_csv_bytes(), "text/csv")},
            headers=make_auth_headers(test_user),
        )
        assert res.status_code == 422

    async def test_absolute_path_filename_rejected(
        self, async_client, test_user, make_auth_headers, s3_client
    ):
        res = await async_client.post(
            "/api/v1/upload",
            files={"file": ("/tmp/evil.csv", _make_csv_bytes(), "text/csv")},
            headers=make_auth_headers(test_user),
        )
        assert res.status_code == 422

    async def test_traversal_filename_rejected_on_local_fallback_path(
        self, async_client, test_user, make_auth_headers, monkeypatch, tmp_path
    ):
        """Same check on the local-storage branch (S3 not configured),
        where an unsanitized filename would previously write outside
        outputs/uploads/{upload_id}/ via os.path.join's absolute-path
        override behavior. monkeypatch the storage root to a throwaway
        tmp_path so a false-negative here can't silently write into the
        real repo tree even if the fix regresses."""
        import backend.api.routes.upload as upload_module
        from backend.core.config import settings as app_settings

        monkeypatch.setattr(upload_module, "_LOCAL_STORAGE_ROOT", str(tmp_path))
        monkeypatch.setattr(app_settings, "S3_BUCKET_NAME", "")

        res = await async_client.post(
            "/api/v1/upload",
            files={"file": ("../evil.csv", _make_csv_bytes(), "text/csv")},
            headers=make_auth_headers(test_user),
        )
        assert res.status_code == 422
        # Confirm nothing was written anywhere under tmp_path's parent —
        # the rejection must happen before any filesystem write is attempted.
        assert list(tmp_path.iterdir()) == []
