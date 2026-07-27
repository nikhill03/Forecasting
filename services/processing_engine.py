from __future__ import annotations

import base64
import io
import json
import logging
import os
import time
import traceback
from datetime import datetime
import tempfile
from typing import List, Optional, Dict, Any

import pandas as pd
import numpy as np
import plotly.graph_objects as go
import redis

# Local imports
from utils.forecasting import parse_uploaded_data, infer_date_column
from services.forecasting_engine import ForecastingEngine
from services.data_handling import DataHandling
from utils.metrics import (
    wmape, forecast_accuracy, mae, mape, rmse,
    calculate_adi, calculate_cv2, classify_demand,
    calculate_performance_metrics, composite_score,
    DemandProfile,
)
from services.multivariate_engine import MultivariateEngine
from services.treatment_analyzer import TreatmentAnalyzer
from utils.holiday_utils import get_region_holidays

# Paths / files
OUT_BASE = os.path.join(os.getcwd(), "outputs")
OUT_LOG_DIR = os.path.join(OUT_BASE, "logs")
OUT_PRED_DIR = os.path.join(OUT_BASE, "predictions")

os.makedirs(OUT_LOG_DIR, exist_ok=True)
os.makedirs(OUT_PRED_DIR, exist_ok=True)

LOCK_PATH = os.path.join(OUT_BASE, "processing.lock")
DONE_FLAG = os.path.join(OUT_BASE, "processing_done.flag")
DEBUG_LOG = os.path.join(OUT_LOG_DIR, "processing_debug.txt")
TRACEBACK_FILE = os.path.join(OUT_LOG_DIR, "processing_exception_traceback.txt")
STD_LOG = os.path.join(OUT_LOG_DIR, "processing.log")
HISTORY_LOG = os.path.join(OUT_LOG_DIR, "model_history.csv")


# ── Job-scoped output paths ────────────────────────────────────────────
# Every concurrent job gets its own subdirectory under OUT_PRED_DIR so that
# two jobs running close together can never clobber each other's results
# (the F5 defect: a single shared predictions_all.json meant job B's write
# could overwrite job A's results before job A read them back).
def _job_pred_dir(job_id: str) -> str:
    # Defense-in-depth: job_id is always a server-generated uuid4() today
    # (ForecastJob.id), never client-controlled, so this isn't reachable
    # under current callers — but nothing here enforced that invariant, so
    # reject path-traversal-shaped values before they can escape OUT_PRED_DIR.
    if not job_id or os.sep in job_id or (os.altsep and os.altsep in job_id) or ".." in job_id:
        raise ValueError(f"invalid job_id: {job_id!r}")
    path = os.path.join(OUT_PRED_DIR, job_id)
    os.makedirs(path, exist_ok=True)
    return path


def _job_pred_json(job_id: str) -> str:
    return os.path.join(_job_pred_dir(job_id), "predictions.json")


def _job_figs_json(job_id: str) -> str:
    return os.path.join(_job_pred_dir(job_id), "figs.json")


def _job_progress_json(job_id: str) -> str:
    return os.path.join(_job_pred_dir(job_id), "progress.json")


# ── Per-job stop signal (Redis) ─────────────────────────────────────────
# This module is a standalone ML engine with no dependency on the backend/
# FastAPI layer, so it never imports backend.core.config.settings. The
# caller that DOES have settings (backend/tasks/forecast_task.py) is
# expected to pass its resolved `settings.REDIS_URL` in explicitly via the
# `redis_url` parameter threaded through processing_worker() below — the
# os.environ.get() fallback here exists only for standalone/test callers
# that construct no Settings object at all.
#
# IMPORTANT: do not rely on the os.environ fallback matching
# settings.REDIS_URL in a real deployment. pydantic-settings' env_file
# loading populates its own Settings object, NOT the process's actual
# os.environ — so if REDIS_URL is only set via .env (this project's own
# documented convention), os.environ.get("REDIS_URL") here will silently
# return the hardcoded default below instead of the configured value,
# while backend/api/routes/forecast.py's settings.REDIS_URL resolves
# correctly. That divergence previously meant DELETE /forecast/{job_id}
# could write a stop key to one Redis while this module checked another —
# the stop signal writes successfully and is simply never observed.
_DEFAULT_REDIS_URL = "redis://localhost:6379/0"
_REDIS_RETRY_COOLDOWN_SECONDS = 30

_redis_clients: dict[str, Any] = {}
_redis_retry_at: dict[str, float] = {}


def _get_redis_client(redis_url: str | None = None):
    """Lazily construct (and cache, per URL) a redis client. Never raises —
    a misconfigured or unreachable Redis (including the test suite's
    REDIS_URL=memory://, which redis-py cannot parse) must never block
    module import or a running job. A construction failure is retried
    after a cooldown rather than latched forever — a permanent latch would
    mean one transient error permanently disables the stop signal for the
    rest of this process's life."""
    url = redis_url or os.environ.get("REDIS_URL", _DEFAULT_REDIS_URL)

    retry_at = _redis_retry_at.get(url)
    if retry_at is not None and time.time() < retry_at:
        return None

    if url not in _redis_clients:
        try:
            _redis_clients[url] = redis.Redis.from_url(
                url, socket_connect_timeout=1, socket_timeout=1
            )
            _redis_retry_at.pop(url, None)
        except Exception:
            _redis_retry_at[url] = time.time() + _REDIS_RETRY_COOLDOWN_SECONDS
            return None
    return _redis_clients[url]


def _is_stop_requested(job_id: str, redis_url: str | None = None) -> bool:
    client = _get_redis_client(redis_url)
    if client is None:
        return False
    try:
        return bool(client.exists(f"dmc:stop:{job_id}"))
    except Exception:
        # Fail open: a missed stop check can be retried on the next call;
        # failing closed would stop every running job on a Redis blip.
        return False

# Logging setup
logger = logging.getLogger("dmc.processing")
logger.setLevel(logging.INFO)

if not logger.handlers:
    fh = logging.FileHandler(STD_LOG, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)

def _now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _emit_status(job_id, total, done, message, completed=False, redis_url=None):
    progress_json = _job_progress_json(job_id)

    if _is_stop_requested(job_id, redis_url):
        stop_data = {
            "percent": int((done / total) * 100) if total > 0 else 0,
            "message": "Execution Stopped by User",
            "status": "stopped",
            "timestamp": datetime.now().isoformat()
        }
        try:
            directory = os.path.dirname(progress_json)
            fd, temp_path = tempfile.mkstemp(dir=directory, text=True)
            with os.fdopen(fd, 'w') as fh:
                json.dump(stop_data, fh)
            os.replace(temp_path, progress_json)
        except:
            pass
        _write_debug("Execution STOPPED: Thread terminating immediately.")
        raise InterruptedError("Stopped by user")

    percent = int((done / total) * 100) if total > 0 else (100 if completed else 0)

    data = {
        "total": total,
        "done": done,
        "percent": percent,
        "message": message,
        "timestamp": datetime.now().isoformat()
    }
    if completed:
        data["completed_at"] = datetime.now().isoformat()

    try:
        directory = os.path.dirname(progress_json)
        fd, temp_path = tempfile.mkstemp(dir=directory, text=True)
        with os.fdopen(fd, 'w') as fh:
            json.dump(data, fh)
        for _ in range(5):
            try:
                os.replace(temp_path, progress_json)
                break
            except PermissionError:
                time.sleep(0.05)
    except Exception as e:
        print(f"[Engine] Status Write Error: {e}")
    finally:
        if 'temp_path' in locals() and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except:
                pass

def _write_debug(msg: str) -> None:
    try:
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{_now_ts()}] {msg}\n")
    except Exception:
        pass
    logger.info(msg)

def normalize_upload_contents(contents) -> Optional[str]:
    if not contents:
        return None
    if isinstance(contents, str):
        return contents
    if isinstance(contents, dict) and "content" in contents:
        return contents["content"]
    if isinstance(contents, list) and contents:
        first = contents[0]
        if isinstance(first, dict) and "content" in first:
            return first["content"]
        if isinstance(first, str):
            return first
    return None

# Tried in order. utf-8-sig also strips a BOM if present; cp1252 covers the
# smart quotes / em dashes / degree signs Excel commonly writes on Windows;
# latin-1 always succeeds (every byte is a valid code point) and is the
# last-resort fallback. Mirrors backend/api/routes/upload.py's _read_csv_any_encoding
# so a file accepted at upload time doesn't fail to decode again here at job time.
_CSV_ENCODINGS = ("utf-8-sig", "cp1252", "latin-1")


def _read_csv_any_encoding(decoded: bytes) -> pd.DataFrame:
    last_error: UnicodeDecodeError | None = None
    for encoding in _CSV_ENCODINGS:
        try:
            return pd.read_csv(io.BytesIO(decoded), encoding=encoding)
        except UnicodeDecodeError as e:
            last_error = e
    raise last_error  # pragma: no cover — latin-1 never raises UnicodeDecodeError


def parse_uploaded_data_robust(content_string) -> Dict[str, pd.DataFrame]:
    try:
        if not content_string:
            return {}
        if ',' in content_string:
            _, content_string = content_string.split(',', 1)
        decoded = base64.b64decode(content_string)
        try:
            xls = pd.ExcelFile(io.BytesIO(decoded))
            return {s: xls.parse(s) for s in xls.sheet_names}
        except:
            try:
                df = _read_csv_any_encoding(decoded)
                return {"Sheet1": df}
            except Exception as e:
                _write_debug(f"Parse Error: {e}")
                return {}
    except Exception as e:
        _write_debug(f"General Parse Error: {e}")
        return {}

def create_lock() -> bool:
    try:
        with open(LOCK_PATH, "w") as fh:
            fh.write(f"pid:{os.getpid()} time:{time.time()}\n")
        return True
    except Exception:
        return False

def remove_lock() -> None:
    try:
        if os.path.exists(LOCK_PATH):
            os.remove(LOCK_PATH)
    except Exception:
        pass

def clear_all_outputs() -> None:
    # NOTE: this wipes every job's namespaced subdirectory under
    # OUT_PRED_DIR at once — the exact cross-job blast radius the
    # job-scoped path builders above otherwise eliminate. Currently unused
    # by any route/task (grepped repo-wide) so this is inert today; if
    # this is ever wired into a cleanup task, it must be scoped to a single
    # job's directory instead, not the whole tree.
    import shutil
    try:
        shutil.rmtree(OUT_PRED_DIR, ignore_errors=True)
        os.makedirs(OUT_PRED_DIR, exist_ok=True)
    except Exception:
        pass
    for p in [DONE_FLAG, DEBUG_LOG, TRACEBACK_FILE]:
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass

def log_experiment(
    sheet: str, metric: str, stage: str, model_name: str,
    wmape_val: float, mae_val: float, mape_val: float, accuracy_val: float,
    rmse_val: float = None,
):
    """
    FIX: Added rmse_val parameter and RMSE column to CSV header.
    FIX: Removed duplicate inline import of composite_score.
    """
    try:
        if not os.path.exists(HISTORY_LOG):
            with open(HISTORY_LOG, "w") as f:
                f.write("Timestamp,Sheet,Metric,Stage,Model,WMAPE,MAE,MAPE,RMSE,Accuracy\n")
        with open(HISTORY_LOG, "a") as f:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            w   = f"{wmape_val:.5f}"    if wmape_val   is not None else ""
            m   = f"{mae_val:.5f}"      if mae_val     is not None else ""
            mp  = f"{mape_val:.5f}"     if mape_val    is not None else ""
            r   = f"{rmse_val:.5f}"     if rmse_val    is not None else ""
            acc = f"{accuracy_val:.2f}" if accuracy_val is not None else ""
            f.write(f"{timestamp},{sheet},{metric},{stage},{model_name},{w},{m},{mp},{r},{acc}\n")
    except Exception as e:
        print(f"Log Error: {e}")

def build_records(
    train_series: pd.Series,
    test_series: pd.Series,
    test_pred_series: Optional[pd.Series] = None,
    forecast_series: Optional[pd.Series] = None,
    train_series_raw: Optional[pd.Series] = None,
    df_x_clean: Optional[pd.DataFrame] = None
):
    records_by_date: Dict[pd.Timestamp, Dict[str, Any]] = {}

    def ensure_row(dt):
        dt = pd.to_datetime(dt)
        if dt not in records_by_date:
            records_by_date[dt] = {
                "Date": dt, "TrainActual": None, "TrainRaw": None,
                "TestActual": None, "TestPrediction": None, "Forecast": None,
            }
        return records_by_date[dt]

    if train_series is not None:
        for dt, val in train_series.items():
            ensure_row(dt)["TrainActual"] = None if (val is None or pd.isna(val)) else float(val)
    if train_series_raw is not None:
        for dt, val in train_series_raw.items():
            ensure_row(dt)["TrainRaw"] = None if (val is None or pd.isna(val)) else float(val)
    if test_series is not None:
        for dt, val in test_series.items():
            ensure_row(dt)["TestActual"] = None if (val is None or pd.isna(val)) else float(val)
    if test_pred_series is not None:
        for dt, val in test_pred_series.items():
            ensure_row(dt)["TestPrediction"] = 0.0 if (val is None or pd.isna(val)) else float(val)
    if forecast_series is not None:
        for dt, val in forecast_series.items():
            ensure_row(dt)["Forecast"] = 0.0 if (val is None or pd.isna(val)) else float(val)
    if df_x_clean is not None and not df_x_clean.empty:
        x_lookup = df_x_clean.to_dict(orient="index")
        for dt in records_by_date.keys():
            if dt in x_lookup:
                records_by_date[dt].update(x_lookup[dt])

    return sorted(records_by_date.values(), key=lambda r: r["Date"])


# ══════════════════════════════════════════════════════════════════════
# Main worker
# ══════════════════════════════════════════════════════════════════════
def processing_worker(
    job_id: str,
    file_contents_norm: str,
    selected_sheets_list: List[str],
    selected_metrics: Optional[List[str]] = None,
    selected_x_cols: Optional[List[str]] = None,
    x_clean_weekday: str = "median",
    x_clean_weekend: str = "zero",
    forecast_horizon: int = 60,
    test_window: int = 30,
    x_file_contents: Optional[str] = None,
    selected_regions: list = None,
    redis_url: Optional[str] = None,
) -> dict:

    start_time = time.time()
    total_tasks = 0
    predictions_by_sheet: Dict[str, Any] = {}

    try:
        # os.path.exists(...) then os.remove(...) is a TOCTOU race: DONE_FLAG
        # is process-wide (not job-scoped, by design — see spec), so two
        # concurrent jobs can both see it exist and race to remove it. The
        # loser previously got an uncaught FileNotFoundError here, which the
        # outer except swallowed and reported as a silent, empty "success".
        # Confirmed live with two real concurrent Celery workers.
        try:
            os.remove(DONE_FLAG)
        except FileNotFoundError:
            pass

        _write_debug("Pipeline execution started.")

        dfs = parse_uploaded_data_robust(file_contents_norm)
        if not dfs:
            _write_debug("Error: Uploaded file parsing returned no sheets.")
            try:
                dfs = parse_uploaded_data(file_contents_norm)
            except:
                pass
            if not dfs:
                _write_debug("CRITICAL: Failed to parse input file. Aborting.")
                return predictions_by_sheet

        df_x_global = None
        if x_file_contents:
            _write_debug("Loading external features (X) file...")
            parsed_x = parse_uploaded_data_robust(x_file_contents)
            if parsed_x:
                sheet_x = list(parsed_x.keys())[0]
                df_x_global = parsed_x[sheet_x]
                _write_debug(f"SUCCESS: Loaded {len(df_x_global.columns)} external features from '{sheet_x}'.")
            else:
                _write_debug("Error: Failed to parse external features file.")

        _emit_status(job_id, 0, 0, "Initializing forecasting engine...", redis_url=redis_url)

        figs_by_sheet: Dict[str, Any] = {}

        for sheet in (selected_sheets_list or []):
            df_raw = dfs.get(sheet)
            if df_raw is None:
                continue
            if selected_metrics:
                m_count = len([m for m in selected_metrics if m in df_raw.columns])
            else:
                m_count = len([c for c in df_raw.columns if pd.api.types.is_numeric_dtype(df_raw[c])])
            total_tasks += m_count * 5

        current_progress = 0
        done_count = 0

        for sheet in (selected_sheets_list or []):
            _write_debug(f" Processing Sheet: {sheet} ")
            df_raw = dfs.get(sheet)
            if df_raw is None:
                _write_debug(f"Error: Sheet '{sheet}' missing in parsed sheets.")
                predictions_by_sheet[sheet] = {"metrics": {}}
                figs_by_sheet[sheet] = {}
                continue

            # ── Date column detection ──────────────────────────────
            # Detected by parsing actual values (infer_date_column), not by
            # matching a column literally named "date" — real datasets name
            # this column Month, Period, Year, Week, Timestamp, etc.
            date_col = infer_date_column(df_raw)

            df = df_raw.copy()
            if date_col:
                df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
                df = df.dropna(subset=[date_col]).set_index(date_col).sort_index()
                _write_debug(f"Identified Date Column: '{date_col}'")
            else:
                try:
                    df.index = pd.to_datetime(df.index)
                    _write_debug("Using Index as Date Column.")
                except Exception:
                    _write_debug(f"Error: No valid date column found in '{sheet}'. Skipping.")
                    predictions_by_sheet[sheet] = {"metrics": {}}
                    figs_by_sheet[sheet] = {}
                    continue

            if selected_metrics and len(selected_metrics) > 0:
                metrics_to_run = [m for m in selected_metrics if m in df.columns]
            else:
                metrics_to_run = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
            metrics_to_run = list(dict.fromkeys(metrics_to_run))

            _emit_status(job_id, total_tasks, current_progress, f"Analyzing sheet: {sheet}", redis_url=redis_url)

            sheet_metrics: Dict[str, Any] = {}
            sheet_figs: Dict[str, Any] = {}

            for metric in metrics_to_run:

                # ── Stage 1: Sanitisation ──────────────────────────
                _emit_status(job_id, total_tasks, current_progress, f"Stage 1/5: Sanitizing {sheet}/{metric}...", redis_url=redis_url)
                time.sleep(1.0)
                current_progress += 1

                metric_completed = False
                metric_success = False
                fe = None
                original_models = {}

                try:
                    metric_finalized = False
                    accuracy = None
                    _write_debug(f"Analysis started for Target: {metric}")

                    dh = DataHandling(min_points=30, allow_negative=False, lookback_days=None)
                    raw_series, dh_logs = dh.sanitize(
                        df.reset_index(),
                        date_col=df.index.name if df.index.name else "Date",
                        metric_col=metric,
                    )

                    y_config = TreatmentAnalyzer.analyze_series(raw_series, is_target=True)
                    _write_debug(
                        f"Data Profile: {y_config.get('outlier_treatment','none')} outliers, "
                        f"{y_config.get('weekday_treatment','none')} imputation."
                    )

                    history_len = len(raw_series)
                    absolute_max_limit = max(14, int(history_len * 0.30))
                    safe_horizon = min(int(forecast_horizon), absolute_max_limit)

                    if int(forecast_horizon) > absolute_max_limit:
                        _write_debug(f"Notice: Horizon capped at {safe_horizon} (30% of history).")
                    else:
                        _write_debug(f"Forecasting Horizon strictly set to: {safe_horizon} days.")

                    # ── Stage 2: Feature Engineering ───────────────
                    _emit_status(job_id, total_tasks, current_progress, "Stage 2/5: Processing Features...", redis_url=redis_url)
                    time.sleep(1.0)
                    current_progress += 1

                    X_train_ext = None
                    X_test_ext = None
                    df_x_clean = None

                    if selected_x_cols:
                        valid_x_local = [c for c in selected_x_cols if c in df.columns and c != metric]
                        valid_x_global = []
                        if df_x_global is not None:
                            valid_x_global = [c for c in selected_x_cols if c in df_x_global.columns]

                        df_source = None
                        valid_x = []

                        if valid_x_global:
                            df_source = df_x_global.copy()
                            valid_x = valid_x_global
                            x_date_col = next(
                                (c for c in df_source.columns if "date" in str(c).lower()), None
                            )
                            if x_date_col:
                                df_source[x_date_col] = pd.to_datetime(df_source[x_date_col])
                                df_source = df_source.set_index(x_date_col).sort_index()
                                _write_debug(f"Using External Features file: {len(valid_x)} variables.")
                            else:
                                _write_debug("Warning: No date column in X file.")
                        elif valid_x_local:
                            df_source = df.copy()
                            valid_x = valid_x_local
                            _write_debug(f"Using Features from main file: {len(valid_x)} variables.")

                        if df_source is not None and valid_x:
                            x_configs = TreatmentAnalyzer.analyze_dataframe(df_source[valid_x])
                            df_x_clean = dh.impute_exogenous(
                                df_source[valid_x], valid_x, treatment_configs=x_configs
                            )
                            df_x_clean = df_x_clean.reindex(df.index).ffill().fillna(0)
                        else:
                            _write_debug("Warning: No valid X variables found despite selection.")

                    # ── FIX: Train/test split BEFORE engine init ───
                    # We need a temporary engine with default freq just to split
                    # then re-init with detected freq after split
                    _temp_fe = ForecastingEngine(freq="D", horizon=safe_horizon, test_size=test_window)
                    train_raw, test_raw = _temp_fe._train_test_split(raw_series)

                    train_series = dh.impute_train(train_raw, config=y_config)
                    test_series_clean = dh.impute_train(test_raw, config=y_config)
                    test_series_raw = test_raw
                    full_clean_series = dh.impute_train(raw_series, config=y_config)

                    # ── FIX: Detect frequency from actual data ─────
                    # Use raw_series for freq detection (more reliable than processed)
                    # Fall back to time-delta calculation if infer_freq returns None
                    detected_freq = pd.infer_freq(raw_series.index)
                    if not detected_freq:
                        detected_freq = pd.infer_freq(train_series.index)
                    if not detected_freq:
                        # Calculate from median time delta
                        deltas = raw_series.index.to_series().diff().dropna()
                        median_delta = deltas.median()
                        if median_delta <= pd.Timedelta(hours=1):
                            detected_freq = "h"
                        elif median_delta <= pd.Timedelta(hours=4):
                            detected_freq = "4h"
                        elif median_delta <= pd.Timedelta(days=1):
                            detected_freq = "D"
                        elif median_delta <= pd.Timedelta(weeks=1):
                            detected_freq = "W"
                        elif median_delta <= pd.Timedelta(days=31):
                            detected_freq = "MS"
                        else:
                            detected_freq = "D"
                    _write_debug(f"Detected frequency: {detected_freq}")
                    fe = ForecastingEngine(
                        freq=detected_freq, horizon=safe_horizon, test_size=test_window
                    )
                    _write_debug(f"Engine initialized: Horizon={safe_horizon}, Test Window={test_window}")

                    if selected_x_cols and df_x_clean is not None:
                        X_train_ext = df_x_clean.reindex(train_series.index).ffill().fillna(0)
                        X_test_ext = df_x_clean.reindex(test_series_clean.index).ffill().fillna(0)

                    adi_val = calculate_adi(full_clean_series)
                    cv2_val = calculate_cv2(full_clean_series)

                    # ── FIX: classify_demand now returns DemandProfile ──
                    demand_profile = classify_demand(adi_val=adi_val, cv2_val=cv2_val)
                    demand_type = demand_profile.demand_type
                    _write_debug(
                        f"Demand Pattern: {demand_type} "
                        f"(ADI={adi_val:.2f}, CV2={cv2_val:.2f}) | "
                        f"Recommended models: {demand_profile.recommended_models}"
                    )

                    for msg in dh_logs:
                        if "SKIP" in msg:
                            _write_debug(f"Warning: {msg}")

                    if train_series is None or train_series.empty:
                        _write_debug("Error: Training series empty after sanitization. Skipping.")
                        sheet_metrics[metric] = {
                            "best_model": None, "wmape": None, "records": [],
                            "y_treatment": y_config,
                        }
                        sheet_figs[metric] = {}
                        current_progress += 3
                        continue

                    n_points = len(train_series)
                    zero_ratio = float((train_series == 0).sum()) / max(1, n_points)
                    mean_val = float(train_series.mean())
                    std_val = float(train_series.std())
                    cv = std_val / (mean_val + 1e-6)

                    # ── Stage 3: Univariate Models ─────────────────
                    _emit_status(job_id, total_tasks, current_progress, "Stage 3/5: Running Univariate Models...", redis_url=redis_url)
                    current_progress += 1

                    # ── FIX: Use demand-aware routing ─────────────
                    demand_filtered_models = fe.get_models_for_demand_type(
                        demand_profile=demand_profile,
                        mean_val=mean_val,
                        zero_ratio=zero_ratio,
                        cv=cv,
                        n_points=n_points,
                    )

                    baseline_wmape = None
                    baseline_test_pred = None

                    try:
                        base_res = fe._run_sma(train_series, test_series_raw)
                        b_scores = calculate_performance_metrics(test_series_raw, base_res.predictions_test)
                        baseline_wmape = b_scores["wmape"]
                        baseline_test_pred = base_res.predictions_test
                        log_experiment(sheet, metric, "Univariate", "Baseline_SMA",
                                       b_scores["wmape"], b_scores["mae"], b_scores["mape"],
                                       b_scores["accuracy"])
                        _write_debug(f"Baseline (SMA) Model Performance: WMAPE={b_scores['wmape']:.2%}")
                    except Exception as base_e:
                        _write_debug(f"Warning: Baseline SMA failed: {base_e}")

                    original_models = fe.models.copy()

                    if not demand_filtered_models:
                        # Sparse fallback
                        _write_debug("Notice: Using Sparse Data Fallback (SMA).")
                        train_model_output = fe.run_fallback_model(train_series)
                        fallback_val = float(train_model_output.iloc[0]) if not train_model_output.empty else 0.0
                        test_pred_series = pd.Series(
                            [fallback_val] * len(test_series_raw), index=test_series_raw.index
                        )
                        forecast_series = fe.run_fallback_model(full_clean_series, horizon=safe_horizon)
                        test_pred_series = dh.apply_business_rules(test_pred_series)
                        forecast_series = dh.apply_business_rules(forecast_series)
                        scores = calculate_performance_metrics(test_series_raw, test_pred_series)
                        log_experiment(sheet, metric, "Univariate", "Baseline_SMA",
                                       scores["wmape"], scores["mae"], scores["mape"], scores["accuracy"])
                        records = build_records(
                            train_series=train_series, test_series=test_series_raw,
                            test_pred_series=test_pred_series, forecast_series=forecast_series,
                            train_series_raw=train_raw,
                            df_x_clean=df_x_clean,
                        )
                        sheet_metrics[metric] = {
                            "best_model": "Baseline_SMA",
                            "wmape": scores["wmape"], "accuracy": scores["accuracy"],
                            "adi": adi_val, "cv2": cv2_val, "demand_type": demand_type,
                            "demand_profile": demand_profile.to_dict(),
                            "records": records,
                            "y_treatment": y_config,
                        }
                        metric_completed = True
                        metric_success = True
                        sheet_figs[metric] = {}
                        current_progress += 2
                        continue
                    else:
                        fe.models = demand_filtered_models
                        _write_debug(f"Active Models (demand-routed): {list(fe.models.keys())}")

                    # ── Univariate selection loop ───────────────────
                    try:
                        best_name = None
                        best_wmape = float("inf")
                        best_composite = float("inf")   # FIX: was missing
                        best_test_pred = None

                        _write_debug("Evaluating Univariate Models")

                        for model_name in fe.models.keys():
                            if _is_stop_requested(job_id, redis_url):
                                raise InterruptedError("Stopped by user")
                            try:
                                test_pred = fe.predict_external_test(
                                    model_name, train_series, test_series_raw.index
                                )
                                common_idx = test_series_raw.index.intersection(test_pred.index)
                                effective_test = test_series_raw.loc[common_idx].dropna()
                                effective_test = effective_test[effective_test != 0]

                                min_required = max(7, int(0.3 * len(test_series_raw)))
                                if len(effective_test) < min_required:
                                    _write_debug(
                                        f"{model_name}: Skipped — insufficient test overlap "
                                        f"({len(effective_test)} pts, need {min_required})"
                                    )
                                    continue

                                scores = calculate_performance_metrics(
                                    test_series_raw.loc[common_idx],
                                    test_pred.loc[common_idx],
                                )

                                # ── FIX: Use composite score for selection ──
                                comp_score = composite_score(
                                    actual=test_series_raw.loc[common_idx],
                                    predicted=test_pred.loc[common_idx],
                                    train_series=train_series,
                                    forecast_series=test_pred.loc[common_idx],
                                )

                                _write_debug(
                                    f"{model_name}: WMAPE={scores['wmape']:.4f}  "
                                    f"Composite={comp_score:.4f}"
                                )
                                log_experiment(
                                    sheet, metric, "Univariate", model_name,
                                    scores["wmape"], scores["mae"], scores["mape"],
                                    scores["accuracy"],
                                    rmse_val=scores.get("rmse"),
                                )

                                if comp_score < best_composite:
                                    best_composite = comp_score
                                    best_wmape = scores["wmape"]
                                    best_name = model_name
                                    best_test_pred = test_pred

                            except Exception:
                                continue

                        if best_name is None:
                            raise RuntimeError("All univariate models failed.")

                        external_wmape = best_wmape
                        test_pred_series = best_test_pred

                        common_idx = test_series_raw.index.intersection(test_pred_series.index)
                        effective_test = test_series_raw.loc[common_idx].dropna()
                        effective_test = effective_test[effective_test != 0]
                        if len(effective_test) >= max(7, int(0.3 * len(test_series_raw))):
                            accuracy = forecast_accuracy(
                                test_series_raw.loc[common_idx],
                                test_pred_series.loc[common_idx],
                            )
                        else:
                            accuracy = None

                        # ── FIX: Refit best model on full train+test ──
                        forecast_series = None
                        runner = fe.models.get(best_name)
                        if runner is not None:
                            refit_res = runner(train_series, test_series_clean)
                            if refit_res is not None and hasattr(refit_res, "forecast"):
                                forecast_series = refit_res.forecast.clip(lower=0.0)
                                last_observed_date = raw_series.index.max()
                                forecast_series.index = fe._future_index(
                                    last_observed_date,
                                    len(forecast_series),
                                    raw_series.index,
                                )

                        _write_debug(f"Univariate Winner: {best_name} (WMAPE={external_wmape:.2%})")

                    except Exception as model_err:
                        _write_debug(f"Error: Univariate selection failed ({model_err}). Reverting to Baseline.")
                        train_model_output = fe.run_fallback_model(train_series)
                        fallback_val = float(train_model_output.iloc[0]) if not train_model_output.empty else 0.0
                        test_pred_series = pd.Series(
                            [fallback_val] * len(test_series_raw), index=test_series_raw.index
                        )
                        forecast_series = fe.run_fallback_model(full_clean_series)
                        test_pred_series = dh.apply_business_rules(test_pred_series)
                        forecast_series = dh.apply_business_rules(forecast_series)
                        scores = calculate_performance_metrics(test_series_raw, test_pred_series)
                        log_experiment(sheet, metric, "Univariate", "Baseline_SMA",
                                       scores["wmape"], scores["mae"], scores["mape"], scores["accuracy"])
                        records = build_records(
                            train_series=train_series, test_series=test_series_raw,
                            test_pred_series=test_pred_series, forecast_series=forecast_series,
                            train_series_raw=train_raw, df_x_clean=df_x_clean,
                        )
                        sheet_metrics[metric] = {
                            "best_model": "Baseline_SMA",
                            "wmape": scores["wmape"], "accuracy": scores["accuracy"],
                            "mae": scores["mae"], "mape": scores["mape"],
                            "rmse": scores.get("rmse"),
                            "adi": adi_val, "cv2": cv2_val,
                            "demand_type": demand_type,
                            "demand_profile": demand_profile.to_dict(),
                            "records": records,
                            "y_treatment": y_config,
                        }
                        metric_completed = True
                        metric_success = True
                        sheet_figs[metric] = {}
                        current_progress += 2
                        continue

                    # ── Stage 4: Multivariate ──────────────────────
                    _emit_status(job_id, total_tasks, current_progress, "Stage 4/5: Evaluating Multivariate", redis_url=redis_url)
                    current_progress += 1

                    apply_multivariate = accuracy is not None and accuracy < 100.0
                    if apply_multivariate:
                        _write_debug(
                            f"Note: Accuracy {accuracy:.1f}% < 100%. Attempting Multivariate improvement..."
                        )
                    else:
                        _write_debug(
                            f"Note: Accuracy {accuracy}% >= 100% or None. Skipping Multivariate."
                        )

                    if apply_multivariate:
                        mv = MultivariateEngine(selected_regions=selected_regions)
                        mv_res = mv.run_multivariate(
                            train_series, test_series_clean, test_series_raw,
                            X_external_train=X_train_ext,
                            X_external_test=X_test_ext,
                            debug=True,
                            logger_func=lambda name, w, m, mp, acc: log_experiment(
                                sheet, metric, "Multivariate", name, w, m, mp, acc
                            ),
                            horizon=safe_horizon,
                            test_size=test_window,
                        )

                        feature_importance_dict = {}
                        if "best_model_object" in mv_res:
                            model_obj = mv_res["best_model_object"]
                            actual_feature_names = mv_res.get("top_features", [])
                            try:
                                if hasattr(model_obj, 'feature_importances_'):
                                    importances = model_obj.feature_importances_
                                    feature_importance_dict = dict(
                                        zip(actual_feature_names, [float(i) for i in importances])
                                    )
                                elif hasattr(model_obj, 'coef_'):
                                    importances = np.abs(model_obj.coef_).flatten()
                                    feature_importance_dict = dict(
                                        zip(actual_feature_names, [float(i) for i in importances])
                                    )
                                feature_importance_dict = {
                                    k: round(v, 4)
                                    for k, v in sorted(
                                        feature_importance_dict.items(),
                                        key=lambda x: x[1], reverse=True
                                    )[:10]
                                    if v > 0
                                }
                            except Exception as e:
                                _write_debug(f"Feature Importance Error: {e}")

                        _write_debug(
                            f"Multivariate Best: {mv_res.get('best_model')} | "
                            f"WMAPE={mv_res.get('wmape'):.2%}"
                        )

                        uni_score = external_wmape if external_wmape is not None else 1.0
                        mv_score = mv_res["wmape"] if mv_res["wmape"] is not None else 1.0
                        mv_std = mv_res["forecast"].std()
                        is_not_flat = mv_std > 1e-6
                        significant_improvement = mv_score < (uni_score * 0.95)
                        forecast_std = forecast_series.std() if forecast_series is not None else 0.0

                        if significant_improvement and is_not_flat or (
                            mv_score < uni_score and is_not_flat and mv_std >= 0.3 * forecast_std
                        ):
                            _write_debug(
                                f"SUCCESS: Multivariate Model Accepted ({mv_res.get('best_model')})."
                            )
                            best_name = mv_res["best_model"]
                            test_pred_series = mv_res["test_pred"].clip(lower=0.0)
                            forecast_series = mv_res["forecast"].clip(lower=0.0)
                            test_pred_series = dh.apply_business_rules(test_pred_series)
                            forecast_series = dh.apply_business_rules(forecast_series)
                            scores = calculate_performance_metrics(test_series_raw, test_pred_series)
                            log_experiment(
                                sheet, metric, "Multivariate", best_name,
                                scores["wmape"], scores["mae"], scores["mape"], scores["accuracy"]
                            )
                            records = build_records(
                                train_series=train_series, test_series=test_series_raw,
                                test_pred_series=test_pred_series, forecast_series=forecast_series,
                                train_series_raw=train_raw, df_x_clean=df_x_clean,
                            )
                            metric_finalized = True
                            sheet_metrics[metric] = {
                                "best_model": best_name,
                                "wmape": scores["wmape"], "mae": scores["mae"],
                                "mape": scores["mape"], "rmse": scores.get("rmse"),
                                "accuracy": scores["accuracy"],
                                "composite_score": scores.get("composite_score"),
                                "adi": adi_val, "cv2": cv2_val,
                                "demand_type": demand_type,
                                "demand_profile": demand_profile.to_dict(),
                                "records": records,
                                "x_vars": selected_x_cols,
                                "y_treatment": y_config,
                                "feature_importance": feature_importance_dict,
                                "forecast_bias": float(
                                    (test_series_raw.sum() - test_pred_series.sum())
                                    / (test_series_raw.sum() + 1e-6)
                                ),
                            }
                            metric_completed = True
                            metric_success = True
                        else:
                            _write_debug("Multivariate did not improve results. Keeping Univariate.")

                    # ── Stage 5: Finalise ──────────────────────────
                    _emit_status(job_id, total_tasks, current_progress, "Stage 5/5: Finalizing Forecast...", redis_url=redis_url)
                    current_progress += 1

                    if forecast_series is None:
                        forecast_series = fe.run_fallback_model(full_clean_series)

                    forecast_series = forecast_series.clip(lower=0.0)
                    test_pred_series = dh.apply_business_rules(test_pred_series)
                    forecast_series = dh.apply_business_rules(forecast_series)

                    # Floor enforcement
                    last_quarter = train_series.tail(90)
                    is_sparse_metric = zero_ratio > 0.10
                    if not is_sparse_metric:
                        non_zero = last_quarter[last_quarter > 0]
                        if not non_zero.empty:
                            floor = max(float(non_zero.quantile(0.10)), float(non_zero.min()))
                            min_allowed = floor * 0.9
                            forecast_series = forecast_series.where(
                                forecast_series >= min_allowed, other=min_allowed
                            )

                    final_accuracy = round(float(accuracy), 2) if accuracy is not None else None

                    if not metric_finalized:
                        common_idx = test_series_raw.index.intersection(test_pred_series.index)
                        val_mae = mae(test_series_raw.loc[common_idx], test_pred_series.loc[common_idx])
                        val_mape = mape(test_series_raw.loc[common_idx], test_pred_series.loc[common_idx])
                        val_rmse = rmse(test_series_raw.loc[common_idx], test_pred_series.loc[common_idx])
                        records = build_records(
                            train_series=train_series, test_series=test_series_raw,
                            test_pred_series=test_pred_series, forecast_series=forecast_series,
                            train_series_raw=train_raw, df_x_clean=df_x_clean,
                        )
                        sheet_metrics[metric] = {
                            "best_model": best_name,
                            "wmape": external_wmape, "mae": val_mae,
                            "mape": val_mape, "rmse": val_rmse,
                            "adi": adi_val, "cv2": cv2_val,
                            "demand_type": demand_type,
                            "demand_profile": demand_profile.to_dict(),
                            "accuracy": final_accuracy,
                            "records": records,
                            "y_treatment": y_config,
                        }
                        metric_completed = True
                        metric_success = True

                    # Baseline comparison
                    if baseline_wmape is not None and metric_success and metric in sheet_metrics:
                        current_best_wmape = sheet_metrics[metric].get("wmape") or float("inf")
                        if baseline_wmape < current_best_wmape:
                            _write_debug("Notice: Baseline (SMA) outperformed advanced models. Reverting.")
                            final_base_res = fe._run_sma(full_clean_series, None)
                            base_scores = calculate_performance_metrics(test_series_raw, baseline_test_pred)
                            records = build_records(
                                train_series=train_series, test_series=test_series_raw,
                                test_pred_series=baseline_test_pred,
                                forecast_series=final_base_res.forecast if final_base_res else forecast_series,
                                train_series_raw=train_raw, df_x_clean=df_x_clean,
                            )
                            sheet_metrics[metric] = {
                                "best_model": "Baseline_SMA",
                                "wmape": base_scores["wmape"], "mae": base_scores["mae"],
                                "mape": base_scores["mape"], "accuracy": base_scores["accuracy"],
                                "adi": adi_val, "cv2": cv2_val,
                                "demand_type": demand_type,
                                "demand_profile": demand_profile.to_dict(),
                                "records": records,
                                "y_treatment": y_config,
                            }
                            best_name = "Baseline_SMA"
                            if final_base_res:
                                forecast_series = final_base_res.forecast

                    # Figure
                    try:
                        hist_df = pd.DataFrame({
                            "Date": pd.to_datetime(train_series.index),
                            "Actual": train_series.values,
                        })
                        future_df = pd.DataFrame({
                            "Date": pd.to_datetime(forecast_series.index),
                            "Forecast": forecast_series.values,
                        })
                        fig = go.Figure()
                        if not hist_df.empty:
                            fig.add_trace(go.Scatter(
                                x=hist_df["Date"], y=hist_df["Actual"],
                                mode="lines+markers", name="Actual"
                            ))
                        if not future_df.empty:
                            fig.add_trace(go.Scatter(
                                x=future_df["Date"], y=future_df["Forecast"],
                                mode="lines+markers",
                                name=f"Forecast ({best_name})",
                                line=dict(dash="dash"),
                            ))
                        fig.update_layout(
                            title=f"{sheet} - {metric} (Best: {best_name})",
                            xaxis_title="Date", yaxis_title=metric,
                        )
                        sheet_figs[metric] = fig.to_dict()
                    except Exception as fig_err:
                        _write_debug(f"Error: Figure build failed for {sheet}/{metric}: {fig_err}")
                        sheet_figs[metric] = {}

                except Exception as metric_exc:
                    _write_debug(f"Error: Metric-level exception for {sheet}/{metric}: {metric_exc}")
                    with open(TRACEBACK_FILE, "w") as fh:
                        fh.write(traceback.format_exc())
                    sheet_metrics[metric] = {
                        "best_model": None, "wmape": None, "records": [],
                        "y_treatment": y_config if 'y_config' in locals() else {},
                    }
                    metric_completed = True
                    metric_success = False
                    sheet_figs[metric] = {}
                    remaining = current_progress % 5
                    if remaining != 0:
                        current_progress += (5 - remaining)

                finally:
                    if fe is not None and original_models:
                        fe.models = original_models
                    if metric_completed:
                        done_count += 1
                        remaining = current_progress % 5
                        if remaining != 0:
                            current_progress += (5 - remaining)
                        if metric_success:
                            _write_debug(f"SUCCESS: Completed forecasting for {sheet}/{metric}")
                        else:
                            _write_debug(f"FAILED: Metric {sheet}/{metric}")

            predictions_by_sheet[sheet] = {"metrics": sheet_metrics}
            figs_by_sheet[sheet] = sheet_figs

            try:
                with open(_job_pred_json(job_id), "w") as fh:
                    json.dump(predictions_by_sheet, fh, default=str, indent=2)
            except Exception:
                pass

        # Final writes
        try:
            with open(_job_pred_json(job_id), "w") as fh:
                json.dump(predictions_by_sheet, fh, default=str, indent=2)
        except Exception as e:
            _write_debug(f"Error: Failed writing predictions: {e}")

        try:
            with open(_job_figs_json(job_id), "w") as fh:
                json.dump(figs_by_sheet, fh, default=str, indent=2)
        except Exception as e:
            _write_debug(f"Error: Failed writing figures: {e}")

        end_time = time.time()
        duration = end_time - start_time
        time_str = (
            f"{int(duration // 60)}m {int(duration % 60)}s"
            if duration > 60 else f"{int(duration)}s"
        )

        _emit_status(
            job_id, total_tasks, total_tasks,
            f"Processing Completed. 100% (Execution Time: {time_str})",
            completed=True,
            redis_url=redis_url,
        )
        time.sleep(1.5)

        try:
            with open(DONE_FLAG, "w") as fh:
                fh.write(f"done:{datetime.now().isoformat()}\n")
        except Exception:
            pass

        _write_debug("SUCCESS: Execution completed successfully.")
        return predictions_by_sheet

    except InterruptedError:
        return predictions_by_sheet

    except Exception as e:
        _write_debug(f"CRITICAL processing worker exception: {e}")
        try:
            with open(TRACEBACK_FILE, "w") as fh:
                fh.write(traceback.format_exc())
        except Exception:
            pass
        return predictions_by_sheet
    finally:
        try:
            remove_lock()
        except Exception:
            pass


# ── Reader helpers ────────────────────────────────────────────────────
def read_predictions_and_figs(job_id: str):
    preds, figs = {}, {}
    pred_json = _job_pred_json(job_id)
    figs_json = _job_figs_json(job_id)
    try:
        if os.path.exists(pred_json):
            with open(pred_json, "r", encoding="utf-8") as fh:
                preds = json.load(fh)
    except Exception:
        preds = {}
    try:
        if os.path.exists(figs_json):
            with open(figs_json, "r", encoding="utf-8") as fh:
                figs = json.load(fh)
    except Exception:
        figs = {}
    return preds, figs


def read_progress(job_id: str) -> Dict[str, Any]:
    progress_data = {"percent": 0, "message": "Waiting..."}
    progress_json = _job_progress_json(job_id)
    if os.path.exists(progress_json):
        try:
            with open(progress_json, "r") as fh:
                progress_data = json.load(fh)
        except:
            pass
    if os.path.exists(DONE_FLAG):
        progress_data["percent"] = 100
        if "completed" not in progress_data.get("message", "").lower():
            progress_data["message"] = "Processing Completed."
    return progress_data


def read_log_tail(max_lines: int = 400) -> List[str]:
    if not os.path.exists(DEBUG_LOG):
        return []
    try:
        with open(DEBUG_LOG, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        return lines[-max_lines:] if len(lines) > max_lines else lines
    except Exception:
        return []