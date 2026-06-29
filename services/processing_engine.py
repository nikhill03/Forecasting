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

# Local imports
from utils.forecasting import parse_uploaded_data
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
STOP_FLAG = os.path.join(OUT_BASE, "processing_stop.flag")
PRED_JSON = os.path.join(OUT_PRED_DIR, "predictions_all.json")
FIGS_JSON = os.path.join(OUT_PRED_DIR, "figs_all.json")
DEBUG_LOG = os.path.join(OUT_LOG_DIR, "processing_debug.txt")
TRACEBACK_FILE = os.path.join(OUT_LOG_DIR, "processing_exception_traceback.txt")
PROGRESS_JSON = os.path.join(OUT_PRED_DIR, "progress.json")
STD_LOG = os.path.join(OUT_LOG_DIR, "processing.log")
HISTORY_LOG = os.path.join(OUT_LOG_DIR, "model_history.csv")

# Logging setup
logger = logging.getLogger("dmc.processing")
logger.setLevel(logging.INFO)

if not logger.handlers:
    fh = logging.FileHandler(STD_LOG, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)

# Helper function
def _now_ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _emit_status(total, done, message, completed=False):
    if os.path.exists(STOP_FLAG):
        stop_data = {
            "percent": int((done / total) * 100) if total > 0 else 0,
            "message": "🛑 Execution Stopped by User",
            "status": "stopped",
            "timestamp": datetime.now().isoformat()
        }
        try:
            directory = os.path.dirname(PROGRESS_JSON)
            fd, temp_path = tempfile.mkstemp(dir=directory, text=True)
            with os.fdopen(fd, 'w') as fh: json.dump(stop_data, fh)
            os.replace(temp_path, PROGRESS_JSON)
        except: pass
            
        _write_debug("🛑 Execution STOPPED: Thread terminating immediately.")
        raise InterruptedError("Stopped by user")

    percent = 0
    if total > 0:
        percent = int((done / total) * 100)
    elif completed:
        percent = 100
        
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
        directory = os.path.dirname(PROGRESS_JSON)
        fd, temp_path = tempfile.mkstemp(dir=directory, text=True)
        with os.fdopen(fd, 'w') as fh: 
            json.dump(data, fh)
        
        success = False
        for i in range(5):
            try:
                os.replace(temp_path, PROGRESS_JSON)
                success = True
                break
            except PermissionError:
                time.sleep(0.05) 
        
        if not success:
            print(f"[Engine] Final attempt to update status failed due to file lock.")
            
    except Exception as e:
        print(f"[Engine] Status Write Error: {e}")
    finally:
        if os.path.exists(temp_path):
            try: os.remove(temp_path)
            except: pass

def _write_debug(msg: str) -> None:
    try:
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
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

def parse_uploaded_data_robust(content_string) -> Dict[str, pd.DataFrame]:
    """
    Parses upload content (CSV or Excel) into a dict of {SheetName: DataFrame}.
    Handles errors gracefully and supports CSVs explicitly.
    """
    try:
        if not content_string: return {}
        
        if ',' in content_string:
            _, content_string = content_string.split(',')
            
        decoded = base64.b64decode(content_string)
        
        try:
            xls = pd.ExcelFile(io.BytesIO(decoded))
            return {s: xls.parse(s) for s in xls.sheet_names}
        except:
            try:
                df = pd.read_csv(io.BytesIO(decoded))
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

def log_experiment(sheet, metric, stage, model_name,
                   wmape_val, mae_val, mape_val, accuracy_val,
                   rmse_val=None):   # NEW: rmse_val param
    try:
        if not os.path.exists(HISTORY_LOG):
            with open(HISTORY_LOG, "w") as f:
                r   = f"{rmse_val:.5f}" if rmse_val is not None else ""
                f.write(f"{timestamp},{sheet},{metric},{stage},{model_name},{w},{m},{mp},{r},{acc}\n")
 
        with open(HISTORY_LOG, "a") as f:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            w   = f"{wmape_val:.5f}"  if wmape_val   is not None else ""
            m   = f"{mae_val:.5f}"    if mae_val     is not None else ""
            mp  = f"{mape_val:.5f}"   if mape_val    is not None else ""
            r   = f"{rmse_val:.5f}"   if rmse_val    is not None else ""  # NEW
            acc = f"{accuracy_val:.2f}" if accuracy_val is not None else ""
            f.write(f"{timestamp},{sheet},{metric},{stage},{model_name},{w},{m},{mp},{r},{acc}\\n")
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
                "Date": dt,
                "TrainActual": None,
                "TrainRaw": None,
                "TestActual": None,
                "TestPrediction": None,
                "Forecast": None,
            }
        return records_by_date[dt]

    if train_series is not None:
        for dt, val in train_series.items():
            row = ensure_row(dt)
            row["TrainActual"] = None if (val is None or pd.isna(val)) else float(val)

    if train_series_raw is not None:
        for dt, val in train_series_raw.items():
            row = ensure_row(dt)
            row["TrainRaw"] = None if (val is None or pd.isna(val)) else float(val)

    if test_series is not None:
        for dt, val in test_series.items():
            row = ensure_row(dt)
            row["TestActual"] = None if (val is None or pd.isna(val)) else float(val)

    if test_pred_series is not None:
        for dt, val in test_pred_series.items():
            row = ensure_row(dt)
            row["TestPrediction"] = 0.0 if (val is None or pd.isna(val)) else float(val)

    if forecast_series is not None:
        for dt, val in forecast_series.items():
            row = ensure_row(dt)
            row["Forecast"] = 0.0 if (val is None or pd.isna(val)) else float(val)

    if df_x_clean is not None and not df_x_clean.empty:
        x_lookup = df_x_clean.to_dict(orient="index")
        for dt in records_by_date.keys():
            if dt in x_lookup:
                records_by_date[dt].update(x_lookup[dt])

    return sorted(records_by_date.values(), key=lambda r: r["Date"])

# Main worker
def processing_worker(file_contents_norm: str, selected_sheets_list: List[str], 
                      selected_metrics: Optional[List[str]] = None,
                      selected_x_cols: Optional[List[str]] = None, 
                      x_clean_weekday: str = "median", x_clean_weekend: str = "zero",
                      forecast_horizon: int = 60, 
                      test_window: int = 30, 
                      x_file_contents: Optional[str] = None, 
                      selected_regions: list = None) -> None:
    
    start_time = time.time()
    total_tasks = 0
    try:
        if os.path.exists(STOP_FLAG): os.remove(STOP_FLAG)
        if os.path.exists(DONE_FLAG): os.remove(DONE_FLAG)

        _write_debug("Pipeline execution started.")

        dfs = parse_uploaded_data_robust(file_contents_norm)

        if not dfs:
            _write_debug("Error: Uploaded file parsing returned no sheets. Please check the file format (CSV/Excel).")
            try:
                from utils.forecasting import parse_uploaded_data
                dfs = parse_uploaded_data(file_contents_norm)
            except:
                pass
            
            if not dfs:
                _write_debug("CRITICAL: Failed to parse input file. Aborting.")
                return

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

        _emit_status(0, 0, "Initializing forecasting engine...")

        predictions_by_sheet: Dict[str, Any] = {}
        figs_by_sheet: Dict[str, Any] = {}
        
        for sheet in (selected_sheets_list or []):
            df_raw = dfs.get(sheet)
            if df_raw is None: continue
            if selected_metrics:
                m_count = len([m for m in selected_metrics if m in df_raw.columns])
            else:
                m_count = len([c for c in df_raw.columns if pd.api.types.is_numeric_dtype(df_raw[c])])
            
            total_tasks += (m_count * 5) 
        
        current_progress = 0 
        done_count = 0

        # Console log begin
        for sheet in (selected_sheets_list or []):
            _write_debug(f" Processing Sheet: {sheet} ")
            df_raw = dfs.get(sheet)
            if df_raw is None:
                _write_debug(f"Error: Sheet '{sheet}' missing in parsed sheets.")
                predictions_by_sheet[sheet] = {"metrics": {}}
                figs_by_sheet[sheet] = {}
                continue

            date_col = None
            for c in df_raw.columns:
                if "date" in str(c).lower():
                    date_col = c
                    break

            df = df_raw.copy()
            if date_col:
                df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
                df = df.dropna(subset=[date_col]).set_index(date_col).sort_index()
                _write_debug(f"Identified Date Column: '{date_col}'")
            else:
                try:
                    df.index = pd.to_datetime(df.index)
                    _write_debug(f"Using Index as Date Column.")
                except Exception:
                    _write_debug(f"Error: No valid date column found in '{sheet}'. Skipping.")
                    predictions_by_sheet[sheet] = {"metrics": {}}
                    figs_by_sheet[sheet] = {}
                    continue

            # metrics to run
            if selected_metrics and len(selected_metrics) > 0:
                metrics_to_run = [m for m in selected_metrics if m in df.columns]
            else:
                metrics_to_run = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
            
            metrics_to_run = list(dict.fromkeys(metrics_to_run))
            
            _emit_status(total_tasks, current_progress, f"Analyzing sheet: {sheet}")

            sheet_metrics: Dict[str, Any] = {}
            sheet_figs: Dict[str, Any] = {}

            for metric in metrics_to_run:                

                # Stage 1 Sanitization 
                _emit_status(total_tasks, current_progress, f"Stage 1/5: Sanitizing {sheet}/{metric}...")
                time.sleep(1.0)
                current_progress += 1
                
                metric_completed = False
                metric_success = False

                try:
                    metric_finalized = False
                    accuracy = None
                    _write_debug(f"Analysis started for Target: {metric}")

                    # Data Sanitation
                    dh = DataHandling(
                        min_points=30,
                        allow_negative=False,
                        lookback_days = None
                    )

                    raw_series, dh_logs = dh.sanitize(
                        df.reset_index(),
                        date_col=df.index.name if df.index.name else "Date",
                        metric_col=metric
                    )

                    y_config = TreatmentAnalyzer.analyze_series(raw_series, is_target=True)
                    _write_debug(f"Data Profile: {y_config.get('outlier_treatment', 'none')} outliers, {y_config.get('weekday_treatment', 'none')} imputation.")

                    history_len = len(raw_series)
                    absolute_max_limit = max(14, int(history_len * 0.30)) 
                    safe_horizon = min(int(forecast_horizon), absolute_max_limit)

                    if int(forecast_horizon) > absolute_max_limit:
                        _write_debug(f"Notice: Horizon capped at {safe_horizon} days (50% of history) to maintain stability.")
                    else:
                        _write_debug(f"Forecasting Horizon strictly set to: {safe_horizon} days.")

                    # Forecasting Engine initialization
                    fe = None
                    try:
                        fe = ForecastingEngine(freq="D", horizon=safe_horizon, test_size=test_window) 
                        _write_debug(f"Engine initialized: Horizon={safe_horizon}, Test Window={test_window}")
                    except Exception as e:
                        _write_debug(f"Error: Engine initialization failed: {e}")


                    # Stage 2: Feature Engineering 
                    _emit_status(total_tasks, current_progress, f"Stage 2/5: Processing Features...")
                    time.sleep(1.0)
                    current_progress += 1

                    X_train_ext = None
                    X_test_ext = None
                    
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
                            x_date_col = next((c for c in df_source.columns if "date" in str(c).lower()), None)
                            if x_date_col:
                                df_source[x_date_col] = pd.to_datetime(df_source[x_date_col])
                                df_source = df_source.set_index(x_date_col).sort_index()
                                _write_debug(f"Using External Features file: {len(valid_x)} variables found.")
                            else:
                                _write_debug("Warning: No date column in X file. Alignment might fail.")
                                
                        elif valid_x_local:
                            df_source = df.copy()
                            valid_x = valid_x_local
                            _write_debug(f"Using Features from main file: {len(valid_x)} variables found.")

                        if df_source is not None and valid_x:
                            x_configs = TreatmentAnalyzer.analyze_dataframe(df_source[valid_x])
                            # _write_debug(f"{sheet}/{metric}: Features X Treatment Profiles -> {x_configs}") # Removed verbose dict
                            
                            df_x_clean = dh.impute_exogenous(
                                df_source[valid_x], 
                                valid_x, 
                                treatment_configs=x_configs
                            )
                            
                            df_x_clean = df_x_clean.reindex(df.index).ffill().fillna(0)
                        else:
                            _write_debug(f"Warning: No valid X variables found despite selection.")

                    train_raw, test_raw = fe._train_test_split(raw_series)

                    train_series = dh.impute_train(train_raw, config=y_config)
                    test_series_clean = dh.impute_train(test_raw, config=y_config) 
                    test_series_raw = test_raw 
                    full_clean_series = dh.impute_train(raw_series, config=y_config)                  

                    if selected_x_cols and 'df_x_clean' in locals():
                        X_train_ext = df_x_clean.reindex(train_series.index)
                        X_train_ext = X_train_ext.ffill().fillna(0)
                        
                        X_test_ext = df_x_clean.reindex(test_series_clean.index)
                        X_test_ext = X_test_ext.ffill().fillna(0)

                    adi_val = calculate_adi(full_clean_series)
                    cv2_val = calculate_cv2(full_clean_series)
                    demand_profile = classify_demand(adi_val=adi_val, cv2_val=cv2_val)
                    demand_type    = demand_profile.demand_type
                    _write_debug(
                        f"Demand Pattern: {demand_type} "
                        f"(ADI={adi_val:.2f}, CV2={cv2_val:.2f}) | "
                        f"Recommended models: {demand_profile.recommended_models}"
                    )

                    if isinstance(train_series.index, pd.DatetimeIndex):
                        if train_series.index.freq is None and train_series.index.inferred_freq is None:
                            _write_debug(f"Notice: Irregular timestamps detected. No frequency enforced.")

                    for msg in dh_logs:
                         if "SKIP" in msg: _write_debug(f"Warning: {msg}")

                    if train_series is None or train_series.empty:
                        _write_debug(f"Error: Training series is empty after sanitization. Skipping.")
                        sheet_metrics[metric] = {
                            "best_model"      : best_name,
                            "wmape"           : scores["wmape"],
                            "mae"             : scores["mae"],
                            "mape"            : scores["mape"],
                            "rmse"            : scores.get("rmse"),          # NEW
                            "composite_score" : scores.get("composite_score"),  # NEW
                            "accuracy"        : scores["accuracy"],
                            "adi"             : adi_val,
                            "cv2"             : cv2_val,
                            "demand_type"     : demand_type,
                            "demand_profile"  : demand_profile.to_dict(),    # NEW — full profile
                            "records"         : records,
                            "y_treatment"     : y_config if 'y_config' in locals() else {},
                            "x_treatment"     : x_configs if 'x_configs' in locals() else {},
                        }
                        sheet_figs[metric] = {}
                        current_progress += 3
                        continue

                    # Data metrics
                    n_points = len(train_series)
                    zero_ratio = float((train_series == 0).sum()) / max(1, n_points)
                    # _write_debug(f"{sheet}/{metric}: points={n_points}, zero_ratio={zero_ratio:.2%}")

                    # Univariate Model
                    _emit_status(total_tasks, current_progress, f"Stage 3/5: Running Univariate Models...")
                    current_progress += 1

                    mean_val = float(train_series.mean())
                    std_val = float(train_series.std())
                    cv = std_val / (mean_val + 1e-6)

                    # model allowlist (will be pruned)
                    # allowed_models = {"TBATS", "Prophet", "LightGBM", "HistGB", "ExpSmoothing", "SARIMAX", "Croston"}

                    # # Low volume series
                    # if mean_val < 10:
                    #     _write_debug(f"Volume Low (Mean < 10): Disabling Prophet & SARIMAX.")
                    #     allowed_models.discard("Prophet")
                    #     allowed_models.discard("SARIMAX")

                    # # Zero heavy series
                    # if zero_ratio > 0.8:
                    #     _write_debug(f"Sparse Data Detected (>80% zeros): Disabling Prophet.")
                    #     allowed_models.discard("Prophet")
                    
                    baseline_wmape = None
                    baseline_test_pred = None

                    # Run Baseline SMA (Runs in ALL cases)
                    try:
                        base_res = fe._run_sma(train_series, test_series_raw)
                        b_scores = calculate_performance_metrics(test_series_raw, base_res.predictions_test)
                        
                        baseline_wmape = b_scores["wmape"]
                        baseline_test_pred = base_res.predictions_test

                        log_experiment(
                            sheet, metric, "Univariate", "Baseline_SMA", 
                            b_scores["wmape"], b_scores["mae"], b_scores["mape"], b_scores["accuracy"]
                        )
                        log_experiment(
                            sheet, metric, "Multivariate", "Baseline_SMA", 
                            b_scores["wmape"], b_scores["mae"], b_scores["mape"], b_scores["accuracy"]
                        )
                        _write_debug(f"Baseline (SMA) Model Performance: WMAPE={b_scores['wmape']:.2%}")

                    except Exception as base_e:
                        _write_debug(f"Warning: Baseline SMA failed: {base_e}")
                    
                    original_models = fe.models.copy()

                    demand_filtered_models = fe.get_models_for_demand_type(
                        demand_profile = demand_profile,
                        mean_val       = mean_val,
                        zero_ratio     = zero_ratio,
                        cv             = cv,
                        n_points       = n_points,
                    )

                    if not demand_filtered_models:
                        _write_debug("Notice: Demand profile indicates sparse fallback will be used.")
                    else:
                        fe.models = demand_filtered_models
                        _write_debug(f"Active Models (demand-routed): {list(fe.models.keys())}")

                    if train_series.empty:
                        _write_debug(f"Error: Series is empty. Skipping.")
                        sheet_metrics[metric] = {
                            "best_model"      : best_name,
                            "wmape"           : scores["wmape"],
                            "mae"             : scores["mae"],
                            "mape"            : scores["mape"],
                            "rmse"            : scores.get("rmse"),          # NEW
                            "composite_score" : scores.get("composite_score"),  # NEW
                            "accuracy"        : scores["accuracy"],
                            "adi"             : adi_val,
                            "cv2"             : cv2_val,
                            "demand_type"     : demand_type,
                            "demand_profile"  : demand_profile.to_dict(),    # NEW — full profile
                            "records"         : records,
                            "y_treatment"     : y_config if 'y_config' in locals() else {},
                            "x_treatment"     : x_configs if 'x_configs' in locals() else {},
                        }
                        metric_completed = True
                        sheet_figs[metric] = {}
                        current_progress += 2 
                        continue

                    if n_points < 90 or (zero_ratio > 0.7 and mean_val < 5):
                        _write_debug(f"Notice: Using Sparse Data Fallback (SMA) due to insufficient history/volume.")

                        # SMA Predictions
                        train_model_output = fe.run_fallback_model(train_series)
                        fallback_val = float(train_model_output.iloc[0]) if not train_model_output.empty else 0.0
                        
                        test_pred_series = pd.Series([fallback_val] * len(test_series_raw), index=test_series_raw.index)
                        forecast_series = fe.run_fallback_model(full_clean_series, horizon=safe_horizon)

                        test_pred_series = dh.apply_business_rules(test_pred_series)
                        forecast_series = dh.apply_business_rules(forecast_series)

                        scores = calculate_performance_metrics(test_series_raw, test_pred_series)
                        
                        log_experiment(
                            sheet, metric, "Univariate", "Baseline_SMA", 
                            scores["wmape"], scores["mae"], scores["mape"], scores["accuracy"]
                        )
                        log_experiment(
                            sheet, metric, "Multivariate", "Baseline_SMA", 
                            scores["wmape"], scores["mae"], scores["mape"], scores["accuracy"]
                        )
                        print(f"   >> {sheet}/{metric} | Model: Baseline_SMA (Sparse) | WMAPE: {scores['wmape']:.4f}")

                        records = build_records(
                            train_series=train_series,
                            test_series=test_series_raw,
                            test_pred_series=test_pred_series,
                            forecast_series=forecast_series,
                            train_series_raw=train_raw,
                            df_x_clean=df_x_clean if 'df_x_clean' in locals() else None 
                        )

                        sheet_metrics[metric] = {
                            "best_model"      : best_name,
                            "wmape"           : scores["wmape"],
                            "mae"             : scores["mae"],
                            "mape"            : scores["mape"],
                            "rmse"            : scores.get("rmse"),          # NEW
                            "composite_score" : scores.get("composite_score"),  # NEW
                            "accuracy"        : scores["accuracy"],
                            "adi"             : adi_val,
                            "cv2"             : cv2_val,
                            "demand_type"     : demand_type,
                            "demand_profile"  : demand_profile.to_dict(),    # NEW — full profile
                            "records"         : records,
                            "y_treatment"     : y_config if 'y_config' in locals() else {},
                            "x_treatment"     : x_configs if 'x_configs' in locals() else {},
                        }

                        metric_completed = True
                        metric_success = True
                        sheet_figs[metric] = {} 
                        _write_debug(f"SUCCESS: Completed {metric} using Baseline Fallback.")
                        current_progress += 2 
                        continue

                    # Univariate Model Selection
                    try:
                        best_name = None
                        best_wmape = float("inf")
                        best_test_pred = None
                        accuracy = None
                        
                        _write_debug("Evaluating Univariate Models")

                        for model_name in fe.models.keys():

                            if os.path.exists(STOP_FLAG):
                                raise InterruptedError("Stopped by user")
                            
                            try:
                                test_pred = fe.predict_external_test(
                                    model_name,
                                    train_series,
                                    test_series_raw.index
                                )

                                # Scoring on non-NaN raw data
                                common_idx = test_series_raw.index.intersection(test_pred.index)
                                effective_test = test_series_raw.loc[common_idx].dropna()
                                effective_test = effective_test[effective_test != 0]

                                if len(effective_test) < max(7, int(0.3 * len(test_series_raw))):
                                    continue

                                scores = calculate_performance_metrics(
                                    test_series_raw.loc[common_idx],
                                    test_pred.loc[common_idx]
                                )
                                from utils.metrics import composite_score as _composite_score
 
                                comp_score = _composite_score(
                                    actual          = test_series_raw.loc[common_idx],
                                    predicted       = test_pred.loc[common_idx],
                                    train_series    = train_series,
                                    forecast_series = test_pred.loc[common_idx],  # proxy until full forecast available
                                )
                                
                                # Log both for transparency
                                _write_debug(f"{model_name}: WMAPE={scores['wmape']:.4f}  Composite={comp_score:.4f}")
                                
                                # Select on composite score (lower is better)
                                if comp_score < best_composite:
                                    best_composite = comp_score
                                    best_wmape     = scores["wmape"]
                                    best_name      = model_name
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
                                test_pred_series.loc[common_idx]
                            )
                        else:
                            accuracy = None

                        # refit best model
                        forecast_series = None
                        runner = fe.models.get(best_name)

                        if runner is not None:
                            dummy_test = train_series.iloc[-1:]
                            refit_res = runner(train_series, dummy_test)

                            if refit_res is not None and hasattr(refit_res, "forecast"):
                                forecast_series = refit_res.forecast.clip(lower=0.0)

                                _write_debug(f"Final forecast series length: {len(forecast_series)}")

                                horizon = len(forecast_series)
                                last_observed_date = raw_series.index.max()

                                forecast_series.index = fe._future_index(
                                    last_observed_date,
                                    horizon,
                                    raw_series.index
                                )

                        _write_debug(
                            f"Univariate Winner: {best_name} (WMAPE={external_wmape:.2%})"
                        )

                    except Exception as model_err:
                        _write_debug(f"Error: Univariate selection failed ({model_err}). Reverting to Baseline.")

                        # SMA Predictions
                        train_model_output = fe.run_fallback_model(train_series)
                        fallback_val = float(train_model_output.iloc[0]) if not train_model_output.empty else 0.0
                        
                        test_pred_series = pd.Series([fallback_val] * len(test_series_raw), index=test_series_raw.index)
                        forecast_series = fe.run_fallback_model(full_clean_series)

                        test_pred_series = dh.apply_business_rules(test_pred_series)
                        forecast_series = dh.apply_business_rules(forecast_series)

                        scores = calculate_performance_metrics(test_series_raw, test_pred_series)
                        
                        log_experiment(
                            sheet, metric, "Univariate", "Baseline_SMA", 
                            scores["wmape"], scores["mae"], scores["mape"], scores["accuracy"]
                        )     
                        log_experiment(
                            sheet, metric, "Multivariate", "Baseline_SMA", 
                            scores["wmape"], scores["mae"], scores["mape"], scores["accuracy"]
                        )         
                        print(f"   >> {sheet}/{metric} | Model: Baseline_SMA (Error) | WMAPE: {scores['wmape']:.4f}")

                        records = build_records(
                            train_series=train_series,
                            test_series=test_series_raw,
                            test_pred_series=test_pred_series,
                            forecast_series=forecast_series,
                            train_series_raw=train_raw,
                            df_x_clean=df_x_clean if 'df_x_clean' in locals() else None  
                        )

                        sheet_metrics[metric] = {
                            "best_model"      : best_name,
                            "wmape"           : scores["wmape"],
                            "mae"             : scores["mae"],
                            "mape"            : scores["mape"],
                            "rmse"            : scores.get("rmse"),          # NEW
                            "composite_score" : scores.get("composite_score"),  # NEW
                            "accuracy"        : scores["accuracy"],
                            "adi"             : adi_val,
                            "cv2"             : cv2_val,
                            "demand_type"     : demand_type,
                            "demand_profile"  : demand_profile.to_dict(),    # NEW — full profile
                            "records"         : records,
                            "y_treatment"     : y_config if 'y_config' in locals() else {},
                            "x_treatment"     : x_configs if 'x_configs' in locals() else {},
                        }
                        metric_completed = True
                        metric_success = True
                        sheet_figs[metric] = {}
                        current_progress += 2
                        continue

                    # Stage 4: Multivariate Pipeline 
                    _emit_status(total_tasks, current_progress, f"Stage 4/5: Evaluating Multivariate")
                    current_progress += 1

                    apply_multivariate = False
                    accuracy_pct = accuracy             

                    if accuracy_pct is not None and accuracy_pct <100.0:
                        apply_multivariate = True
                        _write_debug(
                            f"Note: Accuracy {accuracy_pct:.1f}% < 100%. Attempting Multivariate improvement..."
                        )
                    elif accuracy_pct is not None:
                         _write_debug(
                            f"Note: Accuracy {accuracy_pct:.1f}% >= 100%. Skipping Multivariate."
                        )

                    # Multivariate Escalation
                    if apply_multivariate:

                        if selected_x_cols:
                             _write_debug(f"Starting Multivariate Pipeline. Drivers: {len(selected_x_cols)} variables.")
                             print(f"\n[INFO] STARTING MULTIVARIATE PIPELINE for Target: {metric}")
                             print(f"[INFO] Active External Drivers (X): {selected_x_cols}")
                             _write_debug(f"[INFO] External Variables (X): {selected_x_cols}")
                             
                             common_idx = train_series.index.intersection(X_train_ext.index)
                             print(f"[INFO] Aligned Training Samples: {len(common_idx)}")
                        
                        mv = MultivariateEngine(selected_regions=selected_regions)
                        mv_res = mv.run_multivariate(
                            train_series, 
                            test_series_clean, 
                            test_series_raw,  
                            X_external_train=X_train_ext,
                            X_external_test=X_test_ext,
                            debug=True,
                            logger_func=lambda name, w, m, mp, acc: log_experiment(
                                sheet, metric, "Multivariate", name, w, m, mp, acc
                            ),
                            horizon=safe_horizon,
                            test_size=test_window
                        )

                        feature_importance_dict = {}
                        if "best_model_object" in mv_res:
                            model_obj = mv_res["best_model_object"]
                            actual_feature_names = mv_res.get("top_features", [])
                            
                            try:
                                if hasattr(model_obj, 'feature_importances_'):
                                    importances = model_obj.feature_importances_
                                    feature_importance_dict = dict(zip(actual_feature_names, [float(i) for i in importances]))
                                elif hasattr(model_obj, 'coef_'):
                                    # Handle Linear models (Ridge/Huber)
                                    importances = np.abs(model_obj.coef_).flatten()
                                    feature_importance_dict = dict(zip(actual_feature_names, [float(i) for i in importances]))
                                    
                                # Filter for top 10 impactful drivers
                                feature_importance_dict = {k: round(v, 4) for k, v in sorted(feature_importance_dict.items(), 
                                                        key=lambda item: item[1], reverse=True)[:10] if v > 0}
                            except Exception as e:
                                _write_debug(f"Feature Importance Error: {str(e)}")

                        _write_debug(
                            f"Multivariate Best: {mv_res.get('best_model')} | WMAPE={mv_res.get('wmape'):.2%}"
                        )

                        uni_score = external_wmape if external_wmape is not None else 1.0
                        mv_score = mv_res["wmape"] if mv_res["wmape"] is not None else 1.0

                        _write_debug(f"{sheet}/{metric}: WMAPE comparison | univariate={uni_score:.4f}, multivariate={mv_score:.4f}")

                        is_better = mv_score < uni_score
                        
                        mv_std = mv_res["forecast"].std()
                        is_not_flat = mv_std > 1e-6
                        significant_improvement = mv_score < (uni_score * 0.95)
                        forecast_std = forecast_series.std() if forecast_series is not None else 0.0
                        
                        if (significant_improvement and is_not_flat) or (is_better and is_not_flat and mv_std >= 0.3 * forecast_std):
                            _write_debug(f"SUCCESS: Multivariate Model Accepted ({mv_res.get('best_model')}).")

                            mv_train = mv_res["train"]
                            mv_test = mv_res["test"]
                            best_name = mv_res["best_model"]

                            # Final Series (Clip + Business Rules)
                            test_pred_series = mv_res["test_pred"].clip(lower=0.0)
                            forecast_series = mv_res["forecast"].clip(lower=0.0)

                            test_pred_series = dh.apply_business_rules(test_pred_series)
                            forecast_series = dh.apply_business_rules(forecast_series)
                            scores = calculate_performance_metrics(mv_test, test_pred_series)
                            
                            # Logging Winner
                            log_experiment(
                                sheet, metric, "Multivariate", best_name,
                                scores["wmape"], scores["mae"], scores["mape"], scores["accuracy"]
                            )

                            # Build Records
                            records = build_records(
                                train_series=train_series,
                                test_series=test_series_raw,
                                test_pred_series=test_pred_series,
                                forecast_series=forecast_series,
                                train_series_raw=train_raw,
                                df_x_clean=df_x_clean if 'df_x_clean' in locals() else None  
                            )

                            if selected_x_cols and 'df_x_clean' in locals():
                                x_lookup = df_x_clean.to_dict(orient='index')
                                
                                for rec in records:
                                    d_ts = rec["Date"]
                                    if d_ts in x_lookup:
                                        rec.update(x_lookup[d_ts])

                            metric_finalized = True 

                            # Saving Sheet Metrics
                            sheet_metrics[metric] = {
                                "best_model"      : best_name,
                                "wmape"           : scores["wmape"],
                                "mae"             : scores["mae"],
                                "mape"            : scores["mape"],
                                "rmse"            : scores.get("rmse"),          # NEW
                                "composite_score" : scores.get("composite_score"),  # NEW
                                "accuracy"        : scores["accuracy"],
                                "adi"             : adi_val,
                                "cv2"             : cv2_val,
                                "demand_type"     : demand_type,
                                "demand_profile"  : demand_profile.to_dict(),    # NEW — full profile
                                "records"         : records,
                                "y_treatment"     : y_config if 'y_config' in locals() else {},
                                "x_treatment"     : x_configs if 'x_configs' in locals() else {},
                            }
                            
                            metric_completed = True
                            metric_success = True                            
                                                        
                        else:
                            _write_debug(
                                f"Multivariate ({mv_res.get('best_model')}) did not improve results. Keeping Univariate."
                            )

                    # Stage 5: Finalizing 
                    _emit_status(total_tasks, current_progress, f"Stage 5/5: Finalizing Forecast...")
                    current_progress += 1
                                                            
                    last_quarter = train_series.tail(90)
                    
                    is_sparse_metric = zero_ratio > 0.10  
                    
                    if forecast_series is None:
                        forecast_series = fe.run_fallback_model(full_clean_series)
                    
                    forecast_series = forecast_series.clip(lower=0.0)

                    test_pred_series = dh.apply_business_rules(test_pred_series)
                    forecast_series = dh.apply_business_rules(forecast_series)

                    if not is_sparse_metric:
                        non_zero = last_quarter[last_quarter > 0]
                        if not non_zero.empty:
                            floor = max(float(non_zero.quantile(0.10)), float(non_zero.min()))
                            min_allowed = floor * 0.9
                            
                            forecast_series = forecast_series.where(
                                forecast_series >= min_allowed,
                                other=min_allowed
                            )
                    else:
                        pass
                    
                    if accuracy is not None:
                        final_accuracy = round(float(accuracy), 2)
                    else:
                        final_accuracy = None

                    if not metric_finalized:
                        common_idx = test_series_raw.index.intersection(test_pred_series.index)
                        
                        val_mae = mae(test_series_raw.loc[common_idx], test_pred_series.loc[common_idx])
                        val_mape = mape(test_series_raw.loc[common_idx], test_pred_series.loc[common_idx])

                        records = build_records(
                            train_series=train_series,
                            test_series=test_series_raw,
                            test_pred_series=test_pred_series,
                            forecast_series=forecast_series,
                            train_series_raw=train_raw,
                            df_x_clean=df_x_clean if 'df_x_clean' in locals() else None  
                        )

                        sheet_metrics[metric] = {
                            "best_model"      : best_name,
                            "wmape"           : scores["wmape"],
                            "mae"             : scores["mae"],
                            "mape"            : scores["mape"],
                            "rmse"            : scores.get("rmse"),          # NEW
                            "composite_score" : scores.get("composite_score"),  # NEW
                            "accuracy"        : scores["accuracy"],
                            "adi"             : adi_val,
                            "cv2"             : cv2_val,
                            "demand_type"     : demand_type,
                            "demand_profile"  : demand_profile.to_dict(),    # NEW — full profile
                            "records"         : records,
                            "y_treatment"     : y_config if 'y_config' in locals() else {},
                            "x_treatment"     : x_configs if 'x_configs' in locals() else {},
                        }
                        metric_completed = True
                        metric_success = True

                    if baseline_wmape is not None and metric_success and metric in sheet_metrics:
                        
                        current_best_wmape = sheet_metrics[metric].get("wmape")
                        if current_best_wmape is None: 
                            current_best_wmape = float('inf')

                        # Compare Baseline  with current best 
                        if baseline_wmape < current_best_wmape:
                            _write_debug(f"Notice: Baseline Model (SMA) outperformed advanced models. Reverting.")
                            
                            # Refitting on complete Data (Train + Test) 
                            final_base_res = fe._run_sma(full_clean_series, None)                            
                            base_scores = calculate_performance_metrics(test_series_raw, baseline_test_pred)

                            records = build_records(
                                train_series=train_series,
                                test_series=test_series_raw,
                                test_pred_series=test_pred_series,
                                forecast_series=forecast_series,
                                train_series_raw=train_raw,
                                df_x_clean=df_x_clean if 'df_x_clean' in locals() else None  
                            )

                            # Overwriting Winner
                            sheet_metrics[metric] = {
                                "best_model"      : best_name,
                                "wmape"           : scores["wmape"],
                                "mae"             : scores["mae"],
                                "mape"            : scores["mape"],
                                "rmse"            : scores.get("rmse"),          # NEW
                                "composite_score" : scores.get("composite_score"),  # NEW
                                "accuracy"        : scores["accuracy"],
                                "adi"             : adi_val,
                                "cv2"             : cv2_val,
                                "demand_type"     : demand_type,
                                "demand_profile"  : demand_profile.to_dict(),    # NEW — full profile
                                "records"         : records,
                                "y_treatment"     : y_config if 'y_config' in locals() else {},
                                "x_treatment"     : x_configs if 'x_configs' in locals() else {},
                            }
                            
                            best_name = "Baseline_SMA"
                            forecast_series = final_base_res.forecast

                    # small figure for UI
                    try:
                        hist_df = pd.DataFrame({"Date": pd.to_datetime(train_series.index), "Actual": train_series.values})
                        future_df = pd.DataFrame({"Date": pd.to_datetime(forecast_series.index), "Forecast": forecast_series.values})
                        fig = go.Figure()
                        if not hist_df.empty:
                            fig.add_trace(go.Scatter(x=hist_df["Date"], y=hist_df["Actual"], mode="lines+markers", name="Actual"))
                        if not future_df.empty:
                            fig.add_trace(go.Scatter(x=future_df["Date"], y=future_df["Forecast"], mode="lines+markers", name=f"Forecast ({best_name})", line=dict(dash="dash")))
                        fig.update_layout(title=f"{sheet} - {metric} (Best: {best_name})", xaxis_title="Date", yaxis_title=metric)
                        sheet_figs[metric] = fig.to_dict()
                    except Exception as fig_err:
                        _write_debug(f"Error: Figure build failed for {sheet}/{metric}: {fig_err}")
                        sheet_figs[metric] = {}                

                except Exception as metric_exc:
                    _write_debug(f"Error: Metric-level exception for {sheet}/{metric}: {metric_exc}")
                    with open(TRACEBACK_FILE, "w") as fh:
                        fh.write(traceback.format_exc())
                    sheet_metrics[metric] = {
                        "best_model"      : best_name,
                        "wmape"           : scores["wmape"],
                        "mae"             : scores["mae"],
                        "mape"            : scores["mape"],
                        "rmse"            : scores.get("rmse"),          # NEW
                        "composite_score" : scores.get("composite_score"),  # NEW
                        "accuracy"        : scores["accuracy"],
                        "adi"             : adi_val,
                        "cv2"             : cv2_val,
                        "demand_type"     : demand_type,
                        "demand_profile"  : demand_profile.to_dict(),    # NEW — full profile
                        "records"         : records,
                        "y_treatment"     : y_config if 'y_config' in locals() else {},
                        "x_treatment"     : x_configs if 'x_configs' in locals() else {},
                    }
                    metric_completed = True
                    metric_success = False
                    sheet_figs[metric] = {}
                    remaining = (current_progress % 5)
                    if remaining != 0: current_progress += (5 - remaining)
                
                finally:
                    if fe is not None and 'original_models' in locals():
                        fe.models = original_models

                    if metric_completed:
                        done_count += 1
                        
                        remaining = (current_progress % 5)
                        if remaining != 0: current_progress += (5 - remaining)

                        if metric_success:
                            _write_debug(f"SUCCESS: Completed forecasting for {sheet}/{metric}")
                        else:
                            _write_debug(f"FAILED: Metric {sheet}/{metric}")
            
            predictions_by_sheet[sheet] = {"metrics": sheet_metrics}
            figs_by_sheet[sheet] = sheet_figs

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
            _write_debug(f"Error: Failed writing predictions: {e}")

        try:
            with open(FIGS_JSON, "w") as fh:
                json.dump(figs_by_sheet, fh, default=str, indent=2)
        except Exception as e:
            _write_debug(f"Error: Failed writing figures: {e}")

        end_time = time.time()
        duration = end_time - start_time
        
        if duration > 60:
            time_str = f"{int(duration // 60)}m {int(duration % 60)}s"
        else:
            time_str = f"{int(duration)}s"

        _emit_status(
            total_tasks, 
            total_tasks, 
            f"Processing Completed. 100% (Execution Time: {time_str})", 
            completed=True
        )
        
        time.sleep(1.5)

        try:
            with open(DONE_FLAG, "w") as fh:
                fh.write(f"done:{datetime.now().isoformat()}\n")
        except Exception:
            pass

        _write_debug("SUCCESS: Execution completed successfully.")
    
    except InterruptedError:
        return

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
            with open(PRED_JSON, "r", encoding="utf-8") as fh:
                preds = json.load(fh)
    except Exception:
        preds = {}
    try:
        if os.path.exists(FIGS_JSON):
            with open(FIGS_JSON, "r", encoding="utf-8") as fh:
                figs = json.load(fh)
    except Exception:
        figs = {}
    return preds, figs

def read_progress() -> Dict[str, Any]:
    progress_data = {"percent": 0, "message": "Waiting..."}
    if os.path.exists(PROGRESS_JSON):
        try:
            with open(PROGRESS_JSON, "r") as fh:
                progress_data = json.load(fh)
        except:
            pass

    if os.path.exists(DONE_FLAG):
        progress_data["percent"] = 100
        if "completed" not in progress_data.get("message", "").lower():
             progress_data["message"] = "Processing Completed."
        return progress_data
    
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