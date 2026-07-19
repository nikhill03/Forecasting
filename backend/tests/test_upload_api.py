"""
backend/tests/test_upload_api.py
==================================
Integration tests for POST /api/v1/upload
Uses FastAPI TestClient (httpx under the hood).
"""

import io

import pandas as pd
import pytest


def _make_csv_bytes(rows: int = 50) -> bytes:
    """Generate a minimal valid CSV with a date column."""
    import datetime
    dates  = pd.date_range("2023-01-01", periods=rows, freq="D")
    df     = pd.DataFrame({
        "date"  : dates,
        "sales" : range(rows),
        "units" : range(rows, rows * 2),
    })
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


def _make_excel_bytes(rows: int = 50) -> bytes:
    """Generate a minimal valid Excel file."""
    import datetime
    dates = pd.date_range("2023-01-01", periods=rows, freq="D")
    df    = pd.DataFrame({"date": dates, "revenue": range(rows)})
    buf   = io.BytesIO()
    df.to_excel(buf, index=False)
    return buf.getvalue()


class TestUploadEndpoint:

    def test_health_check(self, client):
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "healthy"

    def test_upload_csv_success(self, client):
        csv_bytes = _make_csv_bytes()
        res = client.post(
            "/api/v1/upload",
            files={"file": ("test.csv", csv_bytes, "text/csv")},
        )
        assert res.status_code == 201
        data = res.json()
        assert "upload_id" in data
        assert "Sheet1" in data["sheets"]
        assert "date" in data["columns"]["Sheet1"]
        assert data["row_counts"]["Sheet1"] == 50

    def test_upload_excel_success(self, client):
        xlsx_bytes = _make_excel_bytes()
        res = client.post(
            "/api/v1/upload",
            files={"file": ("test.xlsx", xlsx_bytes,
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert res.status_code == 201
        data = res.json()
        assert "upload_id" in data

    def test_upload_unsupported_type(self, client):
        res = client.post(
            "/api/v1/upload",
            files={"file": ("test.txt", b"some text", "text/plain")},
        )
        assert res.status_code == 415

    def test_upload_no_date_column(self, client):
        df  = pd.DataFrame({"sales": range(10), "units": range(10)})
        buf = io.BytesIO()
        df.to_csv(buf, index=False)
        res = client.post(
            "/api/v1/upload",
            files={"file": ("nodate.csv", buf.getvalue(), "text/csv")},
        )
        assert res.status_code == 422
        assert "date column" in res.json()["detail"].lower()

    def test_get_upload_metadata(self, client):
        # First upload
        csv_bytes = _make_csv_bytes()
        upload_res = client.post(
            "/api/v1/upload",
            files={"file": ("test.csv", csv_bytes, "text/csv")},
        )
        upload_id = upload_res.json()["upload_id"]

        # Then retrieve
        get_res = client.get(f"/api/v1/upload/{upload_id}")
        assert get_res.status_code == 200
        assert get_res.json()["upload_id"] == upload_id

    def test_get_nonexistent_upload(self, client):
        res = client.get("/api/v1/upload/nonexistent-id")
        assert res.status_code == 404
