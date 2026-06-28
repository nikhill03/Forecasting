from __future__ import annotations

import base64
import io
import json
import logging
import os
import time
import traceback
from datetime import datetime
from typing import List, Optional, Dict, Any

import pandas as pd
import numpy as np
import plotly.graph_objects as go

# Local imports
from utils.forecasting import parse_uploaded_data
from services.forecasting_engine import ForecastingEngine
from services.data_handling import DataHandling
from utils.metrics import wmape, forecast_accuracy
from services.multivariate_engine import MultivariateEngine

# Paths / files
OUT_BASE = os.path.join(os.getcwd(), "outputs")
OUT_LOG_DIR = os.path.join(OUT_BASE, "logs")
OUT_PRED_DIR = os.path.join(OUT_BASE, "predictions")

os.makedirs(OUT_LOG_DIR, exist_ok=True)
os.makedirs(OUT_PRED_DIR, exist_ok=True)

LOCK_PATH = os.path.join(OUT_BASE, "processing.lock")
DONE_FLAG = os.path.join(OUT_BASE, "processing_done.flag")
PRED_JSON = os.path.join(OUT_PRED_DIR, "predictions_all.json")
FIGS_JSON = os.path.join(OUT_PRED_DIR, "figs_all.json")
DEBUG_LOG = os.path.join(OUT_LOG_DIR, "processing_debug.txt")
TRACEBACK_FILE = os.path.join(OUT_LOG_DIR, "processing_exception_traceback.txt")
PROGRESS_JSON = os.path.join(OUT_PRED_DIR, "progress.json")
STD_LOG = os.path.join(OUT_LOG_DIR, "processing.log")

# Logging setup
logger = logging.getLogger("dmc.processing")
logger.setLevel(logging.INFO)
if not logger.handlers:
    fh = logging.FileHandler(STD_LOG)
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)

# Helpers
def _now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _write_debug(msg: str) -> None:
    """
    Append a line to the debug log and the standard logger.
    """
    try:
        with open(DEBUG_LOG, "a") as f:
            f.write(f"[{_now_ts()}] {msg}\n")
    except Exception:
        pass
    logger.info(msg)

def normalize_upload_contents(contents) -> Optional[str]:
    """
    Normalize different upload representations to the base64 data string.
    """
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

def create_lock() -> bool:
    try:
        with open(LOCK_PATH, "w") as fh:
            fh.write(f"pid:{os.getpid() if hasattr(os, 'getpid') else 'unknown'} time:{time.time()}\n")
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
    """
    Remove previous run artifacts (careful in production).
    """
    for p in [PRED_JSON, FIGS_JSON, DONE_FLAG, DEBUG_LOG, TRACEBACK_FILE, PROGRESS_JSON]:
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass

def sma_forecast(series: pd.Series, window: int = 3, horizon: Optional[int] = None) -> pd.Series:
    """
    Simple moving average naive forecast used as fallback on very short series.
    horizon: number of future steps (if None, infer ~2 months by daily freq -> 60 steps).
    """
    if series.empty:
        return pd.Series(dtype=float)

    last_idx = series.index.max()
    try:
        freq = pd.infer_freq(series.index) or series.index.freqstr or "D"
    except Exception:
        freq = "D"

    if horizon is None:
        if "M" in str(freq):
            horizon = 2
        elif "W" in str(freq):
            horizon = 8
        else:
            horizon = 60

    try:
        future_idx = pd.date_range(start=last_idx + pd.Timedelta(days=1), periods=horizon, freq=freq)
    except Exception:
        # fallback to daily
        future_idx = pd.date_range(start=last_idx + pd.Timedelta(days=1), periods=horizon, freq="D")

    mean_val = float(series.dropna().tail(window).mean()) if len(series.dropna()) else 0.0
    return pd.Series([mean_val] * len(future_idx), index=future_idx)


# Main worker
import time  # Ensure time is imported

def processing_worker(file_contents_norm: str, selected_sheets_list: List[str], selected_metrics: Optional[List[str]] = None) -> None:
    total_tasks = 0
    try:
        _write_debug("Processing worker started.")

        # Parse uploaded file into dict of sheet -> df
        try:
            dfs = parse_uploaded_data(file_contents_norm)
            if not dfs or not isinstance(dfs, dict):
                _write_debug("Uploaded file parsing returned no sheets.")
                return
        except Exception as e:
            _write_debug(f"Error parsing uploaded file: {e}")
            # Try fallback manual decode -> pandas
            try:
                if "," in file_contents_norm:
                    _, b64 = file_contents_norm.split(",", 1)
                else:
                    b64 = file_contents_norm
                decoded = base64.b64decode(b64)
                xl = pd.ExcelFile(io.BytesIO(decoded))
                dfs = {s: xl.parse(s) for s in xl.sheet_names}
            except Exception as e2:
                _write_debug(f"Fallback parsing failed: {e2}")
                return


        # Write initial progress
        try:
            with open(PROGRESS_JSON, "w") as fh:
                json.dump({"total": total_tasks, "done": 0, "started_at": datetime.now().isoformat()}, fh)
        except Exception:
            pass

        # 3) Prepare forecasting engine
        fe = None
        try:
            fe = ForecastingEngine(freq="D")
        except Exception as e:
            _write_debug(f"ForecastingEngine instantiation failed: {e}")
            fe = None

        predictions_by_sheet: Dict[str, Any] = {}
        figs_by_sheet: Dict[str, Any] = {}
        done_count = 0

        # 4) Iterate sheets -> metrics
        for sheet in (selected_sheets_list or []):
            _write_debug(f"Processing sheet: {sheet}")
            df_raw = dfs.get(sheet)
            if df_raw is None:
                _write_debug(f"Sheet {sheet} missing in parsed sheets.")
                predictions_by_sheet[sheet] = {"metrics": {}}
                figs_by_sheet[sheet] = {}
                continue

            # detect date column
            date_col = None
            for c in df_raw.columns:
                if "date" in str(c).lower():
                    date_col = c
                    break

            df = df_raw.copy()
            if date_col:
                df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
                df = df.dropna(subset=[date_col]).set_index(date_col).sort_index()
            else:
                # try to coerce index
                try:
                    df.index = pd.to_datetime(df.index)
                except Exception:
                    _write_debug(f"Sheet {sheet}: no date column and index is not datetime. Skipping sheet.")
                    predictions_by_sheet[sheet] = {"metrics": {}}
                    figs_by_sheet[sheet] = {}
                    continue

            # determine metrics to run (authoritative)
            if selected_metrics and len(selected_metrics) > 0:
                metrics_to_run = [m for m in selected_metrics if m in df.columns]
            else:
                metrics_to_run = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
            
            metrics_to_run = list(dict.fromkeys(metrics_to_run))

            total_tasks = total_tasks + len(metrics_to_run)

            # write updated total immediately (first sheet only grows)
            with open(PROGRESS_JSON, "w") as fh:
                json.dump(
                    {
                        "total": total_tasks,
                        "done": done_count,
                        "started_at": datetime.now().isoformat()
                    },
                    fh
                )

            sheet_metrics: Dict[str, Any] = {}
            sheet_figs: Dict[str, Any] = {}

            for metric in metrics_to_run:
                metric_done = False
                try:
                    metric_finalized = False
                    _write_debug(f"Starting metric {sheet}/{metric}")
                    _write_debug(f"STEP: Preparing time series for {sheet}/{metric}")
                    # ---- DATA SANITIZATION (CRITICAL) ----
                    dh = DataHandling(
                        min_points=30,
                        max_fill_gap=2,
                        allow_negative=False
                    )

                    series, dh_logs = dh.sanitize(
                        df.reset_index(),
                        date_col=df.index.name if df.index.name else "Date",
                        metric_col=metric
                    )
                    train_series, test_series = fe._train_test_split(series)

                    if isinstance(series.index, pd.DatetimeIndex):
                        if series.index.freq is None and series.index.inferred_freq is None:
                            _write_debug(
                                f"{sheet}/{metric}: WARN irregular timestamps, no frequency enforced (business-safe)"
                            )

                    for msg in dh_logs:
                        _write_debug(f"{sheet}/{metric}: {msg}")

                    if series is None or series.empty:
                        _write_debug(f"{sheet}/{metric}: series unusable after sanitization, skipping.")
                        sheet_metrics[metric] = {"best_model": None, "wmape": None, "records": []}
                        sheet_figs[metric] = {}
                        if not metric_done:
                            metric_done = True
                            done_count += 1
                            progress_payload = {
                                "total": total_tasks,
                                "done": done_count,
                            }

                            if done_count >= total_tasks:
                                progress_payload["completed_at"] = datetime.now().isoformat()

                            with open(PROGRESS_JSON, "w") as fh:
                                json.dump(progress_payload, fh)
                                _write_debug(f"SUCCESS: Completed metric {sheet}/{metric}")
                            continue


                    # ---- DATA SHAPE METRICS ----
                    n_points = len(series)
                    zero_ratio = float((series == 0).sum()) / max(1, n_points)
                    _write_debug(f"{sheet}/{metric}: points={n_points}, zero_ratio={zero_ratio:.2%}")

                    # --- MODEL ROUTING BASED ON DATA SHAPE ---
                    mean_val = float(series.mean())
                    std_val = float(series.std())
                    cv = std_val / (mean_val + 1e-6)

                    # model allowlist (will be pruned)
                    allowed_models = {"TBATS", "Prophet", "LightGBM", "HistGB", "ExpSmoothing", "SARIMAX"}

                    # ---- LOW VOLUME METRICS ----
                    if mean_val < 10:
                        _write_debug(f"{sheet}/{metric}: low-volume metric (mean={mean_val:.2f}) → disabling Prophet & SARIMAX")
                        allowed_models.discard("Prophet")
                        allowed_models.discard("SARIMAX")

                    # ---- ZERO HEAVY SERIES ----
                    if zero_ratio > 0.8:
                        _write_debug(f"{sheet}/{metric}: many zeros ({zero_ratio:.0%}) → disabling Prophet")
                        allowed_models.discard("Prophet")

                    # apply gating to forecasting engine
                    if fe is not None:
                        # ---- PER-METRIC MODEL SET (NO SHARED STATE) ----
                        models_to_run = {
                            "TBATS": fe._run_tbats,
                            "Prophet": fe._run_prophet,
                            "LightGBM": fe._run_lightgbm,
                            "HistGB": fe._run_hist_gb,
                            "ExpSmoothing": fe._run_expsmoothing,
                            "SARIMAX": fe._run_sarimax,
                        }
                        models_to_run = {k: v for k, v in models_to_run.items() if k in allowed_models}
                        fe.models = models_to_run.copy()

                        _write_debug(f"{sheet}/{metric}: allowed models = {list(fe.models.keys())}")

                    # High volatility → SARIMAX unstable
                    if cv > 1.5 and fe is not None:
                        fe.models.pop("SARIMAX", None)
                        _write_debug(f"{sheet}/{metric}: SARIMAX disabled (high volatility)")

                    # Very low-volume metrics → WMAPE unreliable
                    if series.mean() < 5:
                        _write_debug(f"{sheet}/{metric}: low-volume metric, accuracy may be unreliable")

                    if series.empty:
                        _write_debug(f"{sheet}/{metric}: empty series, skipping.")
                        sheet_metrics[metric] = {"best_model": None, "wmape": None, "records": []}
                        sheet_figs[metric] = {}
                        if not metric_done:
                            metric_done = True
                            done_count += 1
                            try:
                                with open(PROGRESS_JSON, "w") as fh:
                                    json.dump(
                                        {"total": total_tasks, "done": done_count},
                                        fh
                                    )
                                _write_debug(f"SUCCESS: Completed metric {sheet}/{metric}")
                            except Exception:
                                pass
                            continue

                    # ---- HARD BUSINESS FALLBACKS (ROLLING AVERAGE) ----
                    if n_points < 90 or (zero_ratio > 0.7 and mean_val < 5):
                        _write_debug(
                            f"{sheet}/{metric}: triggering ROLLING_AVG fallback "
                            f"(n_points={n_points}, zero_ratio={zero_ratio:.2%})"
                        )

                        clipped = series.clip(lower=series.quantile(0.05),upper=series.quantile(0.95),)
                        roll = (clipped.rolling(window=14, min_periods=7).median().rolling(window=7, min_periods=3).mean())

                        base_val = float(roll.dropna().iloc[-1])
                        horizon = fe._forecast_steps_for_2_months(series.index)
                        future_idx = fe._future_index(series.index.max(), horizon)

                        seasonal = roll.dropna().tail(14).values
                        seasonal_center = seasonal - np.mean(seasonal)
                        forecast_vals = [
                            base_val + seasonal_center[i % len(seasonal_center)]
                            for i in range(horizon)
                        ]

                        forecast = pd.Series(forecast_vals, index=future_idx)

                        records = []

                        for dt, val in train_series.items():
                            records.append({
                                "Date": pd.to_datetime(dt),
                                "TrainActual": 0.0 if (val is None or pd.isna(val)) else float(val),
                                "TestActual": None,
                                "TestPrediction": None,
                                "Forecast": None,
                            })

                        for dt, val in test_series.items():
                            records.append({
                                "Date": pd.to_datetime(dt),
                                "TrainActual": None,
                                "TestActual": 0.0 if (val is None or pd.isna(val)) else float(val),
                                "TestPrediction": None,
                                "Forecast": None,
                            })

                        for dt, val in forecast.items():
                            records.append({
                                "Date": pd.to_datetime(dt),
                                "TrainActual": None,
                                "TestActual": None,
                                "TestPrediction": None,
                                "Forecast": 0.0 if (val is None or pd.isna(val)) else float(val),
                            })

                        sheet_metrics[metric] = {"best_model": "RollingAvg","wmape": None,"accuracy": None,"records": records}
                        sheet_figs[metric] = {}
                        if not metric_done:
                            metric_done = True
                            done_count += 1
                            try:
                                with open(PROGRESS_JSON, "w") as fh:
                                    json.dump(
                                        {"total": total_tasks, "done": done_count},
                                        fh
                                    )
                                _write_debug(f"SUCCESS: Completed metric {sheet}/{metric}")
                            except Exception:
                                pass
                            continue

                    # run all models in the forecasting engine, pick best by wmape
                    try:
                        res = fe.select_best_and_forecast(series)
                        best_name = res[0]
                        best_res = res[1]

                        forecast_series = None
                        if best_res is not None:
                            try:
                                # ---------------------------------------------------------
                                # BUG FIX 1 (CORRECTED): RETRAIN ON FULL DATA
                                # Use a Dummy Test Set (last point) to prevent model crashes
                                # ---------------------------------------------------------
                                runner = fe.models.get(best_res.name)
                                if runner is not None:
                                    # Create a dummy test set using the last actual data point.
                                    # This prevents "Index out of bounds" errors in SARIMAX/TBATS.
                                    dummy_test = series.iloc[-1:]
                                    
                                    # Retrain on 'series' (100% data)
                                    refit_res = runner(series, dummy_test)
                                    
                                    if refit_res is not None and hasattr(refit_res, "forecast"):
                                        forecast_series = refit_res.forecast.copy()

                                        if not forecast_series.empty:
                                            # STRICTLY enforce the start date to be AFTER the last data point
                                            horizon = len(forecast_series)
                                            forecast_series.index = fe._future_index(
                                                series.index.max(), 
                                                horizon
                                            )
                                # If runner not found (e.g. Fallback model), use existing forecast
                                elif hasattr(best_res, 'forecast'):
                                     forecast_series = best_res.forecast.copy()

                            except Exception as e:
                                _write_debug(f"{sheet}/{metric}: full-series refit failed → {e}")
                                # Fallback to original (overlapping) forecast ONLY if refit crashes
                                if hasattr(best_res, 'forecast'):
                                    forecast_series = best_res.forecast.copy()

                        test_pred_series = best_res.predictions_test

                        if test_pred_series is not None and test_series is not None:
                            test_pred_series = test_pred_series.reindex(test_series.index)


                        if test_series is not None and test_pred_series is not None:
                            non_zero_test = test_series[test_series != 0]
                            if len(non_zero_test) >= max(3, int(0.3 * len(test_series))):
                                accuracy = forecast_accuracy(test_series, test_pred_series)
                            else:
                                accuracy = None

                        _write_debug(
                            f"STEP: Model selection completed for {sheet}/{metric} | "
                            f"BestModel={best_name} | WMAPE={best_res.wmape}"
                        )

                    except Exception as model_err:
                        _write_debug(f"{sheet}/{metric}: model suite failed: {model_err}")
                        # fallback to SMA
                        fc = sma_forecast(series)
                        test_pred_series = pd.Series(
                            [train_series.iloc[-1]] * len(test_series),
                            index=test_series.index
                        )

                        best_res = type("SMAResult",(), {"forecast": fc})
                        records = []

                        # Train actuals
                        for dt, val in train_series.items():
                            records.append({
                                "Date": pd.to_datetime(dt),
                                "TrainActual": 0.0 if (val is None or pd.isna(val)) else float(val),
                                "TestActual": None,
                                "TestPrediction": None,
                                "Forecast": None,
                            })

                        # Test actuals
                        for dt, val in test_series.items():
                            records.append({
                                "Date": pd.to_datetime(dt),
                                "TrainActual": None,
                                "TestActual": 0.0 if (val is None or pd.isna(val)) else float(val),
                                "TestPrediction": None,
                                "Forecast": None,
                            })

                        # Test predictions
                        for dt, val in test_pred_series.items():
                            records.append({
                                "Date": pd.to_datetime(dt),
                                "TrainActual": None,
                                "TestActual": None,
                                "TestPrediction": 0.0 if (val is None or pd.isna(val)) else float(val),
                                "Forecast": None,
                            })
                        
                        # Future forecast
                        for dt, val in fc.items():
                            records.append({
                                "Date": pd.to_datetime(dt),
                                "TrainActual": None,
                                "TestActual": None,
                                "TestPrediction": None,
                                "Forecast": 0.0 if (val is None or pd.isna(val)) else float(val),
                            })

                        sheet_metrics[metric] = {"best_model": "SMA_on_error", "wmape": None, "accuracy":None, "records": records}
                        sheet_figs[metric] = {}
                        if not metric_done:
                            metric_done = True
                            done_count += 1
                            try:
                                with open(PROGRESS_JSON, "w") as fh:
                                    json.dump(
                                        {"total": total_tasks, "done": done_count},
                                        fh
                                    )
                                _write_debug(f"SUCCESS: Completed metric {sheet}/{metric}")
                            except Exception:
                                pass
                            continue

                    # Build combined records (Default Path)
                    records = []

                    # Train actuals
                    for dt, val in train_series.items():
                        records.append({
                            "Date": pd.to_datetime(dt),
                            "TrainActual": 0.0 if (val is None or pd.isna(val)) else float(val),
                            "TestActual": None,
                            "TestPrediction": None,
                            "Forecast": None,
                        })

                    # Test actuals
                    for dt, val in test_series.items():
                        records.append({
                            "Date": pd.to_datetime(dt),
                            "TrainActual": None,
                            "TestActual": 0.0 if (val is None or pd.isna(val)) else float(val),
                            "TestPrediction": None,
                           "Forecast": None,
                        })

                    # Test predictions
                    for dt, val in test_pred_series.items():
                        records.append({
                            "Date": pd.to_datetime(dt),
                            "TrainActual": None,
                            "TestActual": None,
                            "TestPrediction": 0.0 if (val is None or pd.isna(val)) else float(val),
                            "Forecast": None,
                        })                    

                    # Future forecast
                    for dt, val in forecast_series.items():
                        records.append({
                            "Date": pd.to_datetime(dt),
                            "TrainActual": None,
                            "TestActual": None,
                            "TestPrediction": None,
                            "Forecast": 0.0 if (val is None or pd.isna(val)) else float(val),
                        })    
                                    
                    apply_multivariate = False
                    accuracy_pct = accuracy             

                    if accuracy_pct is not None and accuracy_pct <50.0:
                        apply_multivariate = True
                        _write_debug(
                            f"{sheet}/{metric}: accuracy {accuracy_pct:.2f}% < 50% (Too Low) → triggering multivariate"
                        )
                    elif accuracy_pct is not None:
                         _write_debug(
                            f"{sheet}/{metric}: accuracy {accuracy_pct:.2f}% >= 50% (Acceptable) → keeping univariate"
                        )

                    # ---- MULTIVARIATE ESCALATION (FIXED) ----
                    if apply_multivariate:
                        
                        mv = MultivariateEngine(country="US")
                        mv_res = mv.run_multivariate(series)

                        _write_debug(
                            f"{sheet}/{metric}: STEP: Multivariate model selection completed | "
                            f"BestModel={mv_res.get('best_model')} | "
                            f"WMAPE={mv_res.get('wmape'):.4f} | "
                            f"Accuracy={forecast_accuracy(mv_res['test'], mv_res['test_pred']):.2f}%"
                        )

                        uni_score = best_res.wmape if best_res.wmape is not None else 1.0
                        mv_score = mv_res["wmape"] if mv_res["wmape"] is not None else 1.0

                        _write_debug(
                            f"{sheet}/{metric}: WMAPE comparison | "
                            f"univariate={uni_score:.4f}, multivariate={mv_score:.4f}"
                        )

                        is_better = mv_score < uni_score
                        
                        mv_std = mv_res["forecast"].std()
                        is_not_flat = mv_std > 1e-6
                        significant_improvement = mv_score < (uni_score * 0.95)
                        
                        if (significant_improvement and is_not_flat) or (is_better and is_not_flat and mv_std >= 0.3 * forecast_series.std()):
                            _write_debug(f"{sheet}/{metric}: multivariate ACCEPTED")

                            # Update series with multivariate results
                            train_series = mv_res["train"]
                            test_series = mv_res["test"]
                            test_pred_series = mv_res["test_pred"]
                            forecast_series = mv_res["forecast"]

                            # Rebuild records for Multivariate
                            records = []

                            for dt, val in train_series.items():
                                records.append({
                                    "Date": pd.to_datetime(dt),
                                    "TrainActual": float(val),
                                    "TestActual": None,
                                    "TestPrediction": None,
                                    "Forecast": None,
                                })

                            for dt, actual, pred in zip(
                                test_series.index,
                                test_series.values,
                                test_pred_series.values
                            ):
                                records.append({
                                    "Date": pd.to_datetime(dt),
                                    "TrainActual": None,
                                    "TestActual": float(actual),
                                    "TestPrediction": float(pred),
                                    "Forecast": None,
                                })

                            for dt, val in forecast_series.items():
                                records.append({
                                    "Date": pd.to_datetime(dt),
                                    "TrainActual": None,
                                    "TestActual": None,
                                    "TestPrediction": None,
                                    "Forecast": float(val),
                                })

                            sheet_metrics[metric] = {
                                "best_model": mv_res["best_model"],
                                "wmape": mv_res["wmape"],
                                "accuracy": forecast_accuracy(
                                    mv_res["test"],
                                    mv_res["test_pred"]
                                ),
                                "records": records,
                            }
                            
                            # CRITICAL FIX: Mark metric as finalized so default logic doesn't overwrite it
                            metric_finalized = True 
                            
                            # CRITICAL FIX: REMOVED `continue` and duplicate logging
                            # Logic will now flow down to 'Business Floor', 'Figures', and 'Progress Update'
                            
                        else:
                            _write_debug(
                                f"{sheet}/{metric}: multivariate REJECTED (univariate is better)"
                            )
                            # Logic continues using original univariate results

                    # ---- BUSINESS FLOOR GUARDRAIL ----
                    # This now applies to both Univariate AND Multivariate results
                    last_quarter = series.tail(90)
                    non_zero = last_quarter[last_quarter > 0]

                    floor = 0.0
                    if not non_zero.empty:
                        floor = max(float(non_zero.quantile(0.10)),float(non_zero.min()))
                    
                    if forecast_series is None:
                        forecast_series = sma_forecast(series)
                    
                    if floor > 0:
                        min_allowed = floor * 0.9
                        forecast_series = forecast_series.where(
                            forecast_series >= min_allowed,
                            other=min_allowed
                        )

                    
                    if accuracy is not None:
                        final_accuracy = round(float(accuracy), 2)
                    else:
                        final_accuracy = None

                    # Only save standard metrics if Multivariate didn't already save them
                    if not metric_finalized:
                        sheet_metrics[metric] = {
                            "best_model": best_name,
                            "wmape": best_res.wmape,
                            "accuracy": final_accuracy,
                            "records": records,
                        }

                    _write_debug(f"SUCCESS: Completed metric {sheet}/{metric}")

                    # small figure for UI
                    try:
                        hist_df = pd.DataFrame({"Date": pd.to_datetime(series.index), "Actual": series.values})
                        future_df = pd.DataFrame({"Date": pd.to_datetime(forecast_series.index), "Forecast": forecast_series.values})
                        fig = go.Figure()
                        if not hist_df.empty:
                            fig.add_trace(go.Scatter(x=hist_df["Date"], y=hist_df["Actual"], mode="lines+markers", name="Actual"))
                        if not future_df.empty:
                            fig.add_trace(go.Scatter(x=future_df["Date"], y=future_df["Forecast"], mode="lines+markers", name=f"Forecast ({best_name})", line=dict(dash="dash")))
                        fig.update_layout(title=f"{sheet} - {metric} (Best: {best_name})", xaxis_title="Date", yaxis_title=metric)
                        sheet_figs[metric] = fig.to_dict()
                    except Exception as fig_err:
                        _write_debug(f"Figure build failed for {sheet}/{metric}: {fig_err}")
                        sheet_figs[metric] = {}
                
                    if not metric_done:
                        metric_done = True
                        done_count += 1
                        try:
                            with open(PROGRESS_JSON, "w") as fh:
                                json.dump(
                                    {"total": total_tasks, "done": done_count},
                                    fh
                                )
                            _write_debug(f"SUCCESS: Completed metric {sheet}/{metric}")
                        except Exception:
                            pass
                        continue

                except Exception as metric_exc:
                    _write_debug(f"Metric-level exception for {sheet}/{metric}: {metric_exc}")
                    with open(TRACEBACK_FILE, "w") as fh:
                        fh.write(traceback.format_exc())
                    sheet_metrics[metric] = {"best_model": None, "wmape": None, "records": []}
                    sheet_figs[metric] = {}
                    if not metric_done:
                        metric_done = True
                        done_count += 1
                        try:
                            with open(PROGRESS_JSON, "w") as fh:
                                json.dump(
                                    {"total": total_tasks, "done": done_count},
                                    fh
                                )
                            _write_debug(f"SUCCESS: Completed metric {sheet}/{metric}")
                        except Exception:
                            pass
                        continue
            
            predictions_by_sheet[sheet] = {"metrics": sheet_metrics}
            figs_by_sheet[sheet] = sheet_figs

            # write partial outputs for UI responsiveness
            try:
                with open(PRED_JSON, "w") as fh:
                    json.dump(predictions_by_sheet, fh, default=str, indent=2)
            except Exception:
                pass

        # final writes
        try:
            with open(PRED_JSON, "w") as fh:
                json.dump(predictions_by_sheet, fh, default=str, indent=2)
        except Exception as e:
            _write_debug(f"Failed writing {PRED_JSON}: {e}")

        try:
            with open(FIGS_JSON, "w") as fh:
                json.dump(figs_by_sheet, fh, default=str, indent=2)
        except Exception as e:
            _write_debug(f"Failed writing {FIGS_JSON}: {e}")

        try:
            with open(PROGRESS_JSON, "w") as fh:
                json.dump({"total": total_tasks, "done": total_tasks, "completed_at": datetime.now().isoformat()}, fh)
        except Exception:
            pass
        
        # CRITICAL FIX: Pause to allow UI to poll the "100%" state
        time.sleep(1.5)

        try:
            with open(DONE_FLAG, "w") as fh:
                fh.write(f"done:{datetime.now().isoformat()}\n")
        except Exception:
            pass

        _write_debug("SUCCESS: Execution completed successfully.")

    except Exception as e:
        _write_debug(f"CRITICAL processing worker exception: {e}")
        try:
            with open(TRACEBACK_FILE, "w") as fh:
                fh.write(traceback.format_exc())
        except Exception:
            pass
    finally:
        try:
            remove_lock()
        except Exception:
            pass

# Reader helpers for callbacks
def read_predictions_and_figs():
    preds = {}
    figs = {}
    try:
        if os.path.exists(PRED_JSON):
            with open(PRED_JSON, "r") as fh:
                preds = json.load(fh)
    except Exception:
        preds = {}
    try:
        if os.path.exists(FIGS_JSON):
            with open(FIGS_JSON, "r") as fh:
                figs = json.load(fh)
    except Exception:
        figs = {}
    return preds, figs

def read_progress() -> Dict[str, Any]:
    if not os.path.exists(PROGRESS_JSON):
        return {}
    try:
        with open(PROGRESS_JSON, "r") as fh:
            return json.load(fh)
    except Exception:
        return {}

def read_log_tail(max_lines: int = 400) -> List[str]:
    if not os.path.exists(DEBUG_LOG):
        return []
    try:
        with open(DEBUG_LOG, "r") as fh:
            lines = fh.read().splitlines()
        return lines[-max_lines:] if len(lines) > max_lines else lines
    except Exception:
        return []
