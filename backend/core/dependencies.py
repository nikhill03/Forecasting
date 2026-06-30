"""
backend/core/dependencies.py
=============================
FastAPI dependency injection functions.
These are injected into route handlers via Depends().
"""

from __future__ import annotations

from typing import AsyncGenerator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from backend.core.config import Settings, get_settings
from backend.core.security import decode_token

bearer_scheme = HTTPBearer(auto_error=False)


# ── Settings dependency ──────────────────────────────────────────

def get_config(settings: Settings = Depends(get_settings)) -> Settings:
    return settings


# ── Auth dependency (Phase 2 will add DB lookup) ─────────────────

async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> str:
    """
    Extract and validate the JWT bearer token.
    Returns the user_id (subject) from the token.

    Phase 2: will extend to look up the full User object from DB.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(credentials.credentials)
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


# ── Optional auth (for endpoints accessible to anonymous users) ───

async def get_optional_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> str | None:
    """Returns user_id if token present and valid, else None."""
    if credentials is None:
        return None
    try:
        payload = decode_token(credentials.credentials)
        return payload.get("sub")
    except JWTError:
        return None