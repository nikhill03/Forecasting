"""
backend/services/file_parsing.py
=================================
Uploaded-file parsing shared by every route that reads a dataset: the
upload routes (validation), the data-quality report and POST /forecast
(F16). Moved out of backend/api/routes/upload.py unchanged so all three
read a file identically.

backend/tasks/forecast_task.py still carries its own copy of the CSV
reader — known duplication, out of F16's scope.
"""

from __future__ import annotations

import io
from typing import Dict

import pandas as pd
from fastapi import HTTPException, status

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


def parse_file(content: bytes, filename: str) -> Dict[str, pd.DataFrame]:
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
