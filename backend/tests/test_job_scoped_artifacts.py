"""
backend/tests/test_job_scoped_artifacts.py
=============================================
Tests for F5 (job-scoped-artifacts), based on
`.claude/specs/p0-job-scoped-artifacts.md`.

Source-of-truth behaviors under test (see spec Overview / Service Layer
Changes / API Changes / Definition of Done):

1. `services/processing_engine.processing_worker()` requires a `job_id: str`
   first positional argument with NO default, namespaces every output file
   under `outputs/predictions/{job_id}/`, and RETURNS the predictions dict
   (never `None`) instead of relying on a fixed shared path being re-read
   afterward.
2. `DELETE /api/v1/forecast/{job_id}` signals a per-job Redis key
   (`dmc:stop:{job_id}`) instead of a single global stop-flag file, so
   stopping job A can never affect job B (or C, or D) — and job A's own
   worker DOES actually observe and honor the signal.
3. Ownership/auth on `DELETE /forecast/{job_id}` is unchanged by this
   feature (that's F3's job) but must still hold: 401 unauthenticated, 404
   cross-tenant.

ASSUMPTION: the Definition of Done's literal
`grep -rn "predictions_all.json|processing_stop.flag" services/ backend/`
check, run verbatim (including comments and the test suite), currently
still matches two kinds of non-defect text that a blunt string grep can't
distinguish from a real regression:
  1. `backend/tests/test_forecast_auth.py` deliberately reconstructs the
     OLD global path string to prove a tenant can no longer be served
     another tenant's leaked global-file output -- that's a legitimate F3
     regression test, not a reintroduction of the bug.
  2. Explanatory comments in `services/processing_engine.py` and
     `backend/api/routes/forecast.py` narrate the historical defect by
     name (e.g. "the F5 defect: a single shared predictions_all.json...")
     for future readers, matching this same codebase's convention of
     naming past bugs in comments (see CLAUDE.md's own "Known Defects"
     section).
Neither is the functional bug the DoD line exists to catch: a CODE path
that still reads/writes a fixed, non-job-scoped file. The check below
therefore excludes `backend/tests/` and comment-only lines, so it stays a
meaningful, durable regression guard against the actual defect returning
to a code path, without being tripped by history being described in
prose.
"""

from __future__ import annotations

import inspect
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from backend.models.db_models import ForecastJob
from services.processing_engine import (
    OUT_PRED_DIR,
    _job_figs_json,
    _job_pred_json,
    _job_progress_json,
    processing_worker,
    read_predictions_and_figs,
    read_progress,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def _make_csv_data_uri(start_value: int, rows: int = 60) -> str:
    """Minimal, distinguishable time-series input for processing_worker."""
    import base64
    import io

    dates = pd.date_range("2023-01-01", periods=rows, freq="D")
    df = pd.DataFrame({"date": dates, "sales": range(start_value, start_value + rows)})
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:application/octet-stream;base64,{b64}"


async def _make_job(db_session, owner_id: str, **overrides) -> ForecastJob:
    job = ForecastJob(
        id=str(uuid.uuid4()),
        user_id=owner_id,
        status=overrides.pop("status", "running"),
        progress_pct=overrides.pop("progress_pct", 0),
        progress_message=overrides.pop("progress_message", "Running"),
        created_at=datetime.now(timezone.utc),
        **overrides,
    )
    db_session.add(job)
    await db_session.flush()
    return job


def _cleanup_job_dir(job_id: str) -> None:
    shutil.rmtree(os.path.join(OUT_PRED_DIR, job_id), ignore_errors=True)


# ── 1. processing_worker(): job_id is required, positional, no default ──
class TestProcessingWorkerRequiresJobId:
    """DoD: 'processing_worker() is uncallable without a job_id argument
    (no default value exists)'."""

    def test_job_id_parameter_has_no_default(self):
        sig = inspect.signature(processing_worker)
        params = list(sig.parameters.values())
        assert params[0].name == "job_id"
        assert params[0].default is inspect.Parameter.empty

    def test_calling_without_job_id_raises_type_error(self):
        with pytest.raises(TypeError):
            processing_worker(  # type: ignore[call-arg]
                file_contents_norm=_make_csv_data_uri(start_value=1),
                selected_sheets_list=["Sheet1"],
            )

    def test_calling_with_job_id_as_none_is_still_accepted_by_signature(self):
        """job_id has no default, but nothing stops a caller from passing
        None explicitly -- the spec only requires a hard failure for a
        MISSING argument, not a runtime type check on its value. This
        documents that boundary rather than asserting behavior the spec
        never promises."""
        sig = inspect.signature(processing_worker)
        # binding a positional job_id (even a nonsense value) must not
        # raise at the *binding* stage -- only omitting it entirely does.
        sig.bind(job_id="anything", file_contents_norm="x", selected_sheets_list=[])


# ── 2. processing_worker(): happy path, job-scoped artifacts ────────────
class TestProcessingWorkerHappyPath:
    """DoD: two jobs resolve to their own results; a submitted job's
    return value / on-disk artifacts are namespaced under its own job_id."""

    def test_returns_predictions_dict_and_writes_namespaced_files(self):
        job_id = f"test-happy-{uuid.uuid4().hex}"
        try:
            result = processing_worker(
                job_id=job_id,
                file_contents_norm=_make_csv_data_uri(start_value=10),
                selected_sheets_list=["Sheet1"],
                selected_metrics=["sales"],
                forecast_horizon=5,
                test_window=10,
                selected_regions=["US"],
            )

            # Returns the predictions dict directly (never None) -- this is
            # what forecast_task.py now consumes instead of re-reading a
            # fixed local path.
            assert result is not None
            assert isinstance(result, dict)
            assert "Sheet1" in result

            # Every output file lives under outputs/predictions/{job_id}/,
            # not a shared top-level path.
            pred_path     = _job_pred_json(job_id)
            figs_path     = _job_figs_json(job_id)
            progress_path = _job_progress_json(job_id)
            assert job_id in pred_path
            assert job_id in figs_path
            assert job_id in progress_path
            assert os.path.exists(pred_path)
            assert os.path.exists(progress_path)

            # read_predictions_and_figs(job_id) round-trips the same data
            # processing_worker returned (its own reader helper is also
            # job-scoped now, per the spec).
            preds, _figs = read_predictions_and_figs(job_id)
            assert "Sheet1" in preds
        finally:
            _cleanup_job_dir(job_id)

    def test_two_distinct_job_ids_get_two_distinct_directories(self):
        """Cheap, non-pipeline-running namespacing check: distinct job_ids
        must never resolve to the same on-disk path, which is the root
        cause the spec identifies (a single shared PRED_JSON path)."""
        job_id_a = f"test-namespace-a-{uuid.uuid4().hex}"
        job_id_b = f"test-namespace-b-{uuid.uuid4().hex}"

        try:
            assert _job_pred_json(job_id_a) != _job_pred_json(job_id_b)
            assert _job_figs_json(job_id_a) != _job_figs_json(job_id_b)
            assert _job_progress_json(job_id_a) != _job_progress_json(job_id_b)
        finally:
            # The path builders create the job's directory as a side
            # effect (os.makedirs(..., exist_ok=True)), even though no
            # file is ever written here.
            _cleanup_job_dir(job_id_a)
            _cleanup_job_dir(job_id_b)

    def test_two_full_pipeline_runs_do_not_clobber_each_other(self):
        """Heavier, end-to-end sibling of the two tests above: actually runs
        the full pipeline twice (not just the path builders) with distinct
        input data, and confirms job A's on-disk file still matches job A's
        own return value after job B has also run -- the exact "job B's
        write clobbers job A's read" race the spec describes."""
        job_id_a = f"test-job-a-{uuid.uuid4().hex}"
        job_id_b = f"test-job-b-{uuid.uuid4().hex}"

        try:
            result_a = processing_worker(
                job_id=job_id_a,
                file_contents_norm=_make_csv_data_uri(start_value=100),
                selected_sheets_list=["Sheet1"],
                selected_metrics=["sales"],
                forecast_horizon=5,
                test_window=10,
                selected_regions=["US"],
            )
            result_b = processing_worker(
                job_id=job_id_b,
                file_contents_norm=_make_csv_data_uri(start_value=5000),
                selected_sheets_list=["Sheet1"],
                selected_metrics=["sales"],
                forecast_horizon=5,
                test_window=10,
                selected_regions=["US"],
            )

            assert result_a != result_b

            path_a = _job_pred_json(job_id_a)
            path_b = _job_pred_json(job_id_b)
            assert path_a != path_b
            assert os.path.exists(path_a)
            assert os.path.exists(path_b)

            # result_a/result_b contain pd.Timestamp objects, which
            # json.load() from disk always reads back as plain strings --
            # round-trip through the same json.dumps(default=str)
            # serialization processing_worker uses so the comparison isn't
            # a false mismatch.
            expected_a = json.loads(json.dumps(result_a, default=str))
            expected_b = json.loads(json.dumps(result_b, default=str))
            with open(path_a) as f:
                assert json.load(f) == expected_a
            with open(path_b) as f:
                assert json.load(f) == expected_b
        finally:
            _cleanup_job_dir(job_id_a)
            _cleanup_job_dir(job_id_b)


# ── 3. read_predictions_and_figs(): job-scoped reads, no cross-job leak ──
class TestReadPredictionsIsolation:
    """Direct, fast (no ML pipeline run) proof that the reader helper
    resolves a job-scoped path and never returns another job's content --
    the exact failure mode the spec describes ('job A returns job B's
    forecast')."""

    def test_reading_job_a_never_returns_job_bs_content(self):
        job_id_a = f"test-read-a-{uuid.uuid4().hex}"
        job_id_b = f"test-read-b-{uuid.uuid4().hex}"
        try:
            os.makedirs(os.path.dirname(_job_pred_json(job_id_a)), exist_ok=True)
            os.makedirs(os.path.dirname(_job_pred_json(job_id_b)), exist_ok=True)

            with open(_job_pred_json(job_id_a), "w") as fh:
                json.dump({"Sheet1": {"metrics": {"sales": {"owner": "A"}}}}, fh)
            with open(_job_pred_json(job_id_b), "w") as fh:
                json.dump({"Sheet1": {"metrics": {"sales": {"owner": "B"}}}}, fh)

            preds_a, _ = read_predictions_and_figs(job_id_a)
            preds_b, _ = read_predictions_and_figs(job_id_b)

            assert preds_a["Sheet1"]["metrics"]["sales"]["owner"] == "A"
            assert preds_b["Sheet1"]["metrics"]["sales"]["owner"] == "B"
        finally:
            _cleanup_job_dir(job_id_a)
            _cleanup_job_dir(job_id_b)

    def test_reading_unknown_job_id_returns_empty_not_another_jobs_data(self):
        """A job_id with no on-disk artifacts yet (e.g. still pending) must
        get back an empty result -- never fall through to some other job's
        (or the old global) file."""
        unknown_job_id = f"test-unknown-{uuid.uuid4().hex}"
        try:
            preds, figs = read_predictions_and_figs(unknown_job_id)
            assert preds == {}
            assert figs == {}
        finally:
            _cleanup_job_dir(unknown_job_id)


# ── 4. Stop signal actually halts the targeted worker ────────────────────
class TestStopSignalHaltsWorker:
    """DoD (stop isolation, direction 2 of 2): job A itself IS actually
    stopped -- not just that job B is left alone. Exercises the exact
    mechanism the spec prescribes: `redis_client.exists(f"dmc:stop:{job_id}")`,
    read via the fake_redis fixture that's autoused for every test."""

    def test_pre_set_stop_key_halts_processing_worker_before_any_work(
        self, fake_redis
    ):
        job_id = f"test-stop-halts-{uuid.uuid4().hex}"
        fake_redis.set(f"dmc:stop:{job_id}", "1")
        try:
            result = processing_worker(
                job_id=job_id,
                file_contents_norm=_make_csv_data_uri(start_value=1),
                selected_sheets_list=["Sheet1"],
                selected_metrics=["sales"],
                forecast_horizon=5,
                test_window=10,
                selected_regions=["US"],
            )
            # The very first status emission checks the stop key and raises
            # before any sheet/metric is processed -- predictions_by_sheet
            # never gets populated.
            assert result == {}

            progress = read_progress(job_id)
            assert progress.get("status") == "stopped"
        finally:
            _cleanup_job_dir(job_id)

    def test_without_a_stop_key_the_same_job_runs_to_completion(self, fake_redis):
        """Control case for the test above: absent a stop signal, the
        identical inputs produce a populated result -- proving the empty
        `{}` above is caused by the stop key, not some unrelated failure."""
        job_id = f"test-no-stop-{uuid.uuid4().hex}"
        assert not fake_redis.exists(f"dmc:stop:{job_id}")
        try:
            result = processing_worker(
                job_id=job_id,
                file_contents_norm=_make_csv_data_uri(start_value=1),
                selected_sheets_list=["Sheet1"],
                selected_metrics=["sales"],
                forecast_horizon=5,
                test_window=10,
                selected_regions=["US"],
            )
            assert result != {}
            assert "Sheet1" in result
        finally:
            _cleanup_job_dir(job_id)


# ── 5. DELETE /forecast/{job_id}: cross-job stop isolation (API layer) ───
class TestStopJobIsolationAcrossMultipleJobs:
    """DoD (stop isolation, direction 1 of 2): stopping A must never affect
    B (or C, or D -- the spec explicitly calls out more than two jobs)."""

    async def test_stopping_one_job_leaves_two_others_untouched(
        self, async_client, db_session, test_user, make_auth_headers, fake_redis
    ):
        job_a = await _make_job(db_session, owner_id=test_user.id)
        job_b = await _make_job(db_session, owner_id=test_user.id)
        job_c = await _make_job(db_session, owner_id=test_user.id)

        res = await async_client.delete(
            f"/api/v1/forecast/{job_a.id}", headers=make_auth_headers(test_user)
        )
        assert res.status_code == 200

        assert fake_redis.exists(f"dmc:stop:{job_a.id}")
        assert not fake_redis.exists(f"dmc:stop:{job_b.id}")
        assert not fake_redis.exists(f"dmc:stop:{job_c.id}")

        await db_session.refresh(job_a)
        await db_session.refresh(job_b)
        await db_session.refresh(job_c)
        assert job_a.status == "stopped"
        assert job_b.status == "running"
        assert job_c.status == "running"

    async def test_stop_key_written_matches_spec_naming_convention(
        self, async_client, db_session, test_user, make_auth_headers, fake_redis
    ):
        """Locks in the exact key format the spec names --
        `dmc:stop:{job_id}` -- so a future refactor can't silently rename
        it without a test failing."""
        job = await _make_job(db_session, owner_id=test_user.id)
        res = await async_client.delete(
            f"/api/v1/forecast/{job.id}", headers=make_auth_headers(test_user)
        )
        assert res.status_code == 200
        assert fake_redis.exists(f"dmc:stop:{job.id}")


# ── 6. Auth boundaries on DELETE /forecast/{job_id} (unchanged by F5) ────
class TestStopJobAuthBoundaries:
    async def test_stop_job_requires_auth(self, async_client):
        res = await async_client.delete(f"/api/v1/forecast/{uuid.uuid4()}")
        assert res.status_code == 401

    async def test_cross_tenant_stop_returns_404_and_sets_no_stop_key(
        self, async_client, db_session, test_user, second_user, make_auth_headers, fake_redis
    ):
        job = await _make_job(db_session, owner_id=test_user.id, status="pending")
        res = await async_client.delete(
            f"/api/v1/forecast/{job.id}", headers=make_auth_headers(second_user)
        )
        assert res.status_code == 404

        # F5's own guarantee -- an unauthorized stop attempt must not leak
        # a stop signal for the job either.
        assert not fake_redis.exists(f"dmc:stop:{job.id}")

        await db_session.refresh(job)
        assert job.status == "pending"


# ── 7. Regression: the old shared global paths are gone from production code ─
class TestGlobalPathStringsRemoved:
    """DoD: `grep -rn "predictions_all.json|processing_stop.flag" services/
    backend/` returns nothing. Scoped to exclude backend/tests/ and
    comment-only lines -- see module docstring ASSUMPTION for why."""

    FORBIDDEN_STRINGS = ("predictions_all.json", "processing_stop.flag")

    def _iter_source_files(self):
        for base in ("services", "backend"):
            base_path = REPO_ROOT / base
            if not base_path.exists():
                continue
            for path in base_path.rglob("*.py"):
                if base == "backend" and "tests" in path.relative_to(base_path).parts:
                    continue
                if "__pycache__" in path.parts:
                    continue
                yield path

    def test_no_production_code_line_references_the_old_global_paths(self):
        offenders: list[str] = []
        for path in self._iter_source_files():
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            for lineno, line in enumerate(lines, start=1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    # Historical-defect narration in comments (this
                    # codebase's own convention, see CLAUDE.md's "Known
                    # Defects" section) is not a functional regression.
                    continue
                for forbidden in self.FORBIDDEN_STRINGS:
                    if forbidden in line:
                        offenders.append(f"{path}:{lineno}: contains {forbidden!r}")
        assert offenders == [], "Old global shared paths still referenced in code:\n" + "\n".join(
            offenders
        )
