"""
backend/api/routes/upload.py
=============================
File upload endpoint.
Replaces: callbacks/file_callbacks.py (Dash-specific upload handling)

Endpoints:
    POST /api/v1/upload          — upload CSV or Excel file
    GET  /api/v1/upload/{id}     — get upload metadata (sheets, columns)
    Uploads to S3, persists metadata in PostgreSQL. Falls back to a
    job-scoped local filesystem path (local dev only) when S3 isn't
    configured.
"""

from __future__ import annotations

import asyncio
import io
import os
import uuid
from typing import Dict

import pandas as pd
import structlog
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import Settings, get_settings
from backend.core.database import get_db
from backend.core.dependencies import get_current_user_id, parse_uuid_or_404
from backend.models.db_models import Upload
from backend.models.schemas import UploadResponse

router = APIRouter(prefix="/upload", tags=["upload"])
logger = structlog.get_logger("forecasting.upload")

_LOCAL_STORAGE_ROOT = "outputs"


def _parse_file(content: bytes, filename: str) -> Dict[str, pd.DataFrame]:
    try:
        if filename.endswith((".xlsx", ".xls")):
            xls = pd.ExcelFile(io.BytesIO(content))
            return {sheet: xls.parse(sheet) for sheet in xls.sheet_names}
        elif filename.endswith(".csv"):
            df = pd.read_csv(io.BytesIO(content))
            return {"Sheet1": df}
        else:
            raise ValueError(f"Unsupported file type: {filename}")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to parse file: {str(e)}",
        )


def _infer_date_column(df: pd.DataFrame) -> str | None:
    for col in df.columns:
        if "date" in str(col).lower():
            return col
    return None


def _reject_unsafe_filename(filename: str) -> None:
    """filename is client-supplied and is used to build both the local-
    fallback filesystem path and the S3 key — a path separator or ".."
    segment would let a caller write outside outputs/uploads/{upload_id}/
    (os.path.join silently discards the directory prefix entirely for an
    absolute path) or land an unexpected key in S3. Reject outright rather
    than silently stripping, since the caller's intended filename would
    otherwise no longer match what's stored/returned."""
    basename = os.path.basename(filename)
    if basename in ("", ".", "..") or "/" in filename or "\\" in filename:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid file name",
        )


def _to_upload_response(upload: Upload) -> UploadResponse:
    return UploadResponse(
        upload_id=upload.id,
        file_name=upload.file_name,
        s3_key=upload.s3_key,
        sheets=upload.sheets,
        columns=upload.columns,
        row_counts=upload.row_counts,
        uploaded_at=upload.created_at,
    )


async def _store_locally(content: bytes, settings: Settings, upload_id: str, filename: str) -> str:
    """Dev-only fallback when S3 isn't configured. Writes under the repo's
    existing gitignored outputs/ runtime-artifacts directory, mirroring the
    S3 key layout (S3_UPLOAD_PREFIX) so the local path and the S3 key differ
    only by root. Key is prefixed "local:" — the read-side convention
    already used for job outputs in forecast.py."""

    def _write() -> str:
        directory = os.path.join(
            _LOCAL_STORAGE_ROOT, settings.S3_UPLOAD_PREFIX.rstrip("/"), upload_id
        )
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, filename)
        with open(path, "wb") as f:
            f.write(content)
        return f"local:{path}"

    return await asyncio.to_thread(_write)


@router.post("", response_model=UploadResponse, status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> UploadResponse:
    content = await file.read()

    if len(content) > settings.MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum size of {settings.MAX_UPLOAD_SIZE_MB}MB",
        )

    filename = file.filename or "upload.csv"
    _reject_unsafe_filename(filename)

    allowed = (".csv", ".xlsx", ".xls")
    if not any(filename.lower().endswith(ext) for ext in allowed):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"File type not supported. Allowed: {', '.join(allowed)}",
        )

    sheets_df = _parse_file(content, filename)

    sheets_with_dates = {
        name: df for name, df in sheets_df.items()
        if _infer_date_column(df)
    }

    if not sheets_with_dates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No sheet contains a date column.",
        )

    upload_id  = str(uuid.uuid4())
    columns    = {name: list(df.columns) for name, df in sheets_with_dates.items()}
    row_counts = {name: len(df) for name, df in sheets_with_dates.items()}

    if settings.S3_BUCKET_NAME and settings.AWS_ACCESS_KEY_ID:
        from backend.storage.s3_client import upload_file as s3_upload

        s3_key = f"{settings.S3_UPLOAD_PREFIX}{upload_id}/{filename}"
        try:
            await s3_upload(content, s3_key)
        except RuntimeError:
            logger.error("upload_s3_failed", upload_id=upload_id, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Upload storage unavailable",
            )
    else:
        s3_key = await _store_locally(content, settings, upload_id, filename)

    upload = Upload(
        id=upload_id,
        user_id=user_id,
        file_name=filename,
        s3_key=s3_key,
        sheets=list(sheets_with_dates.keys()),
        columns=columns,
        row_counts=row_counts,
        file_size_bytes=len(content),
    )
    db.add(upload)
    await db.commit()
    await db.refresh(upload)

    logger.info(
        "upload_complete",
        upload_id=upload_id,
        user_id=user_id,
        rows=sum(row_counts.values()),
    )

    return _to_upload_response(upload)


@router.get("/{upload_id}", response_model=UploadResponse)
async def get_upload(
    upload_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> UploadResponse:
    parse_uuid_or_404(upload_id, "Upload")

    result = await db.execute(
        select(Upload).where(Upload.id == upload_id, Upload.user_id == user_id)
    )
    upload = result.scalar_one_or_none()
    if not upload:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Upload '{upload_id}' not found",
        )

    return _to_upload_response(upload)
