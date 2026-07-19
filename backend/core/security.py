"""
backend/core/security.py
=========================
JWT token creation/verification and password hashing utilities.
Phase 2 will wire these into the auth routes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from backend.core.config import settings

# bcrypt password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Password helpers ─────────────────────────────────────────────

def hash_password(plain: str) -> str:
    """Hash a plain-text password using bcrypt."""
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plain-text password against a bcrypt hash."""
    return pwd_context.verify(plain, hashed)


# ── JWT helpers ──────────────────────────────────────────────────

def create_access_token(
    subject  : str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create a signed JWT access token.

    Parameters
    ----------
    subject      : user identifier (typically user.id as str)
    expires_delta: custom TTL; defaults to ACCESS_TOKEN_EXPIRE_MINUTES
    """
    expire = datetime.now(timezone.utc) + (
        expires_delta
        or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    payload = {
        "sub" : subject,
        "exp" : expire,
        "iat" : datetime.now(timezone.utc),
        "type": "access",
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(subject: str) -> str:
    """Create a signed JWT refresh token with longer TTL."""
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.REFRESH_TOKEN_EXPIRE_DAYS
    )
    payload = {
        "sub" : subject,
        "exp" : expire,
        "iat" : datetime.now(timezone.utc),
        "type": "refresh",
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str, expected_type: str | None = None) -> dict:
    """
    Decode and verify a JWT token.

    Parameters
    ----------
    expected_type: if given, the token's "type" claim must match this
                    value or a JWTError is raised (treated the same as
                    any other decode failure by callers).

    Raises
    ------
    JWTError if token is invalid, expired, tampered with, or (when
    expected_type is given) of the wrong type.
    """
    payload = jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.ALGORITHM],
    )
    if expected_type is not None and payload.get("type") != expected_type:
        raise JWTError(
            f"Invalid token type: expected '{expected_type}', "
            f"got '{payload.get('type')}'"
        )
    return payload


def extract_subject(token: str) -> Optional[str]:
    """
    Extract the subject (user_id) from a token without raising.
    Returns None if the token is invalid.
    """
    try:
        payload = decode_token(token)
        return payload.get("sub")
    except JWTError:
        return None