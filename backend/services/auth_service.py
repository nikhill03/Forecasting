"""
backend/services/auth_service.py
==================================
Authentication business logic.
Routes call these; they never touch HTTP directly.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from backend.models.db_models import User
from backend.models.schemas import (
    TokenResponse,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)


async def register_user(
    request: UserRegisterRequest,
    db: AsyncSession,
) -> TokenResponse:
    """Create account and auto-login. Raises 409 if email exists."""
    existing = await db.execute(
        select(User).where(User.email == request.email.lower())
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    user = User(
        email=request.email.lower(),
        password_hash=hash_password(request.password),
        full_name=request.full_name,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        token_type="bearer",
    )


async def login_user(
    request: UserLoginRequest,
    db: AsyncSession,
) -> TokenResponse:
    """Authenticate user. Raises 401 for invalid credentials."""
    result = await db.execute(
        select(User).where(User.email == request.email.lower())
    )
    user = result.scalar_one_or_none()

    if not user or not verify_password(request.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled. Please contact support.",
        )

    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        token_type="bearer",
    )


async def refresh_tokens(
    refresh_token: str,
    db: AsyncSession,
) -> TokenResponse:
    """Exchange refresh token for new token pair."""
    from jose import JWTError

    try:
        payload = decode_token(refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type.",
            )
        user_id: str = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload.",
            )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token invalid or expired.",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or disabled.",
        )

    return TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        token_type="bearer",
    )


async def get_user_by_id(
    user_id: str,
    db: AsyncSession,
) -> UserResponse:
    """Fetch user profile by ID."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )
    return UserResponse.model_validate(user)