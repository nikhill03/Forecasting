"""
backend/tests/test_conftest_fixtures.py
=========================================
Smoke tests proving the test harness itself works. If these fail,
don't trust any other test in the suite.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.security import create_refresh_token, hash_password
from backend.models.db_models import User


class TestDbSessionIsolation:
    """
    DoD: a row inserted in one test's db_session is not visible outside
    that test. Proven within a single test rather than via two tests
    that rely on pytest's declaration order — that ordering assumption
    would silently stop proving anything the moment a test-randomization
    plugin is introduced. Instead, this replicates what two independent
    tests' db_session fixtures each do (open connection, SAVEPOINT,
    rollback) directly against `_engine`.
    """

    async def test_savepoint_rollback_hides_row_from_next_transaction(self, _engine):
        email = f"isolation-check-{uuid.uuid4().hex}@example.com"

        # "Test 1": insert a row, then roll back — mirrors db_session's teardown.
        async with _engine.connect() as conn:
            await conn.begin()
            session = AsyncSession(
                bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
            )
            session.add(User(email=email, password_hash=hash_password("x"), full_name="Iso Check"))
            await session.flush()
            result = await session.execute(select(User).where(User.email == email))
            assert result.scalar_one_or_none() is not None  # visible within its own transaction
            await session.close()
            await conn.rollback()

        # "Test 2": a fresh connection/transaction — must not see test 1's row.
        async with _engine.connect() as conn:
            await conn.begin()
            session = AsyncSession(
                bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
            )
            result = await session.execute(select(User).where(User.email == email))
            assert result.scalar_one_or_none() is None
            await session.close()
            await conn.rollback()


class TestDualAuthenticatedClients:
    """DoD: two authenticated clients for two different users in one test."""

    async def test_two_users_have_distinct_valid_tokens(
        self, async_client, test_user, second_user, make_auth_headers
    ):
        headers_a = make_auth_headers(test_user)
        headers_b = make_auth_headers(second_user)
        assert headers_a != headers_b

        res_a = await async_client.get("/api/v1/auth/me", headers=headers_a)
        res_b = await async_client.get("/api/v1/auth/me", headers=headers_b)

        assert res_a.status_code == 200
        assert res_b.status_code == 200
        assert res_a.json()["email"] != res_b.json()["email"]
        assert res_a.json()["email"] == test_user.email
        assert res_b.json()["email"] == second_user.email


class TestRefreshTokenRejectedAsBearer:
    """
    F1 regression: decode_token's type-claim check must reject a
    refresh token presented as a Bearer access token on a protected route.
    """

    async def test_refresh_token_as_bearer_returns_401(self, async_client, test_user):
        refresh_token = create_refresh_token(subject=test_user.id)
        res = await async_client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {refresh_token}"},
        )
        assert res.status_code == 401


class TestS3Fixture:
    """DoD: moto put_object/get_object round-trip, no real AWS calls."""

    def test_put_get_round_trip(self, s3_client):
        s3_client.put_object(Bucket=settings.S3_BUCKET_NAME, Key="k.txt", Body=b"hello")
        body = s3_client.get_object(Bucket=settings.S3_BUCKET_NAME, Key="k.txt")["Body"].read()
        assert body == b"hello"


class TestMockCeleryDelay:
    """DoD: mock_celery_delay captures dispatch args, task body never runs."""

    def test_captures_args_without_running_task(self, mock_celery_delay):
        from backend.tasks.forecast_task import run_forecast

        task = run_forecast.apply_async(
            args=["job-1", "ZmFrZQ==", {"selected_sheets": []}], queue="forecasts"
        )

        assert len(mock_celery_delay) == 1
        assert mock_celery_delay[0]["args"] == ["job-1", "ZmFrZQ==", {"selected_sheets": []}]
        assert task.id == "fake-task-id"
