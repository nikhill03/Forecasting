"""
backend/tests/test_auth_rate_limit.py
========================================
Integration tests for F3 (auth-enforcement): POST /auth/login and
POST /auth/register are rate-limited by client IP, protecting them from
brute-force / mass-registration abuse.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from backend.core.config import settings
from backend.core.dependencies import limiter
from backend.core.database import get_db
from backend.main import app

RATE_LIMIT_N = int(settings.RATE_LIMIT_AUTH.split("/")[0])


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Every test starts with a clean limiter counter — the underlying
    storage is a process-wide singleton on app.state.limiter, shared
    across the whole test session otherwise."""
    limiter.reset()
    yield
    limiter.reset()


class TestLoginRateLimit:
    async def test_login_returns_429_after_limit_exceeded(self, async_client):
        for _ in range(RATE_LIMIT_N):
            res = await async_client.post(
                "/api/v1/auth/login",
                json={"email": "nobody@example.com", "password": "wrong-password"},
            )
            assert res.status_code != 429

        res = await async_client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "wrong-password"},
        )
        assert res.status_code == 429
        body = res.json()
        assert body["success"] is False
        assert "error" in body
        assert "detail" in body

    async def test_login_different_ip_not_rate_limited(self, async_client, db_session):
        for _ in range(RATE_LIMIT_N):
            res = await async_client.post(
                "/api/v1/auth/login",
                json={"email": "nobody@example.com", "password": "wrong-password"},
            )
            assert res.status_code != 429
        limited = await async_client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@example.com", "password": "wrong-password"},
        )
        assert limited.status_code == 429

        # A different client IP is not affected by the first IP's limit.
        async def _override_get_db():
            yield db_session

        app.dependency_overrides[get_db] = _override_get_db
        try:
            other_transport = ASGITransport(app=app, client=("10.0.0.9", 123))
            async with AsyncClient(
                transport=other_transport, base_url="http://testserver"
            ) as other_client:
                res = await other_client.post(
                    "/api/v1/auth/login",
                    json={"email": "nobody@example.com", "password": "wrong-password"},
                )
                assert res.status_code != 429
        finally:
            app.dependency_overrides.pop(get_db, None)


class TestRegisterRateLimit:
    async def test_register_returns_429_after_limit_exceeded(self, async_client):
        for _ in range(RATE_LIMIT_N):
            res = await async_client.post(
                "/api/v1/auth/register",
                json={
                    "email": f"{uuid.uuid4().hex}@example.com",
                    "password": "Passw0rd123",
                    "full_name": "Rate Limit Test",
                },
            )
            assert res.status_code != 429

        res = await async_client.post(
            "/api/v1/auth/register",
            json={
                "email": f"{uuid.uuid4().hex}@example.com",
                "password": "Passw0rd123",
                "full_name": "Rate Limit Test",
            },
        )
        assert res.status_code == 429
