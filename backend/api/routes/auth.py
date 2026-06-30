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

from fastapi import APIRouter, Depends, HTTPException, status

from backend.core.dependencies import get_current_user_id
from backend.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from backend.models.schemas import (
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
    SuccessResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user account",
)
async def register(request: UserRegisterRequest):
    """
    Phase 2 implementation:
    - Check email uniqueness in PostgreSQL
    - Hash password with bcrypt
    - Insert User row
    - Return TokenResponse (auto-login on register)
    """
    # Phase 1 stub — returns 501 until Phase 2
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Auth not yet implemented. Coming in Phase 2.",
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login and receive JWT tokens",
)
async def login(request: UserLoginRequest):
    """
    Phase 2 implementation:
    - Look up user by email in PostgreSQL
    - Verify password with bcrypt
    - Create access + refresh JWT tokens
    - Store refresh token hash in Redis for blacklisting
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Auth not yet implemented. Coming in Phase 2.",
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh access token",
)
async def refresh_token(refresh_token: str):
    """
    Phase 2 implementation:
    - Verify refresh token signature and expiry
    - Check refresh token not blacklisted in Redis
    - Issue new access + refresh token pair
    - Blacklist old refresh token
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Auth not yet implemented. Coming in Phase 2.",
    )


@router.post(
    "/logout",
    response_model=SuccessResponse,
    summary="Logout and invalidate tokens",
)
async def logout(user_id: str = Depends(get_current_user_id)):
    """
    Phase 2 implementation:
    - Blacklist current refresh token in Redis
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Auth not yet implemented. Coming in Phase 2.",
    )


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get current user profile",
)
async def get_me(user_id: str = Depends(get_current_user_id)):
    """
    Phase 2 implementation:
    - Look up user by ID from JWT subject
    - Return UserResponse
    """
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Auth not yet implemented. Coming in Phase 2.",
    )