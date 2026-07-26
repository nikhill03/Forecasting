"""
backend/tests/test_p2-durable-upload-storage.py
==================================================
Tests for F6 / p2-durable-upload-storage: the in-memory `_upload_store`
dict is replaced by a real `uploads` table + S3-backed file storage, and
the forecast-submit path passes Celery an S3 key instead of a base64
blob.

Written from `.claude/specs/p2-durable-upload-storage.md` — the API
Changes, Database Changes, Celery Tasks, and Definition of Done sections
— NOT from reading `upload.py` / `forecast.py` / `forecast_task.py`.
Assertions target the documented contract:

  * POST /api/v1/upload   — requires auth; persists an `Upload` row
    owned by the caller; returns `UploadResponse` (upload_id, file_name,
    s3_key, sheets, columns, row_counts, uploaded_at); no bytes retained
    in process memory after the response.
  * GET  /api/v1/upload/{id} — requires auth; owner-scoped
    (`Upload.id == id AND Upload.user_id == user_id`); 404 (never 403)
    for a foreign or nonexistent id — no existence oracle.
  * POST /api/v1/forecast — owner-scoped `Upload` lookup; 404 if the
    upload doesn't belong to the caller or doesn't exist (and no
    `ForecastJob` row is created in that case); populates
    `ForecastJob.s3_input_key` from the upload's stored key; dispatches
    the S3 key (not file bytes) to Celery.

Uses `async_client` (not the sync `client` fixture) throughout: these
routes are auth-required and DB-backed, and `client`'s own docstring in
conftest.py says it's unsuitable for that combination. `s3_client` (the
moto fixture) is required on every test that hits `POST /upload` because
conftest.py forces S3 env vars unconditionally, so the S3 code path
always fires in the test process. `mock_celery_delay` is mandatory for
every test that hits `POST /forecast` through `async_client` — see
conftest.py's fixture docstring for why (a real `apply_async`/eager
execution would write to the DB through a separate, non-rolled-back
psycopg2 connection and leak state across tests).
"""

from __future__ import annotations

import uuid
from functools import partial

import pytest
from sqlalchemy import select

from backend.core.config import settings
from backend.models.db_models import ForecastJob, Upload
from conftest import make_csv_bytes as _make_csv_bytes
from conftest import make_no_date_csv_bytes as _make_no_date_csv_bytes
from conftest import make_excel_bytes

_make_excel_bytes = partial(make_excel_bytes, rows=30)


async def _upload_csv(async_client, headers, s3_client, rows: int = 50) -> dict:
    """POST a valid CSV upload and return the parsed UploadResponse body."""
    res = await async_client.post(
        "/api/v1/upload",
        files={"file": ("test.csv", _make_csv_bytes(rows), "text/csv")},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()


def _forecast_payload(upload_id: str, **overrides) -> dict:
    payload = {
        "upload_id": upload_id,
        "selected_sheets": ["Sheet1"],
        "selected_metrics": ["sales"],
    }
    payload.update(overrides)
    return payload


# ══════════════════════════════════════════════════════════════════════
# POST /api/v1/upload
# ══════════════════════════════════════════════════════════════════════

class TestUploadCreateHappyPath:
    """POST /api/v1/upload — valid input contract per UploadResponse."""

    async def test_csv_upload_returns_201_with_full_response_shape(
        self, async_client, test_user, make_auth_headers, s3_client
    ):
        res = await async_client.post(
            "/api/v1/upload",
            files={"file": ("sales.csv", _make_csv_bytes(50), "text/csv")},
            headers=make_auth_headers(test_user),
        )
        assert res.status_code == 201
        body = res.json()

        # UploadResponse: upload_id, file_name, s3_key, sheets, columns,
        # row_counts, uploaded_at — all must be present.
        for field in ("upload_id", "file_name", "s3_key", "sheets", "columns",
                      "row_counts", "uploaded_at"):
            assert field in body, f"missing field {field!r} in UploadResponse"

        assert body["file_name"] == "sales.csv"
        assert "Sheet1" in body["sheets"]
        assert "date" in body["columns"]["Sheet1"]
        assert body["row_counts"]["Sheet1"] == 50

    async def test_excel_upload_accepted(
        self, async_client, test_user, make_auth_headers, s3_client
    ):
        res = await async_client.post(
            "/api/v1/upload",
            files={"file": (
                "sales.xlsx", _make_excel_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )},
            headers=make_auth_headers(test_user),
        )
        assert res.status_code == 201
        assert "upload_id" in res.json()

    async def test_upload_id_is_a_valid_identifier(
        self, async_client, test_user, make_auth_headers, s3_client
    ):
        body = await _upload_csv(async_client, make_auth_headers(test_user), s3_client)
        # Per the DB Changes section, `Upload.id` is a UUID primary key.
        uuid.UUID(body["upload_id"])


class TestUploadCreateAuth:
    async def test_upload_without_token_returns_401(self, async_client):
        res = await async_client.post(
            "/api/v1/upload",
            files={"file": ("test.csv", _make_csv_bytes(), "text/csv")},
        )
        assert res.status_code == 401

    async def test_upload_with_garbage_token_returns_401(self, async_client):
        res = await async_client.post(
            "/api/v1/upload",
            files={"file": ("test.csv", _make_csv_bytes(), "text/csv")},
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert res.status_code == 401


class TestUploadCreateValidation:
    async def test_unsupported_file_type_returns_415(
        self, async_client, test_user, make_auth_headers
    ):
        res = await async_client.post(
            "/api/v1/upload",
            files={"file": ("test.txt", b"just some plain text", "text/plain")},
            headers=make_auth_headers(test_user),
        )
        assert res.status_code == 415

    async def test_missing_date_column_returns_422_with_explanation(
        self, async_client, test_user, make_auth_headers
    ):
        res = await async_client.post(
            "/api/v1/upload",
            files={"file": ("nodate.csv", _make_no_date_csv_bytes(), "text/csv")},
            headers=make_auth_headers(test_user),
        )
        assert res.status_code == 422
        assert "date column" in res.json()["detail"].lower()

    async def test_oversized_file_returns_413(
        self, async_client, test_user, make_auth_headers
    ):
        # One byte over MAX_UPLOAD_SIZE_BYTES (default 50MB per
        # settings.MAX_UPLOAD_SIZE_MB) — CLAUDE.md's guardrails section:
        # "files over MAX_UPLOAD_SIZE_MB (default 50 MB) -> 413".
        oversized = b"a" * (settings.MAX_UPLOAD_SIZE_BYTES + 1)
        res = await async_client.post(
            "/api/v1/upload",
            files={"file": ("huge.csv", oversized, "text/csv")},
            headers=make_auth_headers(test_user),
        )
        assert res.status_code == 413

    async def test_missing_file_field_returns_422(
        self, async_client, test_user, make_auth_headers
    ):
        res = await async_client.post(
            "/api/v1/upload",
            headers=make_auth_headers(test_user),
        )
        assert res.status_code == 422


# ══════════════════════════════════════════════════════════════════════
# Database side effects of POST /api/v1/upload
# ══════════════════════════════════════════════════════════════════════

class TestUploadDbPersistence:
    """
    Per the spec's Overview: 'nothing about an upload ever reaches
    PostgreSQL' is exactly the defect being fixed. These tests assert an
    `Upload` row is durably persisted — independent of the response the
    route happened to return — matching the DB Changes table.
    """

    async def test_upload_creates_a_row_owned_by_the_caller(
        self, async_client, db_session, test_user, make_auth_headers, s3_client
    ):
        body = await _upload_csv(async_client, make_auth_headers(test_user), s3_client)

        row = await db_session.get(Upload, body["upload_id"])
        assert row is not None
        assert row.user_id == test_user.id
        assert row.file_name == "test.csv"
        assert row.sheets == body["sheets"]
        assert row.row_counts == body["row_counts"]
        assert row.file_size_bytes > 0

    async def test_upload_row_survives_independent_query(
        self, async_client, db_session, test_user, make_auth_headers, s3_client
    ):
        """
        Simulates the DoD's 'restart between upload and submit' scenario:
        a totally independent lookup (not reusing any object returned by
        the POST /upload call) must still find the row and its stored
        key, proving durability doesn't depend on in-process state.
        """
        body = await _upload_csv(async_client, make_auth_headers(test_user), s3_client)
        upload_id = body["upload_id"]

        result = await db_session.execute(select(Upload).where(Upload.id == upload_id))
        row = result.scalar_one_or_none()
        assert row is not None
        assert row.s3_key == body["s3_key"]

    async def test_no_file_bytes_leak_into_response(
        self, async_client, test_user, make_auth_headers, s3_client
    ):
        """
        Per 'Files to Change': confirm no `content` or other internal-only
        key (i.e. raw file bytes) ever leaves upload.py's route handlers.
        """
        body = await _upload_csv(async_client, make_auth_headers(test_user), s3_client)
        assert "content" not in body
        assert "file_content" not in body
        assert "file_content_b64" not in body


# ══════════════════════════════════════════════════════════════════════
# GET /api/v1/upload/{upload_id}
# ══════════════════════════════════════════════════════════════════════

class TestUploadRetrieveHappyPath:
    async def test_owner_can_retrieve_their_own_upload(
        self, async_client, test_user, make_auth_headers, s3_client
    ):
        headers = make_auth_headers(test_user)
        upload_body = await _upload_csv(async_client, headers, s3_client)

        res = await async_client.get(
            f"/api/v1/upload/{upload_body['upload_id']}", headers=headers
        )
        assert res.status_code == 200
        body = res.json()
        assert body["upload_id"] == upload_body["upload_id"]
        assert body["file_name"] == upload_body["file_name"]
        assert body["s3_key"] == upload_body["s3_key"]
        assert body["sheets"] == upload_body["sheets"]


class TestUploadRetrieveAuth:
    async def test_get_upload_without_token_returns_401(self, async_client):
        res = await async_client.get(f"/api/v1/upload/{uuid.uuid4()}")
        assert res.status_code == 401


class TestUploadRetrieveNotFound:
    async def test_nonexistent_upload_id_returns_404(
        self, async_client, test_user, make_auth_headers
    ):
        res = await async_client.get(
            f"/api/v1/upload/{uuid.uuid4()}", headers=make_auth_headers(test_user)
        )
        assert res.status_code == 404

    async def test_malformed_upload_id_returns_404_not_500(
        self, async_client, test_user, make_auth_headers
    ):
        """A non-UUID id must not blow up the query layer with a 500 —
        the spec treats 'missing or foreign' uniformly as 404."""
        res = await async_client.get(
            "/api/v1/upload/not-a-uuid-at-all", headers=make_auth_headers(test_user)
        )
        assert res.status_code == 404


class TestUploadOwnershipBoundary:
    """
    Per the spec's API Changes section: 'Returns 404 (not 403) for
    another user's upload — no existence oracle, matching the F3
    convention on forecast routes.'
    """

    async def test_foreign_upload_returns_404_not_403(
        self, async_client, test_user, second_user, make_auth_headers, s3_client
    ):
        owner_headers = make_auth_headers(test_user)
        upload_body = await _upload_csv(async_client, owner_headers, s3_client)

        res = await async_client.get(
            f"/api/v1/upload/{upload_body['upload_id']}",
            headers=make_auth_headers(second_user),
        )
        assert res.status_code == 404
        assert res.status_code != 403

    async def test_foreign_upload_404_body_matches_nonexistent_upload_404_body(
        self, async_client, test_user, second_user, make_auth_headers, s3_client
    ):
        """
        'No existence oracle' means a caller must not be able to
        distinguish 'exists but isn't yours' from 'doesn't exist' by
        inspecting the response.
        """
        owner_headers = make_auth_headers(test_user)
        upload_body = await _upload_csv(async_client, owner_headers, s3_client)

        foreign_res = await async_client.get(
            f"/api/v1/upload/{upload_body['upload_id']}",
            headers=make_auth_headers(second_user),
        )
        missing_res = await async_client.get(
            f"/api/v1/upload/{uuid.uuid4()}",
            headers=make_auth_headers(second_user),
        )
        assert foreign_res.status_code == missing_res.status_code == 404


# ══════════════════════════════════════════════════════════════════════
# POST /api/v1/forecast — ownership boundary on upload_id
# ══════════════════════════════════════════════════════════════════════

class TestForecastSubmitOwnership:
    """
    Per API Changes: submit_forecast looks up the Upload row owner-scoped
    by (upload_id, user_id); 404 if it doesn't belong to the caller or
    doesn't exist. Per Definition of Done: no ForecastJob row is created
    in that case.
    """

    async def test_submit_against_foreign_upload_returns_404(
        self, async_client, db_session, test_user, second_user,
        make_auth_headers, s3_client, mock_celery_delay,
    ):
        owner_headers = make_auth_headers(test_user)
        upload_body = await _upload_csv(async_client, owner_headers, s3_client)

        res = await async_client.post(
            "/api/v1/forecast",
            json=_forecast_payload(upload_body["upload_id"]),
            headers=make_auth_headers(second_user),
        )
        assert res.status_code == 404
        # No dispatch to Celery should have happened for a rejected submit.
        assert mock_celery_delay == []

    async def test_submit_against_foreign_upload_creates_no_forecast_job(
        self, async_client, db_session, test_user, second_user,
        make_auth_headers, s3_client, mock_celery_delay,
    ):
        owner_headers = make_auth_headers(test_user)
        upload_body = await _upload_csv(async_client, owner_headers, s3_client)

        jobs_before = (await db_session.execute(select(ForecastJob))).scalars().all()

        res = await async_client.post(
            "/api/v1/forecast",
            json=_forecast_payload(upload_body["upload_id"]),
            headers=make_auth_headers(second_user),
        )
        assert res.status_code == 404

        jobs_after = (await db_session.execute(select(ForecastJob))).scalars().all()
        assert len(jobs_after) == len(jobs_before)

    async def test_submit_against_nonexistent_upload_returns_404(
        self, async_client, test_user, make_auth_headers, mock_celery_delay
    ):
        res = await async_client.post(
            "/api/v1/forecast",
            json=_forecast_payload(str(uuid.uuid4())),
            headers=make_auth_headers(test_user),
        )
        assert res.status_code == 404
        assert mock_celery_delay == []

    async def test_submit_requires_auth(self, async_client, mock_celery_delay):
        res = await async_client.post(
            "/api/v1/forecast",
            json=_forecast_payload(str(uuid.uuid4())),
        )
        assert res.status_code == 401


# ══════════════════════════════════════════════════════════════════════
# POST /api/v1/forecast — happy path + DB side effects
# ══════════════════════════════════════════════════════════════════════

class TestForecastSubmitHappyPath:
    async def test_submit_with_owned_upload_returns_202(
        self, async_client, test_user, make_auth_headers, s3_client, mock_celery_delay
    ):
        headers = make_auth_headers(test_user)
        upload_body = await _upload_csv(async_client, headers, s3_client)

        res = await async_client.post(
            "/api/v1/forecast",
            json=_forecast_payload(upload_body["upload_id"]),
            headers=headers,
        )
        assert res.status_code == 202
        assert "job_id" in res.json()

    async def test_submit_populates_s3_input_key_from_upload(
        self, async_client, db_session, test_user, make_auth_headers,
        s3_client, mock_celery_delay,
    ):
        """
        Per Database Changes: 'this feature is what starts writing
        [ForecastJob.s3_input_key]' — sourced from the upload's stored
        key, not left null.
        """
        headers = make_auth_headers(test_user)
        upload_body = await _upload_csv(async_client, headers, s3_client)

        res = await async_client.post(
            "/api/v1/forecast",
            json=_forecast_payload(upload_body["upload_id"]),
            headers=headers,
        )
        assert res.status_code == 202
        job_id = res.json()["job_id"]

        job = await db_session.get(ForecastJob, job_id)
        assert job is not None
        assert job.s3_input_key is not None
        assert job.s3_input_key == upload_body["s3_key"]
        assert job.user_id == test_user.id


class TestForecastSubmitCeleryDispatch:
    """
    Per the Definition of Done: dispatch args to run_forecast.apply_async
    contain a key string, not a base64 payload — the whole point of this
    feature is that a 50MB upload never becomes a ~67MB Celery message.
    """

    async def test_dispatch_args_carry_a_short_key_not_a_file_blob(
        self, async_client, test_user, make_auth_headers, s3_client, mock_celery_delay
    ):
        headers = make_auth_headers(test_user)
        upload_body = await _upload_csv(async_client, headers, s3_client, rows=200)
        expected_key = upload_body["s3_key"]

        res = await async_client.post(
            "/api/v1/forecast",
            json=_forecast_payload(upload_body["upload_id"]),
            headers=headers,
        )
        assert res.status_code == 202
        assert len(mock_celery_delay) == 1

        dispatched_args = mock_celery_delay[0]["args"]
        # The dispatched positional args must contain the S3 key exactly
        # as returned by the upload response...
        assert expected_key in dispatched_args
        # ...and must NOT contain anything resembling the base64-encoded
        # file content that the pre-fix implementation put on the wire.
        # A 200-row CSV base64-encoded would be well over a thousand
        # characters; every dispatched arg here must be short.
        for arg in dispatched_args:
            if isinstance(arg, str):
                assert len(arg) < 200, (
                    "a dispatched Celery arg looks like a large encoded "
                    "blob, not a short storage key"
                )

    async def test_dispatch_args_do_not_contain_raw_csv_content(
        self, async_client, test_user, make_auth_headers, s3_client, mock_celery_delay
    ):
        headers = make_auth_headers(test_user)
        csv_bytes = _make_csv_bytes(50)
        upload_res = await async_client.post(
            "/api/v1/upload",
            files={"file": ("test.csv", csv_bytes, "text/csv")},
            headers=headers,
        )
        upload_id = upload_res.json()["upload_id"]

        res = await async_client.post(
            "/api/v1/forecast",
            json=_forecast_payload(upload_id),
            headers=headers,
        )
        assert res.status_code == 202

        dispatched_args = mock_celery_delay[0]["args"]
        for arg in dispatched_args:
            if isinstance(arg, (bytes, bytearray)):
                pytest.fail("raw file bytes were dispatched to Celery")
            if isinstance(arg, str):
                assert "date,sales,units" not in arg  # CSV header, if leaked raw
