"""
backend/api/routes/upload.py
=============================
File upload endpoint.
Replaces: callbacks/file_callbacks.py (Dash-specific upload handling)

Endpoints:
    POST /api/v1/upload              — upload CSV or Excel file
    GET  /api/v1/upload/samples      — list built-in sample datasets
    POST /api/v1/upload/sample/{id}  — materialise a sample as a real upload
    GET  /api/v1/upload/{id}         — get upload metadata (sheets, columns)
    Uploads to S3, persists metadata in PostgreSQL. Falls back to a
    job-scoped local filesystem path (local dev only) when S3 isn't
    configured.

Both POST routes converge on _persist_upload(). That is deliberate: a
sample must produce an ordinary Upload row indistinguishable from a
hand-uploaded file, so that forecast.py and forecast_task.py need no
knowledge of samples at all. If sample handling ever needs a branch inside
_persist_upload, the design has gone wrong — fix the design.
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
from backend.models.schemas import (
    SampleDatasetResponse,
    SampleListResponse,
    UploadResponse,
)
from backend.services.sample_datasets import (
    get_sample,
    list_samples,
    load_sample_bytes,
)
from utils.forecasting import infer_date_column

router = APIRouter(prefix="/upload", tags=["upload"])
logger = structlog.get_logger("forecasting.upload")

_LOCAL_STORAGE_ROOT = "outputs"


# Tried in order. utf-8-sig also strips a BOM if present; cp1252 covers the
# smart quotes / em dashes / degree signs Excel commonly writes on Windows;
# latin-1 always succeeds (every byte is a valid code point) and is the
# last-resort fallback.
_CSV_ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")


def _read_csv_any_encoding(content: bytes) -> pd.DataFrame:
    last_error: UnicodeDecodeError | None = None
    for encoding in _CSV_ENCODINGS:
        try:
            return pd.read_csv(io.BytesIO(content), encoding=encoding)
        except UnicodeDecodeError as e:
            last_error = e
    raise last_error  # pragma: no cover — latin-1 never raises UnicodeDecodeError


def _parse_file(content: bytes, filename: str) -> Dict[str, pd.DataFrame]:
    try:
        if filename.endswith((".xlsx", ".xls")):
            xls = pd.ExcelFile(io.BytesIO(content))
            return {sheet: xls.parse(sheet) for sheet in xls.sheet_names}
        elif filename.endswith(".csv"):
            df = _read_csv_any_encoding(content)
            return {"Sheet1": df}
        else:
            raise ValueError(f"Unsupported file type: {filename}")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to parse file: {str(e)}",
        )


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


async def _persist_upload(
    *,
    content: bytes,
    filename: str,
    user_id: str,
    settings: Settings,
    db: AsyncSession,
) -> Upload:
    """Validate, store and record one uploaded dataset.

    The single path shared by POST /upload and POST /upload/sample/{id} —
    everything from size check through the committed Upload row. Callers
    supply bytes and a filename and get back a persisted Upload; how those
    bytes were obtained is not this function's concern, and must not become
    one.
    """
    if len(content) > settings.MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum size of {settings.MAX_UPLOAD_SIZE_MB}MB",
        )

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
        if infer_date_column(df)
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

    return upload


@router.post("", response_model=UploadResponse, status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> UploadResponse:
    content = await file.read()

    upload = await _persist_upload(
        content=content,
        filename=file.filename or "upload.csv",
        user_id=user_id,
        settings=settings,
        db=db,
    )

    logger.info(
        "upload_complete",
        upload_id=upload.id,
        user_id=user_id,
        rows=sum(upload.row_counts.values()),
    )

    return _to_upload_response(upload)


# NOTE: /samples must stay ABOVE GET /{upload_id}. FastAPI matches routes in
# declaration order, so the reverse would let {upload_id} capture the literal
# string "samples" and parse_uuid_or_404 would 404 the catalog.
@router.get("/samples", response_model=SampleListResponse)
async def list_sample_datasets(
    user_id: str = Depends(get_current_user_id),
) -> SampleListResponse:
    return SampleListResponse(
        samples=[
            SampleDatasetResponse(
                id=sample.id,
                title=sample.title,
                description=sample.description,
                demand_class=sample.demand_class,
                file_name=sample.file_name,
                frequency=sample.frequency,
                row_count=sample.row_count,
                columns=list(sample.columns),
            )
            for sample in list_samples()
        ]
    )


@router.post("/sample/{sample_id}", response_model=UploadResponse, status_code=201)
async def create_upload_from_sample(
    sample_id: str,
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
    user_id: str = Depends(get_current_user_id),
) -> UploadResponse:
    """Copy a built-in sample into the caller's account as a real upload.

    sample_id is untrusted path input and is resolved by dict lookup only —
    it never reaches a path join. The filename handed to _persist_upload
    comes from the catalog entry we constructed ourselves.
    """
    try:
        sample = get_sample(sample_id)
    except KeyError:
        # Deliberately does not echo sample_id back. The valid set is small,
        # public and fixed, so naming it is both safer and more useful.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Unknown sample dataset. Available: "
                + ", ".join(s.id for s in list_samples())
            ),
        )

    content = await asyncio.to_thread(load_sample_bytes, sample.id)

    upload = await _persist_upload(
        content=content,
        filename=sample.file_name,
        user_id=user_id,
        settings=settings,
        db=db,
    )

    logger.info(
        "sample_upload_created",
        sample_id=sample.id,
        upload_id=upload.id,
        user_id=user_id,
        rows=sum(upload.row_counts.values()),
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
