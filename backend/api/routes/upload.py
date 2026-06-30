"""
backend/api/routes/upload.py
=============================
File upload endpoint.
Replaces: callbacks/file_callbacks.py (Dash-specific upload handling)

Endpoints:
    POST /api/v1/upload          — upload CSV or Excel file
    GET  /api/v1/upload/{id}     — get upload metadata (sheets, columns)
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone
from typing import Dict, List

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from backend.core.config import Settings, get_settings
from backend.core.dependencies import get_current_user_id
from backend.models.schemas import UploadResponse

router = APIRouter(prefix="/upload", tags=["upload"])

# In-memory store for Phase 1 (Phase 2: replaced by PostgreSQL + S3)
_upload_store: Dict[str, dict] = {}


def _parse_file(content: bytes, filename: str) -> Dict[str, pd.DataFrame]:
    """Parse uploaded CSV or Excel into dict of {sheet_name: DataFrame}."""
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
    """Find a column with 'date' in its name (case-insensitive)."""
    for col in df.columns:
        if "date" in str(col).lower():
            return col
    return None


def _get_column_info(df: pd.DataFrame) -> List[str]:
    """Return list of column names."""
    return list(df.columns)


@router.post(
    "",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a CSV or Excel file for forecasting",
)
async def upload_file(
    file     : UploadFile = File(...),
    settings : Settings   = Depends(get_settings),
    # Phase 2: uncomment to require auth
    # user_id: str = Depends(get_current_user_id),
) -> UploadResponse:
    """
    Upload a dataset file (CSV or Excel).

    Returns sheet names, column names, and row counts so the
    frontend can render the column selector UI.

    Phase 2: file will be stored in S3; metadata in PostgreSQL.
    """

    # ── Validate file size ────────────────────────────────────────
    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum size of {settings.MAX_UPLOAD_SIZE_MB}MB",
        )

    # ── Validate file type ────────────────────────────────────────
    filename = file.filename or "upload.csv"
    allowed  = (".csv", ".xlsx", ".xls")
    if not any(filename.lower().endswith(ext) for ext in allowed):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"File type not supported. Allowed: {', '.join(allowed)}",
        )

    # ── Parse file ────────────────────────────────────────────────
    sheets_df = _parse_file(content, filename)

    if not sheets_df:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="File parsed successfully but contained no data.",
        )

    # ── Validate each sheet has a date column ─────────────────────
    sheets_with_dates = {}
    for sheet_name, df in sheets_df.items():
        date_col = _infer_date_column(df)
        if date_col:
            sheets_with_dates[sheet_name] = df

    if not sheets_with_dates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "No sheet contains a date column. "
                "Ensure at least one column name contains 'date'."
            ),
        )

    # ── Build metadata ────────────────────────────────────────────
    upload_id  = str(uuid.uuid4())
    columns    = {name: _get_column_info(df) for name, df in sheets_with_dates.items()}
    row_counts = {name: len(df) for name, df in sheets_with_dates.items()}

    # Phase 1: store in memory
    # Phase 2: upload content to S3, store metadata in PostgreSQL
    _upload_store[upload_id] = {
        "upload_id"  : upload_id,
        "file_name"  : filename,
        "s3_key"     : f"uploads/{upload_id}/{filename}",  # Phase 2: actual S3 key
        "sheets"     : list(sheets_with_dates.keys()),
        "columns"    : columns,
        "row_counts" : row_counts,
        "content"    : content,   # Phase 2: remove, stored in S3
        "uploaded_at": datetime.now(timezone.utc),
    }

    return UploadResponse(
        upload_id   = upload_id,
        file_name   = filename,
        s3_key      = f"uploads/{upload_id}/{filename}",
        sheets      = list(sheets_with_dates.keys()),
        columns     = columns,
        row_counts  = row_counts,
        uploaded_at = datetime.now(timezone.utc),
    )


@router.get(
    "/{upload_id}",
    response_model=UploadResponse,
    summary="Get metadata for a previously uploaded file",
)
async def get_upload(upload_id: str) -> UploadResponse:
    """Retrieve upload metadata by ID."""
    record = _upload_store.get(upload_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Upload '{upload_id}' not found",
        )
    return UploadResponse(**{k: v for k, v in record.items() if k != "content"})


def get_upload_content(upload_id: str) -> bytes:
    """
    Internal helper: retrieve raw file bytes for the forecast pipeline.
    Phase 2: will download from S3 instead.
    """
    record = _upload_store.get(upload_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Upload '{upload_id}' not found or expired",
        )
    return record["content"]