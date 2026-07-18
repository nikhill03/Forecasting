"""
backend/tasks/celery_app.py
============================
Celery application factory.
Replaces the background daemon thread from Phase 1.

Start worker:
    celery -A backend.tasks.celery_app.celery_app worker --loglevel=info -Q forecasts
"""

from __future__ import annotations

from celery import Celery
from backend.core.config import settings

celery_app = Celery(
    "forecasting",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["backend.tasks.forecast_task"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    result_expires=86_400,
    task_max_retries=3,
    task_default_retry_delay=10,
    task_routes={
        "backend.tasks.forecast_task.run_forecast": {"queue": "forecasts"},
    },
)