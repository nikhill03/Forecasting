"""
backend/api/routes/upload.py
=============================
File upload endpoint.
Replaces: callbacks/file_callbacks.py (Dash-specific upload handling)

Endpoints:
    POST /api/v1/upload          — upload CSV or Excel file
    GET  /api/v1/upload/{id}     — get upload metadata (sheets, columns)
    Phase 2: uploads to S3, stores metadata in PostgreSQL.
    Falls back to in-memory if S3 not configured (local dev).
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone
from typing import Dict, List

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import Settings, get_settings
from backend.core.database import get_db
from backend.models.schemas import UploadResponse

router = APIRouter(prefix="/upload", tags=["upload"])

# Fallback in-memory store when S3 not configured
_upload_store: Dict[str, dict] = {}


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


@router.post("", response_model=UploadResponse, status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> UploadResponse:
    content = await file.read()

    if len(content) > settings.MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum size of {settings.MAX_UPLOAD_SIZE_MB}MB",
        )

    filename = file.filename or "upload.csv"
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

    upload_id = str(uuid.uuid4())
    s3_key = f"{settings.S3_UPLOAD_PREFIX}{upload_id}/{filename}"
    columns = {name: list(df.columns) for name, df in sheets_with_dates.items()}
    row_counts = {name: len(df) for name, df in sheets_with_dates.items()}

    # Try S3 upload; fall back to in-memory for local dev
    if settings.S3_BUCKET_NAME and settings.AWS_ACCESS_KEY_ID:
        try:
            from backend.storage.s3_client import upload_file as s3_upload
            await s3_upload(content, s3_key)
        except Exception:
            _upload_store[upload_id] = {"content": content}
    else:
        _upload_store[upload_id] = {"content": content}

    _upload_store[upload_id] = {
        "upload_id": upload_id,
        "file_name": filename,
        "s3_key": s3_key,
        "sheets": list(sheets_with_dates.keys()),
        "columns": columns,
        "row_counts": row_counts,
        "content": content,
        "uploaded_at": datetime.now(timezone.utc),
    }

    return UploadResponse(
        upload_id=upload_id,
        file_name=filename,
        s3_key=s3_key,
        sheets=list(sheets_with_dates.keys()),
        columns=columns,
        row_counts=row_counts,
        uploaded_at=datetime.now(timezone.utc),
    )


@router.get("/{upload_id}", response_model=UploadResponse)
async def get_upload(upload_id: str) -> UploadResponse:
    record = _upload_store.get(upload_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Upload '{upload_id}' not found",
        )
    return UploadResponse(**{k: v for k, v in record.items() if k != "content"})


def get_upload_content(upload_id: str) -> bytes:
    """Internal helper: get raw bytes. Phase 3: downloads from S3."""
    record = _upload_store.get(upload_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Upload '{upload_id}' not found or expired",
        )
    return record["content"]