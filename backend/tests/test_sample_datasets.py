"""
backend/tests/test_sample_datasets.py
======================================
Tests for the built-in sample datasets (F13) — the catalog module, the two
new routes, and the data itself.

Filename note: this deliberately avoids the spec slug's "p2.5" prefix. A
dot in the module name would break pytest's dotted import under
backend/tests/__init__.py (it would be read as a package boundary).

The s3_client moto fixture is MANDATORY on every test that creates an
upload: conftest.py forces S3_BUCKET_NAME/AWS_* unconditionally, so the S3
branch in upload.py always fires in the test process.

The data assertions here exist because SAMPLE_CATALOG hardcodes row_count,
columns and demand_class rather than computing them per request. That is a
deliberate performance choice, and these tests are what stop the manifest
from drifting away from the CSVs it describes.
"""

from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import select

from backend.models.db_models import Upload
from backend.services.sample_datasets import (
    SAMPLE_CATALOG,
    SAMPLES_DIR,
    load_sample_bytes,
)
from utils.forecasting import infer_date_column
from utils.metrics import classify_demand

_SAMPLE_IDS = list(SAMPLE_CATALOG)

# Read on every sample request, and committed to git — keep them small.
_MAX_SAMPLE_BYTES = 100 * 1024


def _read_sample_df(sample_id: str) -> pd.DataFrame:
    sample = SAMPLE_CATALOG[sample_id]
    return pd.read_csv(SAMPLES_DIR / sample.file_name)


# ══════════════════════════════════════════════════════════════════
# The catalog and the data behind it
# ══════════════════════════════════════════════════════════════════

class TestSampleCatalog:

    def test_catalog_is_not_empty(self):
        assert len(SAMPLE_CATALOG) >= 2

    def test_ids_are_self_consistent(self):
        # The dict key and the dataclass id must agree, since routes look up
        # by key but log and store using sample.id.
        for key, sample in SAMPLE_CATALOG.items():
            assert key == sample.id

    @pytest.mark.parametrize("sample_id", _SAMPLE_IDS)
    def test_file_exists_and_is_small(self, sample_id):
        path = SAMPLES_DIR / SAMPLE_CATALOG[sample_id].file_name
        assert path.is_file()
        assert path.stat().st_size <= _MAX_SAMPLE_BYTES

    @pytest.mark.parametrize("sample_id", _SAMPLE_IDS)
    def test_declared_metadata_matches_csv(self, sample_id):
        """The manifest cannot silently drift from the data."""
        sample = SAMPLE_CATALOG[sample_id]
        df     = _read_sample_df(sample_id)

        assert len(df) == sample.row_count
        assert list(df.columns) == list(sample.columns)

    @pytest.mark.parametrize("sample_id", _SAMPLE_IDS)
    def test_date_column_is_inferred_and_first(self, sample_id):
        """infer_date_column is parse-based and first-match-wins, so the date
        column must lead and no numeric column may look like a year."""
        df = _read_sample_df(sample_id)

        assert infer_date_column(df) == "date"
        assert list(df.columns)[0] == "date"

    @pytest.mark.parametrize("sample_id", _SAMPLE_IDS)
    def test_series_is_daily_and_continuous(self, sample_id):
        """Demand classification runs on a series that data_handling.py
        force-reindexes to freq="D". A gap or a non-daily frequency would
        make the classification an artifact of imputation."""
        df    = _read_sample_df(sample_id)
        dates = pd.to_datetime(df["date"])

        assert dates.is_monotonic_increasing
        assert dates.diff().dropna().eq(pd.Timedelta(days=1)).all()

    @pytest.mark.parametrize("sample_id", _SAMPLE_IDS)
    def test_classifies_into_declared_quadrant(self, sample_id):
        """The whole point of shipping three samples is that they land in
        three different quadrants. Assert it against the real classifier."""
        sample = SAMPLE_CATALOG[sample_id]
        df     = _read_sample_df(sample_id)
        series = pd.Series(df[df.columns[1]].to_numpy(), dtype=float)

        assert classify_demand(series=series).demand_type == sample.demand_class

    def test_samples_span_distinct_quadrants(self):
        classes = [s.demand_class for s in SAMPLE_CATALOG.values()]
        assert len(set(classes)) == len(classes)

    def test_load_sample_bytes_returns_file_content(self):
        sample_id = _SAMPLE_IDS[0]
        content   = load_sample_bytes(sample_id)

        assert isinstance(content, bytes)
        assert content == (SAMPLES_DIR / SAMPLE_CATALOG[sample_id].file_name).read_bytes()

    @pytest.mark.parametrize(
        "bad_id",
        ["nonexistent", "../../etc/passwd", "..", "", "retail-daily-smooth.csv"],
    )
    def test_load_sample_bytes_rejects_unknown_id(self, bad_id):
        """Resolution is dict-lookup only — an unknown id must fail before
        any filesystem access, not resolve to a path."""
        with pytest.raises(KeyError):
            load_sample_bytes(bad_id)


# ══════════════════════════════════════════════════════════════════
# GET /api/v1/upload/samples
# ══════════════════════════════════════════════════════════════════

class TestListSamplesEndpoint:

    async def test_requires_auth(self, async_client):
        res = await async_client.get("/api/v1/upload/samples")
        assert res.status_code == 401

    async def test_lists_every_catalog_entry(self, async_client, test_user, make_auth_headers):
        res = await async_client.get(
            "/api/v1/upload/samples",
            headers=make_auth_headers(test_user),
        )
        assert res.status_code == 200

        samples = res.json()["samples"]
        assert len(samples) == len(SAMPLE_CATALOG)
        assert {s["id"] for s in samples} == set(SAMPLE_CATALOG)

    async def test_entries_carry_display_metadata(
        self, async_client, test_user, make_auth_headers
    ):
        res = await async_client.get(
            "/api/v1/upload/samples",
            headers=make_auth_headers(test_user),
        )
        first = res.json()["samples"][0]

        for field in ("id", "title", "description", "demand_class", "frequency", "row_count", "columns"):
            assert field in first
        assert first["row_count"] > 0
        assert isinstance(first["columns"], list)

    async def test_samples_path_is_not_shadowed_by_upload_id_route(
        self, async_client, test_user, make_auth_headers
    ):
        """Regression guard on route declaration order. If GET /{upload_id}
        were declared first it would capture the literal "samples" and
        parse_uuid_or_404 would turn this into a 404."""
        res = await async_client.get(
            "/api/v1/upload/samples",
            headers=make_auth_headers(test_user),
        )
        assert res.status_code == 200
        assert "samples" in res.json()


# ══════════════════════════════════════════════════════════════════
# POST /api/v1/upload/sample/{sample_id}
# ══════════════════════════════════════════════════════════════════

class TestCreateUploadFromSample:

    async def test_requires_auth(self, async_client):
        res = await async_client.post("/api/v1/upload/sample/retail-daily-smooth")
        assert res.status_code == 401

    @pytest.mark.parametrize("sample_id", _SAMPLE_IDS)
    async def test_creates_upload_for_each_sample(
        self, async_client, test_user, make_auth_headers, s3_client, sample_id
    ):
        res = await async_client.post(
            f"/api/v1/upload/sample/{sample_id}",
            headers=make_auth_headers(test_user),
        )
        assert res.status_code == 201

        data   = res.json()
        sample = SAMPLE_CATALOG[sample_id]

        assert data["file_name"] == sample.file_name
        assert data["sheets"] == ["Sheet1"]
        assert data["row_counts"]["Sheet1"] == sample.row_count
        assert data["columns"]["Sheet1"] == list(sample.columns)

    async def test_persists_a_real_owner_scoped_upload_row(
        self, async_client, db_session, test_user, make_auth_headers, s3_client
    ):
        res = await async_client.post(
            "/api/v1/upload/sample/retail-daily-smooth",
            headers=make_auth_headers(test_user),
        )
        upload_id = res.json()["upload_id"]

        row = (
            await db_session.execute(select(Upload).where(Upload.id == upload_id))
        ).scalar_one_or_none()

        assert row is not None
        assert row.user_id == test_user.id
        assert row.file_size_bytes > 0

    async def test_upload_is_readable_through_the_ordinary_get_route(
        self, async_client, test_user, make_auth_headers, s3_client
    ):
        """A sample upload must be an ordinary upload — no second read path."""
        created = await async_client.post(
            "/api/v1/upload/sample/spare-parts-lumpy",
            headers=make_auth_headers(test_user),
        )
        upload_id = created.json()["upload_id"]

        fetched = await async_client.get(
            f"/api/v1/upload/{upload_id}",
            headers=make_auth_headers(test_user),
        )
        assert fetched.status_code == 200
        assert fetched.json()["upload_id"] == upload_id

    async def test_another_user_cannot_read_the_upload(
        self, async_client, test_user, second_user, make_auth_headers, s3_client
    ):
        created = await async_client.post(
            "/api/v1/upload/sample/retail-daily-smooth",
            headers=make_auth_headers(test_user),
        )
        upload_id = created.json()["upload_id"]

        res = await async_client.get(
            f"/api/v1/upload/{upload_id}",
            headers=make_auth_headers(second_user),
        )
        assert res.status_code == 404

    async def test_s3_key_follows_the_standard_upload_layout(
        self, async_client, test_user, make_auth_headers, s3_client
    ):
        from backend.core.config import settings

        res = await async_client.post(
            "/api/v1/upload/sample/retail-daily-smooth",
            headers=make_auth_headers(test_user),
        )
        data = res.json()

        expected = f"{settings.S3_UPLOAD_PREFIX}{data['upload_id']}/{data['file_name']}"
        assert data["s3_key"] == expected

        # And the object is really in the bucket, not merely recorded.
        stored = s3_client.get_object(
            Bucket=settings.S3_BUCKET_NAME, Key=data["s3_key"]
        )["Body"].read()
        assert stored == load_sample_bytes("retail-daily-smooth")

    @pytest.mark.parametrize(
        "bad_id",
        ["nonexistent", "retail-daily-smooth.csv", "%2e%2e%2fetc%2fpasswd", "RETAIL-DAILY-SMOOTH"],
    )
    async def test_unknown_sample_id_returns_404(
        self, async_client, test_user, make_auth_headers, s3_client, bad_id
    ):
        res = await async_client.post(
            f"/api/v1/upload/sample/{bad_id}",
            headers=make_auth_headers(test_user),
        )
        assert res.status_code == 404

    async def test_404_does_not_reflect_the_requested_id(
        self, async_client, test_user, make_auth_headers, s3_client
    ):
        marker = "zzz-not-a-sample-marker"
        res = await async_client.post(
            f"/api/v1/upload/sample/{marker}",
            headers=make_auth_headers(test_user),
        )
        assert res.status_code == 404
        assert marker not in res.text

    async def test_no_upload_row_is_created_for_an_unknown_id(
        self, async_client, db_session, test_user, make_auth_headers, s3_client
    ):
        before = len((await db_session.execute(select(Upload))).scalars().all())

        await async_client.post(
            "/api/v1/upload/sample/nonexistent",
            headers=make_auth_headers(test_user),
        )

        after = len((await db_session.execute(select(Upload))).scalars().all())
        assert after == before
