"""
conftest.py (repo root)
========================
Backend test-suite fixtures.

Root-level placement is REQUIRED (not `tests/conftest.py` or
`backend/tests/conftest.py`) — pytest only auto-loads conftest.py files
from directories on the ancestor chain of `testpaths` (backend/tests ->
backend -> repo root, per pytest.ini). A sibling `tests/` directory is
never on that chain and would silently not apply to backend/tests/*.py.
See backend/CLAUDE.md Testing section for the full explanation.

Section 1 below MUST run before the first `import backend.*` anywhere
in this file. `backend.core.config.settings` is a module-level
singleton instantiated the instant `backend.core.config` is imported;
dozens of modules do `from backend.core.config import settings` and
keep that object by reference, so there is no way to retroactively
override it once created — the only reliable way to avoid needing a
real `.env` file present is to set the required environment variables
before that first import happens.
"""

from __future__ import annotations

import os

from sqlalchemy.engine import make_url  # third-party, safe before backend.* imports

# ── 1. Environment — MUST precede any `backend.*` import ──────────────
os.environ.setdefault("APP_ENV", "test")
# Test-only signing key. Never imported by production code as things
# stand (only backend.main -> ... -> backend.core.config are ever
# imported by the app itself, never this file) — but if this same
# env-injection pattern is ever reused to stand up a network-reachable
# instance (a CI "test-deploy", a review app), give it its own
# SECRET_KEY. This one is committed to git and forgeable by anyone who
# can read the repo.
os.environ.setdefault(
    "SECRET_KEY", "test-only-secret-key-do-not-use-in-prod-0123456789"
)

_TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://forecasting:forecasting_dev@localhost:5432/dmc_test",
)
os.environ["TEST_DATABASE_URL"] = _TEST_DB_URL
os.environ["DATABASE_URL"]      = _TEST_DB_URL  # binds backend.core.database.engine at import time

# Refuse to run schema create_all/drop_all against anything that isn't
# obviously a disposable test database. Without this, a misconfigured
# TEST_DATABASE_URL (a copy-pasted staging URL, a CI secret pointed at
# the wrong env, TEST_DATABASE_URL accidentally equal to DATABASE_URL)
# doesn't just risk polluting a shared DB — the _engine fixture below
# DROPS EVERY TABLE in it at session teardown.
_test_db_name = make_url(_TEST_DB_URL).database or ""
if "test" not in _test_db_name.lower():
    raise RuntimeError(
        f"Refusing to run schema create_all/drop_all against database "
        f"{_test_db_name!r} — TEST_DATABASE_URL must point at a database "
        f"with 'test' in its name."
    )

os.environ.setdefault("CELERY_BROKER_URL",     "memory://")
os.environ.setdefault("CELERY_RESULT_BACKEND", "cache+memory://")
# slowapi's Limiter (backend.core.dependencies.limiter) is constructed at
# backend.main import time with storage_uri=settings.REDIS_URL. Default to
# an in-memory store so the test session never depends on a real Redis
# instance being reachable; setdefault lets a developer still point at real
# Redis locally by exporting REDIS_URL before running pytest.
os.environ.setdefault("REDIS_URL", "memory://")
# Forced, not setdefault: if a developer's shell already exports real
# AWS credentials (common for anyone doing manual aws-cli work), those
# must never flow into settings.AWS_* during a test run — moto's
# mock_aws() happens to intercept regardless of which credentials are
# configured, but that's incidental, not something to depend on.
os.environ["AWS_ACCESS_KEY_ID"]     = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
os.environ["AWS_DEFAULT_REGION"]    = "us-east-1"
os.environ["S3_BUCKET_NAME"]        = "dmc-test-bucket"

# ── 2. Now safe to import backend.* and third-party test deps ─────────
import io
import uuid
from typing import AsyncGenerator, Iterator

import boto3
import pandas as pd
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from moto import mock_aws
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import Base, get_db
from backend.core.security import create_access_token, hash_password
from backend.main import app
from backend.models.db_models import User
from backend.tasks.celery_app import celery_app

# ── 3. Celery: synchronous in-process execution for the whole session ──
# forecast.py:137 dispatches via run_forecast.apply_async(...), not
# .delay() — task_always_eager makes both honour eager execution
# transparently. Tests that need to assert dispatch *args* instead of
# running the task body use the mock_celery_delay fixture below, which
# patches apply_async directly and bypasses eager mode entirely.
#
# IMPORTANT — mock_celery_delay is MANDATORY, not optional, for any
# test that calls POST /forecast through async_client. forecast.py only
# flush()es the ForecastJob row before dispatching, it doesn't commit.
# With task_always_eager, run_forecast executes synchronously in this
# same process — but forecast_task.py updates the DB via a SEPARATE
# psycopg2 connection (by design, to avoid the asyncpg/fork conflict),
# which cannot see the uncommitted row sitting in db_session's SAVEPOINT
# transaction, and whose own writes are real, autocommitted, and NOT
# rolled back by db_session's teardown. Any test hitting POST /forecast
# without mock_celery_delay will leak state across tests. Use
# mock_celery_delay to intercept dispatch instead of letting it run.
celery_app.conf.task_always_eager    = True
celery_app.conf.task_eager_propagates = True


# ── 3b. Shared upload-fixture-file builders ─────────────────────────────
# Plain functions, not fixtures — same rationale as auth_headers() below:
# callers need different row counts / column shapes within a single test.
# Previously duplicated near-identically across test_upload_api.py,
# test_forecast_auth.py, and test_p2-durable-upload-storage.py.
def make_csv_bytes(rows: int = 50, **extra_columns) -> bytes:
    """Minimal valid CSV with a date column. Defaults to sales/units
    columns; pass explicit column=range(...) kwargs to override."""
    dates = pd.date_range("2023-01-01", periods=rows, freq="D")
    data: dict = {"date": dates}
    data.update(extra_columns or {"sales": range(rows), "units": range(rows, rows * 2)})
    df = pd.DataFrame(data)
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


def make_excel_bytes(rows: int = 50, column: str = "revenue") -> bytes:
    """Minimal valid Excel file with a date column."""
    dates = pd.date_range("2023-01-01", periods=rows, freq="D")
    df = pd.DataFrame({"date": dates, column: range(rows)})
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


def make_no_date_csv_bytes(rows: int = 10) -> bytes:
    """A CSV with no plausible date column — should fail upload validation."""
    df = pd.DataFrame({"sales": range(rows), "units": range(rows)})
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


# ── 4. Session-scoped engine + schema ───────────────────────────────────
@pytest_asyncio.fixture(scope="session")
async def _engine():
    """
    Reuses backend.core.database.engine directly — it was already built
    from settings.DATABASE_URL, which section 1 above pointed at
    TEST_DATABASE_URL, so there's no second parallel engine to keep in
    sync. Schema is created via Base.metadata.create_all() against real
    Postgres (required for UUID/JSONB columns — SQLite has no
    equivalent) and dropped at session end.
    """
    from backend.core.database import engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ── 5. Function-scoped db_session: SAVEPOINT-per-test rollback ─────────
@pytest_asyncio.fixture
async def db_session(_engine) -> AsyncGenerator[AsyncSession, None]:
    """
    One outer, connection-level transaction per test, always rolled
    back at teardown — regardless of how many times application code
    (e.g. backend/core/database.get_db) calls `await session.commit()`
    internally.

    Uses SQLAlchemy 2.0's join_transaction_mode="create_savepoint":
    because the outer transaction is opened manually here via
    conn.begin() (not by the Session), every session.commit() called by
    app code only commits a SAVEPOINT that SQLAlchemy opened
    underneath, then immediately reopens a fresh SAVEPOINT for further
    work. The connection-level transaction itself is only ever rolled
    back, never committed — nothing a test does is visible outside it.
    """
    async with _engine.connect() as conn:
        await conn.begin()
        session = AsyncSession(
            bind=conn,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )
        try:
            yield session
        finally:
            await session.close()
            await conn.rollback()


# ── 6. async_client — PRIMARY fixture for DB-backed integration tests ──
@pytest_asyncio.fixture
async def async_client(db_session) -> AsyncGenerator[AsyncClient, None]:
    """
    Runs the ASGI app in-process on the SAME event loop as the calling
    test coroutine (httpx ASGITransport, no thread/portal), so it is
    safe to share db_session's asyncpg connection with it. Use this
    (not `client`) for anything that needs both an HTTP call AND
    transactional isolation — dual-user auth tests, cross-tenant tests,
    the refresh-token-as-bearer-token regression test, etc.
    """
    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(get_db, None)


# ── 7. client — sync TestClient, DB-agnostic routes only ───────────────
@pytest.fixture
def client(_engine) -> Iterator[TestClient]:
    """
    Kept for existing sync-style tests (backend/tests/test_upload_api.py).

    starlette's TestClient runs the app on a SEPARATE thread with its
    own event loop (anyio.from_thread.start_blocking_portal). Sharing
    db_session's asyncpg connection (opened on pytest-asyncio's loop)
    across that boundary raises "attached to a different loop". So this
    fixture does NOT reuse db_session: it hands out a fresh AsyncSession
    bound to the shared test engine on every call, with production-like
    commit/rollback semantics (safe because it all runs inside the
    portal's own loop).

    Consequence: writes made via `client` are NOT rolled back between
    tests. None of the routes currently exercised by `client`
    (upload.py) touch the DB, so this is safe today. Any NEW test that
    needs both an HTTP call and rollback isolation MUST use
    `async_client`, not this.
    """
    async def _override_get_db():
        async with AsyncSession(bind=_engine, expire_on_commit=False) as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)


# ── 8. User factory + auth fixtures ─────────────────────────────────────
@pytest_asyncio.fixture
async def user_factory(db_session):
    """
    Async factory fixture: `user = await user_factory(email="a@b.com")`.
    Creates a User row directly via the ORM (bypassing /auth/register),
    inside the same SAVEPOINT-scoped db_session as async_client, so it's
    visible to requests made through async_client in the same test and
    rolled back at teardown.
    """

    async def _make(
        email: str | None = None,
        password: str = "TestPassw0rd!",
        full_name: str = "Test User",
        is_active: bool = True,
    ) -> User:
        user = User(
            email=(email or f"{uuid.uuid4().hex}@example.com").lower(),
            password_hash=hash_password(password),
            full_name=full_name,
            is_active=is_active,
        )
        db_session.add(user)
        await db_session.flush()
        return user

    return _make


@pytest_asyncio.fixture
async def test_user(user_factory) -> User:
    return await user_factory()


@pytest_asyncio.fixture
async def second_user(user_factory) -> User:
    """A second, distinct user for cross-tenant / negative-auth tests."""
    return await user_factory()


def auth_headers(user: User) -> dict[str, str]:
    """
    Plain function, not a fixture — callers need headers for *different*
    users within one test (e.g. F3's "user B requests user A's job ->
    404"), which a zero-arg fixture can't express. Importable directly
    or via the `make_auth_headers` fixture wrapper below.
    """
    token = create_access_token(subject=user.id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def make_auth_headers():
    """Fixture wrapper around auth_headers(), for injection-style tests."""
    return auth_headers


# ── 9. mock_celery_delay ────────────────────────────────────────────────
@pytest.fixture
def mock_celery_delay(monkeypatch):
    """
    Named `mock_celery_delay` for parity with the spec's DoD checklist
    wording, but patches `run_forecast.apply_async` — NOT `.delay` —
    because backend/api/routes/forecast.py:137 calls
    `run_forecast.apply_async(args=[...], queue="forecasts")`, not
    `.delay(...)`. Captures dispatch args without invoking the task
    body or touching Celery's broker at all (bypasses task_always_eager
    too, since it never calls the real apply_async).

    Returns the list of captured calls: `mock_celery_delay[0]["args"]`.
    """
    from backend.tasks.forecast_task import run_forecast

    calls: list[dict] = []

    class _FakeAsyncResult:
        id = "fake-task-id"

    def _fake_apply_async(args=None, kwargs=None, **opts):
        calls.append({"args": args, "kwargs": kwargs, **opts})
        return _FakeAsyncResult()

    monkeypatch.setattr(run_forecast, "apply_async", _fake_apply_async)
    return calls


# ── 10. S3 / moto fixture ───────────────────────────────────────────────
@pytest.fixture
def s3_client():
    """
    In-memory S3 via moto's mock_aws context manager, pre-seeded with
    settings.S3_BUCKET_NAME so backend/storage/s3_client.py (which reads
    settings.S3_BUCKET_NAME / AWS_* at call time via _get_client()) hits
    the mock transparently — no code change needed in s3_client.py.
    Yields a boto3 S3 client for tests to assert against directly.
    """
    with mock_aws():
        s3 = boto3.client("s3", region_name=settings.AWS_DEFAULT_REGION)
        if settings.AWS_DEFAULT_REGION == "us-east-1":
            s3.create_bucket(Bucket=settings.S3_BUCKET_NAME)
        else:
            s3.create_bucket(
                Bucket=settings.S3_BUCKET_NAME,
                CreateBucketConfiguration={
                    "LocationConstraint": settings.AWS_DEFAULT_REGION
                },
            )
        yield s3


# ── 11. fake_redis — autouse per-job stop-key fake ──────────────────────
class _FakeRedis:
    """
    Minimal in-memory stand-in for redis-py's Redis client, covering only
    the .exists/.set/.delete surface F5's per-job stop key needs.
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value

    def exists(self, key: str) -> bool:
        return key in self._store

    def delete(self, key: str) -> None:
        self._store.pop(key, None)


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    """
    Autouse so every test gets a working, inspectable fake instead of a
    real redis.Redis construction attempt against REDIS_URL=memory://
    (which redis-py cannot parse and would raise). Patches the
    _get_redis_client() getter in both modules that own one —
    backend.api.routes.forecast (writes the stop key on DELETE) and
    services.processing_engine (reads it during processing_worker) — so a
    write in one and a read in the other see the same store within a test.
    """
    import backend.api.routes.forecast as forecast_module
    import services.processing_engine as processing_engine_module

    fake = _FakeRedis()
    monkeypatch.setattr(forecast_module, "_get_redis_client", lambda *a, **k: fake)
    monkeypatch.setattr(processing_engine_module, "_get_redis_client", lambda *a, **k: fake)
    return fake
