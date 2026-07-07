"""
backend/storage/s3_client.py
==============================
AWS S3 integration — replaces in-memory upload store from Phase 1.
All operations are async-wrapped via asyncio.to_thread().
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

from backend.core.config import settings

logger = logging.getLogger("storage.s3")


def _get_client():
    return boto3.client(
        "s3",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_DEFAULT_REGION,
    )


async def upload_file(
    content: bytes,
    key: str,
    content_type: str = "application/octet-stream",
) -> str:
    def _upload():
        _get_client().put_object(
            Bucket=settings.S3_BUCKET_NAME,
            Key=key,
            Body=content,
            ContentType=content_type,
        )
        return key

    try:
        return await asyncio.to_thread(_upload)
    except NoCredentialsError:
        raise RuntimeError("S3 not configured — check AWS credentials in .env")
    except ClientError as e:
        raise RuntimeError(f"S3 upload failed: {e}")


async def upload_json(data: dict, key: str) -> str:
    content = json.dumps(data, default=str).encode("utf-8")
    return await upload_file(content, key, content_type="application/json")


async def download_file(key: str) -> bytes:
    def _download():
        response = _get_client().get_object(
            Bucket=settings.S3_BUCKET_NAME, Key=key
        )
        return response["Body"].read()

    try:
        return await asyncio.to_thread(_download)
    except ClientError as e:
        if e.response["Error"]["Code"] == "NoSuchKey":
            raise FileNotFoundError(f"S3 key not found: {key}")
        raise RuntimeError(f"S3 download failed: {e}")


async def download_json(key: str) -> dict:
    content = await download_file(key)
    return json.loads(content.decode("utf-8"))


async def get_presigned_download_url(
    key: str,
    expires_in: int = 3600,
    filename: Optional[str] = None,
) -> str:
    def _presign():
        params = {"Bucket": settings.S3_BUCKET_NAME, "Key": key}
        if filename:
            params["ResponseContentDisposition"] = (
                f'attachment; filename="{filename}"'
            )
        return _get_client().generate_presigned_url(
            "get_object", Params=params, ExpiresIn=expires_in
        )

    return await asyncio.to_thread(_presign)


async def get_presigned_upload_url(
    key: str,
    expires_in: int = 3600,
    content_type: str = "application/octet-stream",
) -> str:
    def _presign():
        return _get_client().generate_presigned_url(
            "put_object",
            Params={
                "Bucket": settings.S3_BUCKET_NAME,
                "Key": key,
                "ContentType": content_type,
            },
            ExpiresIn=expires_in,
        )

    return await asyncio.to_thread(_presign)


async def key_exists(key: str) -> bool:
    def _check():
        try:
            _get_client().head_object(
                Bucket=settings.S3_BUCKET_NAME, Key=key
            )
            return True
        except ClientError:
            return False

    return await asyncio.to_thread(_check)


async def delete_file(key: str) -> None:
    def _delete():
        _get_client().delete_object(
            Bucket=settings.S3_BUCKET_NAME, Key=key
        )

    await asyncio.to_thread(_delete)