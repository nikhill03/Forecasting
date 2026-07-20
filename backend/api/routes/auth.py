"""
backend/api/routes/auth.py
===========================
Authentication endpoints — shell scaffolded in Phase 1,
fully implemented in Phase 2 with PostgreSQL user store.

Endpoints:
    POST /api/v1/auth/register  — create new user account
    POST /api/v1/auth/login     — login, receive JWT tokens
    POST /api/v1/auth/refresh   — exchange refresh token for new access token
    POST /api/v1/auth/logout    — invalidate refresh token
    GET  /api/v1/auth/me        — get current user profile
"""

from __future__ import annotations

from pydantic import BaseModel
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.dependencies import get_current_user_id, limiter
from backend.models.schemas import (
    SuccessResponse,
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)
from backend.services.auth_service import (
    get_user_by_id,
    login_user,
    refresh_tokens,
    register_user,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class RefreshTokenRequest(BaseModel):
    refresh_token: str


@router.post("/register", response_model=TokenResponse, status_code=201)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def register(
    payload: UserRegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Create a new account. Auto-logs in on success."""
    return await register_user(payload, db)


@router.post("/login", response_model=TokenResponse)
@limiter.limit(settings.RATE_LIMIT_AUTH)
async def login(
    payload: UserLoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Login with email + password. Returns access + refresh tokens."""
    return await login_user(payload, db)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    """Exchange refresh token for new token pair."""
    return await refresh_tokens(request.refresh_token, db)


@router.post("/logout", response_model=SuccessResponse)
async def logout(
    _user_id: str = Depends(get_current_user_id),
) -> SuccessResponse:
    """Logout. Phase 3 will blacklist token in Redis."""
    return SuccessResponse(message="Logged out successfully.")


@router.get("/me", response_model=UserResponse)
async def get_me(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Return authenticated user profile."""
    return await get_user_by_id(user_id, db)