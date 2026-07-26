"""
backend/core/dependencies.py
=============================
FastAPI dependency injection functions.
These are injected into route handlers via Depends().
"""
from __future__ import annotations

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import Settings, get_settings, settings
from backend.core.security import decode_token
from backend.core.database import get_db

bearer_scheme = HTTPBearer(auto_error=False)

# Shared by backend.main (registers it on app.state) and backend.api.routes.auth
# (applies it via @limiter.limit(...)). Lives here rather than main.py to avoid a
# main.py <-> auth.py circular import.
limiter = Limiter(key_func=get_remote_address, storage_uri=settings.REDIS_URL)


def get_config(settings: Settings = Depends(get_settings)) -> Settings:
    return settings


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> str:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(credentials.credentials, expected_type="access")
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload",
            )
        return user_id
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token invalid or expired",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def get_current_user(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Returns full User ORM object. Use when you need user attributes."""
    from backend.models.db_models import User

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )
    return user


async def get_optional_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> str | None:
    if credentials is None:
        return None
    try:
        payload = decode_token(credentials.credentials, expected_type="access")
        return payload.get("sub")
    except JWTError:
        return None


def parse_uuid_or_404(value: str, resource_name: str) -> str:
    """A malformed ID must be indistinguishable from one that doesn't
    exist — both 404, never a raw DB type-cast error (asyncpg rejects a
    non-UUID string against a UUID column with a 500, not a clean 404)."""
    try:
        uuid.UUID(value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{resource_name} '{value}' not found",
        )
    return value