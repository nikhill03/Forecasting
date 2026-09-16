"""
backend/api/routes/dashboard.py
================================
Dashboard home page aggregates (F15).

Endpoints:
    GET /api/v1/dashboard — the current user's run summary

A separate router rather than GET /forecast/dashboard: forecast.py's
/{job_id} routes would capture that literal path, and they don't validate the
id as a UUID, so a shadowed request reaches asyncpg and returns a 500.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.dependencies import get_current_user_id
from backend.models.schemas import DashboardSummary
from backend.services.dashboard import build_dashboard_summary

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("", response_model=DashboardSummary)
async def get_dashboard(
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> DashboardSummary:
    return await build_dashboard_summary(db, user_id)
