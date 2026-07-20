"""
backend/main.py
================
FastAPI application factory.
Replaces: app.py (Dash application entry point)

Run with:
    uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded

from backend.core.config import settings
from backend.core.dependencies import limiter
from backend.api.routes import auth, forecast, upload

# ── Structured logging setup ─────────────────────────────────────
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer()
        if settings.is_production
        else structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger("forecasting.main")


# ── Lifespan (startup / shutdown) ─────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Runs on startup and shutdown.
    Phase 2: initialise DB connection pool, Redis, Celery here.
    """
    logger.info(
        "Starting Forecasting Platform",
        env=settings.APP_ENV,
        version="2.0.0",
    )
    yield
    logger.info("Shutting down Forecasting Platform")


# ── App factory ───────────────────────────────────────────────────
def create_app() -> FastAPI:
    app = FastAPI(
        title       = settings.PROJECT_NAME,
        description = (
            "ML-powered time-series forecasting API. "
            "Supports univariate and multivariate demand forecasting "
            "with automatic model selection."
        ),
        version     = "2.0.0",
        docs_url    = "/docs" if not settings.is_production else None,
        redoc_url   = "/redoc" if not settings.is_production else None,
        lifespan    = lifespan,
    )

    # ── Rate limiting ────────────────────────────────────────────
    app.state.limiter = limiter

    # ── CORS ─────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins     = settings.CORS_ORIGINS,
        allow_credentials = True,
        allow_methods     = ["*"],
        allow_headers     = ["*"],
    )

    # ── Request logging middleware ─────────────────────────────────
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start  = time.perf_counter()
        response = await call_next(request)
        duration = (time.perf_counter() - start) * 1000

        logger.info(
            "http_request",
            method   = request.method,
            path     = request.url.path,
            status   = response.status_code,
            duration_ms = round(duration, 2),
        )
        return response

    # ── Global exception handler ───────────────────────────────────
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(
            "unhandled_exception",
            path  = request.url.path,
            error = str(exc),
            exc_info=True,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": "Internal server error"},
        )

    # ── Rate limit exceeded handler ────────────────────────────────
    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "success": False,
                "error"  : "Too many requests",
                "detail" : str(exc.detail),
            },
        )

    # ── Health check ──────────────────────────────────────────────
    @app.get("/health", tags=["health"], summary="Health check")
    async def health():
        return {
            "status" : "healthy",
            "env"    : settings.APP_ENV,
            "version": "2.0.0",
        }

    # ── Register routers ──────────────────────────────────────────
    prefix = settings.API_V1_PREFIX  # /api/v1

    app.include_router(auth.router,     prefix=prefix)
    app.include_router(upload.router,   prefix=prefix)
    app.include_router(forecast.router, prefix=prefix)

    return app


# ── Entry point ───────────────────────────────────────────────────
app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host   = settings.APP_HOST,
        port   = settings.APP_PORT,
        reload = settings.is_development,
    )