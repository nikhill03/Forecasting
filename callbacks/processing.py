import base64
import html
import io
import json
import logging
import os
import threading
import traceback
from datetime import datetime
from dash_iconify import DashIconify
from typing import Dict, Any, List, Optional
from dash import ALL

import dash_mantine_components as dmc
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, dcc, html, callback_context, no_update
from dash.exceptions import PreventUpdate
from dash import Input, Output, callback

import plotly.subplots as sp
from services.processing_engine import HISTORY_LOG, PROGRESS_JSON  
from utils.holiday_utils import get_region_holidays

from services.data_handling import DataHandling 
from services.llm_service import LLMService
from services.constraint_executor import ConstraintExecutor
from utils.holiday_utils import get_region_holidays

from services.forecast_artifact import (
    generate_experiment_figure, generate_health_summary_table, generate_seasonality_figure, generate_stationarity_figure,
    generate_acf_pacf_figure, generate_distribution_figure, generate_feature_heatmap,
    generate_multivariate_feature_analysis, generate_treatment_comparison_figure, generate_holiday_table, 
    generate_holiday_charts, generate_holiday_windows
)
from layout.main_layout import elevated_card

# Import services used by your app (paths must match your project)
from services.processing_engine import (
    processing_worker,
    read_predictions_and_figs,
    read_progress,
    read_log_tail,
    normalize_upload_contents,
    create_lock,
    clear_all_outputs,
    DONE_FLAG,
    STOP_FLAG,
    PRED_JSON,
    DEBUG_LOG,
    TRACEBACK_FILE,
)
from utils.metrics import calculate_adi, calculate_cv2, classify_demand

# Temp compatibility files (older worker expectations)
TMP_B64_PATH = "/tmp/dmc_uploaded_raw.b64"
TMP_SELECTIONS = "/tmp/dmc_last_selection.json"

# Module-level state
IN_MEMORY_LOGS: List[str] = []
CURRENT_PROGRESS: Dict[str, int] = {"total": 0, "done": 0}

WORKER_THREAD: Optional[threading.Thread] = None
WORKER_THREAD_LOCK = threading.Lock()

logger = logging.getLogger("dmc.processing")
logger.setLevel(logging.INFO)


def _now_ts():
    """Standardized timestamp matching the engine's format"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def _write_debug(msg: str) -> None:
    """Writes to the physical log file"""
    try:
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{_now_ts()}] {msg}\n")
    except Exception:
        pass

def _append_log(msg: str):
    """Adds message to UI state and physical file simultaneously"""
    line = f"[{_now_ts()}] {msg}"
    if line not in IN_MEMORY_LOGS:
        IN_MEMORY_LOGS.append(line)
    _write_debug(msg)

def _render_console_lines(lines):
    rendered = []
    for line in lines:
        # Determine Color based on content
        is_error = any(kw in line.lower() for kw in ["error:", "exception", "failed", "critical"])
        is_success = "success:" in line.lower()
        is_intervention = any(kw in line for kw in ["🛑", "🔄", "STOPPED", "RESTARTED"]) # NEW: Manual intervention

        color = "#e6eef8" # Default
        if is_error: color = "#ff4d4f"
        elif is_success: color = "#2ecc71"
        elif is_intervention: color = "#f39c12" # ORANGE for Stop/Restart

        rendered.append(
            dmc.Text(
                line, size="sm",
                style={"color": color, "fontFamily": "monospace", "whiteSpace": "pre-wrap"}
            )
        )
    return rendered

# =================================================
# 1. PARSING HELPER (New)
# =================================================
def parse_contents(contents, filename):
    if not contents: return None
    _, content_string = contents.split(',')
    decoded = base64.b64decode(content_string)
    dfs = {}
    try:
        if 'xlsx' in filename:
            xl = pd.ExcelFile(io.BytesIO(decoded))
            for sheet in xl.sheet_names:
                dfs[sheet] = xl.parse(sheet)
        else:
            dfs['Sheet1'] = pd.read_csv(io.BytesIO(decoded))
    except Exception as e:
        print(f"Error parsing {filename}: {e}")
        return None
    return dfs

def register_processing_callbacks(app):
    
    # =================================================
    # 2. TARGET (Y) UPLOAD CALLBACKS
    # =================================================
    @app.callback(
        Output("store-target-dfs", "data"),
        Output("filename-target", "children"),
        Output("select-sheet-target", "data"),
        Output("select-sheet-target", "value"),
        Output("select-sheet-target", "disabled"),
        Input("upload-target", "contents"),
        State("upload-target", "filename"),
    )
    def handle_target_upload(contents, filename):
        if not contents: return no_update
        dfs = parse_contents(contents, filename)
        if not dfs: return no_update
        
        store_data = {k: v.to_json(orient='split', date_format='iso') for k, v in dfs.items()}
        sheet_opts = [{"label": k, "value": k} for k in dfs.keys()]
        
        # Auto-select first sheet
        default_sheet = sheet_opts[0]["value"] if sheet_opts else None
        
        # Display shortened filename
        short_name = filename[:20] + "..." if len(filename) > 20 else filename
        
        return store_data, short_name, sheet_opts, default_sheet, False

    @app.callback(
        Output("select-col-target", "data"),
        Output("select-col-target", "value"),
        Output("select-col-target", "disabled"),
        Input("select-sheet-target", "value"),
        State("store-target-dfs", "data"),
    )
    def populate_target_columns(sheet, store_data):
        if not sheet or not store_data: return [], None, True
        try:
            df = pd.read_json(store_data[sheet], orient='split')
            # Filter: Numeric cols only, exclude "date" cols
            cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and "date" not in str(c).lower()]
            opts = [{"label": c, "value": c} for c in cols]
            return opts, (opts[0]["value"] if opts else None), False
        except:
            return [], None, True

    # =================================================
    # 3. FEATURES (X) UPLOAD CALLBACKS
    # =================================================
    @app.callback(
        Output("store-feature-dfs", "data"),
        Output("filename-features", "children"),
        Input("upload-features", "contents"),
        State("upload-features", "filename"),
    )
    def handle_feature_upload(contents, filename):
        if not contents: return no_update
        dfs = parse_contents(contents, filename)
        if not dfs: return no_update
        
        store_data = {k: v.to_json(orient='split', date_format='iso') for k, v in dfs.items()}
        
        short_name = filename[:20] + "..." if len(filename) > 20 else filename
        return store_data, short_name

    # =================================================
    # 4. MAIN CONTROL RUN (MERGE & EXECUTE)
    # =================================================
    @app.callback(
        [Output("console-empty-state", "style"),
        Output("console-main-content", "style"),
        Output("log-interval", "disabled"),
        Output("log-store", "data"),
        Output("console-output", "children"),
        Output("predictions-store", "data"),
        Output("graph-store", "data"),
        Output("content-tabs", "value")],
        [Input("run-models-btn", "n_clicks"), 
        Input("btn-stop", "n_clicks"),
        Input("btn-restart", "n_clicks"),
        Input("log-interval", "n_intervals"),
        Input("clear-graph", "n_clicks")],
        [State("store-target-dfs", "data"),
        State("select-sheet-target", "value"),
        State("select-col-target", "value"),
        State("store-feature-dfs", "data"),
        State("forecast-horizon-input", "value"),
        State("region-select", "value"),
        State("test-window-select", "value")],
        prevent_initial_call=True
    )
    def control_run(n_click, stop_click, restart_click, n_int, clear_click,
                    target_store, target_sheet, target_col, 
                    feature_store, horizon, selected_regions, test_window):
        
        global WORKER_THREAD
        global IN_MEMORY_LOGS

        ctx = callback_context
        if not ctx.triggered:
            raise PreventUpdate
            
        trigger = ctx.triggered[0]["prop_id"].split(".")[0]
        log_store = IN_MEMORY_LOGS
        
        # --- UI DISPLAY STATES ---
        SHOW_EMPTY = {"height": "100%", "display": "flex", "borderRadius": "20px"}
        HIDE_EMPTY = {"display": "none"}
        SHOW_CONSOLE = {"display": "flex", "flexDirection": "column", "height": "100%"}
        HIDE_CONSOLE = {"display": "none"}

        # --- UI Interactions ---
        if trigger == "clear-graph":
            clear_all_outputs()
            return SHOW_EMPTY, HIDE_CONSOLE, True, [], _render_console_lines([]), {}, {}, no_update

        # 1. STOP LOGIC: Immediate append and file write
        if trigger == "btn-stop":
            try:
                with open(STOP_FLAG, "w") as fh: fh.write("stop")
                with open(PROGRESS_JSON, "w") as fh:
                    json.dump({"percent": 0, "message": "🛑 Execution Stopped", "status": "stopped"}, fh)
            except: pass
            
            # Log to both memory and file immediately
            _append_log("🛑 Execution STOPPED by user request.") 
            
            return HIDE_EMPTY, SHOW_CONSOLE, False, IN_MEMORY_LOGS, _render_console_lines(IN_MEMORY_LOGS), no_update, no_update, no_update

        # 2. INTERVAL POLLING LOGIC
        if trigger == "log-interval":
            # If a stop was requested, disable the interval now
            if os.path.exists(STOP_FLAG):
                return no_update, no_update, True, no_update, no_update, no_update, no_update, no_update

            try:
                preds, figs = read_predictions_and_figs()
                tail = read_log_tail()
                merged = IN_MEMORY_LOGS[:]
                for l in tail:
                    if l not in merged: merged.append(l)

                if preds and os.path.exists(DONE_FLAG):
                    return HIDE_EMPTY, SHOW_CONSOLE, True, merged, _render_console_lines(merged), preds, figs, no_update
                return HIDE_EMPTY, SHOW_CONSOLE, False, merged, _render_console_lines(merged), preds, figs, no_update
            except: pass
            return no_update

        # 3. RUN / RESTART LOGIC
        if trigger in ["run-models-btn", "btn-restart"]:
            if trigger == "btn-restart":
                try:
                    with open(STOP_FLAG, "w") as fh: fh.write("stop")
                    # Clear progress file for fresh start
                    if os.path.exists(PROGRESS_JSON): os.remove(PROGRESS_JSON)
                except: pass
                
                IN_MEMORY_LOGS.clear()
                restart_msg = f"[{_now_ts()}] 🔄 Execution RESTARTED by user request."
                IN_MEMORY_LOGS.append(restart_msg)
            
            # 1. VALIDATION CHECK (Logic Preserved)
            missing = []
            if not target_store or not target_sheet or not target_col: missing.append("Target Data")
            if not horizon: missing.append("Forecast Horizon")
            if not selected_regions or len(selected_regions) == 0: missing.append("Region Selection")

            if missing:
                err = f"[{_now_ts()}] ❌ Error: Missing {', '.join(missing)}."
                _append_log(err)
                return SHOW_EMPTY, HIDE_CONSOLE, True, log_store + [err], _render_console_lines(log_store + [err]), {}, {}, no_update

            try:
                # 2. DATA PREPARATION (Logic Preserved)
                test_size = int(test_window) if test_window else 30
                df_y = pd.read_json(target_store[target_sheet], orient='split')
                date_col_y = next((c for c in df_y.columns if "date" in str(c).lower()), None)
                df_y[date_col_y] = pd.to_datetime(df_y[date_col_y])
                df_y = df_y.set_index(date_col_y).sort_index()
                
                df_merged = df_y[[target_col]].copy()
                x_cols_list = []
                if feature_store:
                    x_sheet = list(feature_store.keys())[0]
                    df_x = pd.read_json(feature_store[x_sheet], orient='split')
                    date_col_x = next((c for c in df_x.columns if "date" in str(c).lower()), None)
                    if date_col_x:
                        df_x[date_col_x] = pd.to_datetime(df_x[date_col_x])
                        df_x = df_x.set_index(date_col_x).sort_index()
                        x_cols_raw = [c for c in df_x.columns if pd.api.types.is_numeric_dtype(df_x[c])]
                        df_merged = df_merged.join(df_x[x_cols_raw], how='left')
                        x_cols_list = x_cols_raw

                csv_buffer = io.StringIO()
                df_merged.reset_index().to_csv(csv_buffer, index=False)
                b64_merged = base64.b64encode(csv_buffer.getvalue().encode('utf-8')).decode('utf-8')
                
                # 3. WORKER INITIATION (Logic Preserved)
                clear_all_outputs()
                # Clear memory for fresh run if not already cleared by restart logic
                if trigger == "run-models-btn":
                    IN_MEMORY_LOGS.clear() 
                
                def _thread_target():
                    try:
                        processing_worker(
                            b64_merged, ["Sheet1"], [target_col],
                            selected_x_cols=x_cols_list, forecast_horizon=int(horizon),
                            test_window=test_size,
                            selected_regions=selected_regions
                        )
                    except Exception as e: _append_log(f"Worker Error: {str(e)}")

                with WORKER_THREAD_LOCK:
                    WORKER_THREAD = threading.Thread(target=_thread_target, daemon=True)
                    WORKER_THREAD.start()

                return HIDE_EMPTY, SHOW_CONSOLE, False, IN_MEMORY_LOGS, _render_console_lines(IN_MEMORY_LOGS), {}, {}, "console"
            except Exception as e:
                return SHOW_EMPTY, HIDE_CONSOLE, True, [str(e)], _render_console_lines([str(e)]), {}, {}, no_update
        
        raise PreventUpdate

   # Progress bar callback (FIXED: Resets on page load)
    @app.callback(
        Output("processing-progress", "value"),
        Output("progress-text", "children"),
        Input("log-interval", "n_intervals"),
        prevent_initial_call=False,
    )
    def update_progress(n):
        # ... (initial checks) ...
        progress_data = read_progress()
        
        pct = progress_data.get("percent", 0)
        msg = progress_data.get("message", "")

        # If it's 100%, show the message EXACTLY as the worker sent it
        if pct >= 100:
            return 100, msg 
        
        # Otherwise, show the percentage for active tasks
        txt = f"{msg} ({pct}% completed)" if pct > 0 else msg
        return pct, txt
    
    # NEW: Clear old progress file on page refresh
    @app.callback(
        Output("log-interval", "n_intervals"), # Dummy output just to trigger
        Input("log-interval", "n_intervals"),
        prevent_initial_call=False,
    )
    def reset_progress_on_load(n):
        if n == 0:
            # Clear the progress file so it doesn't show old state
            try:
                if os.path.exists(PROGRESS_JSON):
                    os.remove(PROGRESS_JSON)
                if os.path.exists(DONE_FLAG):
                    os.remove(DONE_FLAG)
            except:
                pass
        return no_update
    

    # Enable graphs tab only when predictions exist & interval disabled
    @app.callback(
        Output("run-models-btn", "disabled"), # NEW: Disable toolbar button during run
        Output("tab-graphs", "disabled"),
        Output("tab-artifacts", "disabled"),
        Output("kyd-tab", "disabled"),  
        Input("predictions-store", "data"),
        Input("log-interval", "disabled"), # interval_disabled=False means it IS running
        prevent_initial_call=False,
    )
    def toggle_ui_states(preds, interval_disabled):
        # Determine execution state
        is_running = not interval_disabled #
        has_preds = bool(preds and isinstance(preds, dict) and len(preds) > 0)
        
        # 1. Disable 'Run Forecast' button if already running
        run_btn_disabled = is_running
        
        # 2. Disable analysis tabs until finished
        tabs_disabled = not (has_preds and interval_disabled)
        
        return run_btn_disabled, tabs_disabled, tabs_disabled, tabs_disabled

    # Download logs
    @app.callback(
        Output("download-logs", "data"),
        Input("btn-download-log", "n_clicks"),
        prevent_initial_call=True,
    )
    def download_logs(n_clicks):
        if not n_clicks:
            raise PreventUpdate
        if not os.path.exists(DEBUG_LOG):
            return dcc.send_string("No logs available.", "logs.txt")
        with open(DEBUG_LOG, "r") as fh:
            return dcc.send_string(fh.read(), "processing_logs.txt")

    # Populate graph sheet select
    @app.callback(
        Output("graph-sheet-select", "data"),
        Input("predictions-store", "data"),
        prevent_initial_call=False,
    )
    def populate_graph_sheets(preds):
        if preds and isinstance(preds, dict) and len(preds) > 0:
            return [{"label": k, "value": k} for k in sorted(preds.keys())]
        try:
            if os.path.exists(PRED_JSON):
                with open(PRED_JSON, "r") as fh:
                    loaded = json.load(fh)
                if isinstance(loaded, dict) and loaded:
                    return [{"label": k, "value": k} for k in sorted(loaded.keys())]
        except Exception:
            pass
        return []
    
    # NEW: Auto-update Header Labels based on processed data
    @app.callback(
        Output("forecast-metric-label", "children"),
        Output("artifact-metric-label", "children"),
        Input("predictions-store", "data"),
    )
    def update_labels(preds):
        if not preds:
            return "Forecast Overview", "Analysis Artifacts"
        
        try:
            # Auto-detect first sheet and metric
            sheet = next(iter(preds.keys()))
            if "metrics" in preds[sheet] and preds[sheet]["metrics"]:
                metric = next(iter(preds[sheet]["metrics"].keys()))
                label = f"{metric} ({sheet})"
                return f"Forecast: {label}", f"Artifacts: {label}"
        except Exception:
            pass
            
        return "Forecast Overview", "Analysis Artifacts"
    
    @app.callback(
        Output("graph-sheet-select", "value"),
        Input("graph-sheet-select", "data"),
        State("graph-sheet-select", "value"),
        prevent_initial_call=False,
    )
    def auto_select_graph_sheet(options, current):
        if current: return current
        if options and isinstance(options, list) and len(options) > 0:
            return options[0]["value"]
        return None

    # Combined callback for graph-metric-select (single writer for its outputs)
    @app.callback(
        Output("graph-metric-select", "data"),
        Output("graph-metric-select", "value"),
        Output("graph-metric-select", "disabled"),
        Input("graph-sheet-select", "value"),       # user-selected sheet in graphs tab
        State("predictions-store", "data"),         # predictions written by worker
        State("uploaded-dfs", "data"),              # uploaded raw dfs
        prevent_initial_call=False,
    )
    def combined_populate_graph_metrics(graph_sheet, preds, uploaded_dfs):
        if not graph_sheet: return [], None, True

        options = []
        try:
            if preds and isinstance(preds, dict) and graph_sheet in preds:
                sheet_obj = preds.get(graph_sheet, {}) or {}
                metrics_container = sheet_obj.get("metrics", sheet_obj) if isinstance(sheet_obj, dict) else {}
                if isinstance(metrics_container, dict) and metrics_container:
                    options = [{"label": m, "value": m} for m in sorted(metrics_container.keys())]
        except Exception:
            options = []

        if not options: return [], None, True

        return options, options[0]["value"], False

    # Render graphs
    @app.callback(
        [Output("best-model-display", "children"),
        Output("graph-container", "children")],
        [Input("predictions-store", "data"),
        Input("adjusted-forecast-store", "data")], 
        prevent_initial_call=False,
    )
    def render_graph(preds, adjusted_data):
        if not preds:
            return None, dmc.Text("No predictions available. Run the pipeline first.")

        try:
            # Standard extraction of the active metric sheet
            sheet = next(iter(preds.keys()))
            sheet_obj = preds[sheet]
            metric = next(iter(sheet_obj["metrics"].keys()))
            metric_obj = sheet_obj["metrics"][metric]
        except (StopIteration, KeyError, TypeError, AttributeError):
            return None, dmc.Text("Waiting for data...")
        
        model_name = metric_obj.get("best_model") or metric_obj.get("model") or "Unknown"
        acc_val = metric_obj.get("accuracy", 0.0)
        mae_val = metric_obj.get("mae") or 0.0

        # 1. BIAS CALCULATION LOGIC
        df = pd.DataFrame(metric_obj.get("records", []))
        bias_val = 0.0
        if "TestActual" in df.columns and "TestPrediction" in df.columns:
            valid = df.dropna(subset=["TestActual", "TestPrediction"])
            if not valid.empty:
                sum_act = valid["TestActual"].sum()
                sum_pred = valid["TestPrediction"].sum()
                if sum_act != 0:
                    bias_val = ((sum_act - sum_pred) / sum_act) * 100

        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

        # 2. Logic for "Adjustment" Badge
        # adjustment_badge = []
        # if adjusted_data:
        #     adjustment_badge = [dmc.Badge("ADJUSTED BY AI", color="indigo", variant="filled", size="lg", radius="xl")]

        # 3. METRICS STRIP WITH BIAS ADDED
        metrics_strip = [
            dmc.Badge(f"BEST MODEL: {model_name.upper()}", color="gray", variant="outline", size="lg", radius="xl"),                
            dmc.Badge(f"ACCURACY: {int(round(float(acc_val)))}%", color="blue", variant="light", size="lg", radius="xl"),
            dmc.Badge(f"BIAS: {bias_val:+.1f}%", color="indigo", variant="light", size="lg", radius="xl"), # RESTORED BIAS
            dmc.Badge(f"AVG. ERROR: {int(round(float(mae_val)))}", color="blue", variant="light", size="lg", radius="xl"),
        ] # + adjustment_badge
        
        fig = go.Figure()

        # Trace 1: Historical Actuals (Standard Blue)
        if "TrainRaw" in df.columns:
            fig.add_trace(go.Scatter(
                x=df["Date"], y=df["TrainRaw"], mode="lines+markers",
                name="Train Actual", line=dict(color="#1f77b4"), connectgaps=False
            ))
        elif "TrainActual" in df.columns: 
            fig.add_trace(go.Scatter(
                x=df["Date"], y=df["TrainActual"], mode="lines+markers",
                name="Train Actual (Cleaned)", line=dict(color="#1f77b4"), 
            ))

        # Trace 2: Test Set Actuals & Predictions
        if "TestActual" in df.columns:
            fig.add_trace(go.Scatter(
                x=df["Date"], y=df["TestActual"], mode="lines+markers",
                name="Test Actual", line=dict(color="#ff7f0e"), connectgaps=False
            ))
        if "TestPrediction" in df.columns:
            fig.add_trace(go.Scatter(
                x=df["Date"], y=df["TestPrediction"], mode="lines+markers",
                name="Test Prediction", line=dict(color="#d62728", dash="dot"), 
            ))

        # Trace 3: FORECAST COMPARISON LOGIC (Baseline Green vs. Adjusted Indigo)
        if "Forecast" in df.columns:
            # ORIGINAL BASELINE: Always Green
            fig.add_trace(go.Scatter(
                x=df["Date"], y=df["Forecast"], mode="lines+markers",
                name="Forecast", 
                line=dict(color="#2ca02c", width=2), 
                opacity=0.4 if adjusted_data else 1.0 
            ))
            
            if adjusted_data:
                # ADJUSTED FORECAST: Highlighted Indigo
                df_adj = pd.DataFrame(adjusted_data)
                df_adj["Date"] = pd.to_datetime(df_adj["Date"])
                
                df_adj_forecast = df_adj[df_adj["Forecast"].notna()]
                
                fig.add_trace(go.Scatter(
                    x=df_adj_forecast["Date"], y=df_adj_forecast["Forecast"], mode="lines+markers",
                    name="Adjusted Forecast", 
                    line=dict(color="#6a11cb", width=3), 
                    marker=dict(size=8, symbol="diamond")
                ))

        fig.update_layout(
            template="plotly_white", 
            margin=dict(t=20, b=30, l=50, r=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )

        return metrics_strip, dcc.Graph(figure=fig, style={"height": "70vh"})
    
    # Callback to handle CSV Export for the Forecast Tab
    @app.callback(
        Output("download-csv", "data"),
        Input("export-csv", "n_clicks"),
        State("predictions-store", "data"),
        prevent_initial_call=True,
    )
    def export_forecast_to_csv(n_clicks, preds):
        if not n_clicks or not preds:
            raise PreventUpdate

        try:
            # 1. Identify the current sheet and metric being viewed
            sheet = next(iter(preds.keys()))
            metric = next(iter(preds[sheet]["metrics"].keys()))
            metric_data = preds[sheet]["metrics"][metric]
            
            # 2. Convert the internal 'records' list back to a DataFrame
            records = metric_data.get("records", [])
            if not records:
                raise PreventUpdate
                
            df_export = pd.DataFrame(records)
            
            # 3. Clean up date formatting for Excel compatibility
            if "Date" in df_export.columns:
                df_export["Date"] = pd.to_datetime(df_export["Date"]).dt.strftime('%Y-%m-%d')
            
            # 4. Generate the download
            filename = f"forecast_{metric}_{datetime.now().strftime('%Y%m%d')}.csv"
            return dcc.send_data_frame(df_export.to_csv, filename, index=False)
            
        except Exception as e:
            print(f"Export CSV Error: {str(e)}")
            raise PreventUpdate

    # 3. Render Experiment Details (Using Service)
    @app.callback(
        [Output("experiment-graph", "figure"),
         Output("experiment-split-info", "children")], # New Output for badges
        [Input("predictions-store", "data"),
         Input("experiment-perf-metric", "value")],
        prevent_initial_call=True,
    )
    def render_experiment_artifact(preds, perf_metric):
        if not preds or not perf_metric:
            return go.Figure(), []

        try:
            sheet = next(iter(preds.keys()))
            metric = next(iter(preds[sheet]["metrics"].keys()))
            metric_data = preds[sheet]["metrics"][metric]
            
            # 1. Parse records to calculate split details
            records = metric_data.get("records", [])
            df = pd.DataFrame(records)
            if "Date" in df.columns:
                df["Date"] = pd.to_datetime(df["Date"])
                
                train_df = df[df["TrainActual"].notna()]
                test_df = df[df["TestActual"].notna()]
                
                # 2. Create UI Badges
                split_badges = [
                    dmc.Badge(
                        f"Train: {len(train_df)} Rows ({train_df['Date'].min().strftime('%Y-%m-%d')} to {train_df['Date'].max().strftime('%Y-%m-%d')})",
                        color="blue", variant="light", radius="sm"
                    ),
                    dmc.Badge(
                        f"Test: {len(test_df)} Rows ({test_df['Date'].min().strftime('%Y-%m-%d')} to {test_df['Date'].max().strftime('%Y-%m-%d')})",
                        color="orange", variant="light", radius="sm"
                    ),
                ]
            else:
                split_badges = []

            # 3. Generate Graph
            fig = generate_experiment_figure(sheet, metric, perf_metric)
            return fig, split_badges
            
        except Exception as e: 
            return go.Figure(), [dmc.Text(f"Error loading split info: {str(e)}", size="xs", c="red")]
    
    # ------------------------------------------------------------------
    #  KNOW YOUR DATA (KYD) TAB CALLBACKS
    # ------------------------------------------------------------------

    # 1. Populate KYD Sheet Select from Uploaded Data
    @app.callback(
        Output("kyd-sheet-select", "data"),
        Output("kyd-sheet-select", "value"), # Auto-select first sheet
        Input("store-target-dfs", "data"),
    )
    def update_kyd_sheet_dropdown(uploaded_dfs):
        if not uploaded_dfs:
            return [], None
        sheets = list(uploaded_dfs.keys())
        # Default to first sheet
        return [{"label": s, "value": s} for s in sheets], sheets[0]

    # 2. Populate KYD Metric (Y) and External (X) from Selected Sheet
    @app.callback(
        Output("kyd-metric-select", "data"),
        Output("kyd-x-select", "data"),
        Input("kyd-sheet-select", "value"),
        State("store-target-dfs", "data"),
    )
    def update_kyd_variables(sheet, uploaded_dfs):
        if not sheet or not uploaded_dfs or sheet not in uploaded_dfs:
            return [], []
        
        try:
            # Read Data
            df = pd.read_json(uploaded_dfs[sheet], orient="split")
            
            # Find Numeric Columns
            numeric_cols = [
                c for c in df.columns 
                if pd.api.types.is_numeric_dtype(df[c]) and "date" not in str(c).lower()
            ]
            
            options = [{"label": c, "value": c} for c in numeric_cols]
            
            # Return same options for both Y and X
            return options, options
        except Exception:
            return [], []

    # ------------------------------------------------------------------
    #  3. RUN HEALTH CHECK & GENERATE ALL KYD CHARTS (MERGED STATIONARITY & DECOMPOSITION)
    # ------------------------------------------------------------------
    @app.callback(
        Output("kyd-empty-state", "style"),
        Output("kyd-main-content", "style"),
        Output("tab-x-health", "style"),      
        Output("tab-x-collinear", "style"),   
        Output("tab-x-dist", "style"),        
        Output("health-check-content-raw", "children"),
        Output("kyd-features-graph", "children"), 
        Output("kyd-x-distribution-graph-raw", "children"), 
        Output("kyd-stationarity-graph-raw", "figure"),
        Output("kyd-stationarity-graph-processed", "figure"),
        Output("kyd-decomposition-graph-raw", "figure"),
        Output("kyd-decomposition-graph-processed", "figure"),
        Output("kyd-acf-pacf-graph-raw", "figure"),
        Output("kyd-acf-pacf-graph-processed", "figure"),
        Output("kyd-y-distribution-graph-raw", "figure"),
        Output("kyd-y-distribution-graph-processed", "figure"),
        Output("kyd-collinear-type-label", "children"), 
        Output("kyd-y-dist-results-raw", "children"),
        Output("kyd-y-dist-results-processed", "children"),
        
        Input("store-target-dfs", "data"), 
        Input("store-feature-dfs", "data"), 
        Input("predictions-store", "data"), 
        Input("kyd-x-plot-type", "value"),
        Input("kyd-y-plot-type", "value"),
        Input("kyd-corr-method", "value"),
        Input("select-sheet-target", "value"),
        Input("select-col-target", "value"),
        prevent_initial_call=False 
    )
    def run_health_check(target_store, feature_store, preds, plot_type_x, plot_type_y, corr_method, target_sheet, target_col):
        has_y = (target_store is not None and target_sheet in target_store)
        has_x = (feature_store is not None and len(feature_store) > 0)
        has_preds = (preds is not None and len(preds) > 0)

        if not (has_y or has_x):
            return (no_update,) * 19

        style_empty, style_content, style_always_visible = {"display": "none"}, {"display": "block"}, {"display": "block"}
        from layout.main_layout import create_x_placeholder
        x_placeholder = create_x_placeholder("Upload X feature file for analysis")
        
        ret_health_raw = x_placeholder
        ret_dist_x_raw = x_placeholder
        ret_feat = x_placeholder
        ret_dist_res_raw = dmc.Text("No data available", size="xs")
        ret_dist_res_proc = dmc.Text("Waiting for engine...", size="xs")
        
        empty_fig = {"data": [], "layout": {"template": "plotly_white"}}
        ret_stat_raw, ret_stat_proc = empty_fig, empty_fig
        ret_decomp_raw, ret_decomp_proc = empty_fig, empty_fig
        ret_acf_raw, ret_acf_proc = empty_fig, empty_fig
        ret_dist_y_raw, ret_dist_y_proc = empty_fig, empty_fig

        collinear_label = "Linear Collinearity" if corr_method == "pearson" else "Non-Linear Collinearity"

        if has_x:
            try:
                sheet_x = list(feature_store.keys())[0]
                df_x = pd.read_json(io.StringIO(feature_store[sheet_x]), orient='split')
                x_cols = [c for c in df_x.columns if pd.api.types.is_numeric_dtype(df_x[c]) and "date" not in str(c).lower()]
                
                recs_x_raw = df_x.to_dict(orient="records")
                ret_health_raw = dcc.Graph(figure=generate_health_summary_table(recs_x_raw, x_cols), config={'displayModeBar': False})
                ret_dist_x_raw = dcc.Graph(
                    figure=generate_distribution_figure(recs_x_raw, x_cols=x_cols, plot_type=plot_type_x),
                    responsive=True, style={"height": "100%", "width": "100%"}
                )
                
                # --- DYNAMIC MERGE FOR COLLINEARITY (BUG FIXES) ---
                recs_corr = recs_x_raw 
                if has_preds:
                    sheet_p = next(iter(preds.keys()))
                    metric_p = next(iter(preds[sheet_p]["metrics"].keys()))
                    recs_corr = preds[sheet_p]["metrics"][metric_p].get("records", [])
                elif has_y and target_col:
                    try:
                        df_y_tmp = pd.read_json(io.StringIO(target_store[target_sheet]), orient='split')
                        
                        # Robustly find date columns
                        date_x = next((c for c in df_x.columns if "date" in str(c).lower().strip()), None)
                        date_y = next((c for c in df_y_tmp.columns if "date" in str(c).lower().strip()), None)

                        # Fallback: Specifically for Club_311 naming convention
                        if not date_y and "DATE" in df_y_tmp.columns:
                            date_y = "DATE"
                        if not date_x and "DATE" in df_x.columns:
                            date_x = "DATE"
                        
                        if date_x and date_y:
                            df_x_dt = df_x.copy()
                            df_y_dt = df_y_tmp[[date_y, target_col]].copy()
                            
                            # FIX: Force to datetime and NORMALIZE to remove hidden timestamps
                            df_x_dt[date_x] = pd.to_datetime(df_x_dt[date_x], errors='coerce').dt.normalize()
                            df_y_dt[date_y] = pd.to_datetime(df_y_dt[date_y], errors='coerce').dt.normalize()
                            
                            # Clean target column for correlation
                            df_y_dt[target_col] = pd.to_numeric(df_y_dt[target_col], errors='coerce')
                            
                            # Merge with inner join
                            merged_df = pd.merge(df_x_dt, df_y_dt, left_on=date_x, right_on=date_y, how='inner')
                            
                            if not merged_df.empty:
                                # FIX: Use ffill() instead of deprecated method='ffill' to avoid crash
                                recs_corr = merged_df.ffill().bfill().to_dict(orient="records")
                            else:
                                # Fallback to feature-only correlation if merge results in 0 rows
                                recs_corr = recs_x_raw
                    except Exception as merge_err: 
                        print(f"Collinearity Merge Warning: {merge_err}")

                ret_feat = dcc.Graph(
                    figure=generate_feature_heatmap(recs_corr, target_col=target_col, x_cols=x_cols, method=corr_method),
                    responsive=True, style={"height": "100%", "width": "100%"}
                )
            except Exception as e: print(f"X-Processing Error: {e}")

        # --- Y-Analysis Processing (Logic Preserved) ---
        if has_y and target_col:
            try:
                df_y = pd.read_json(io.StringIO(target_store[target_sheet]), orient='split')
                date_col_y = next((c for c in df_y.columns if "date" in str(c).lower()), "Date")
                df_y[date_col_y] = pd.to_datetime(df_y[date_col_y])
                df_y = df_y.dropna(subset=[target_col]).sort_values(date_col_y)
                recs_y_raw = [{"Date": r[date_col_y], "TrainActual": r[target_col]} for _, r in df_y.iterrows()]
                series_raw = pd.Series([r["TrainActual"] for r in recs_y_raw]).dropna()
                
                ret_stat_raw = generate_stationarity_figure(recs_y_raw, target_col).to_dict()
                stats_raw = {"adi": calculate_adi(series_raw), "cv2": calculate_cv2(series_raw), "type": classify_demand(calculate_adi(series_raw), calculate_cv2(series_raw))}
                ret_decomp_raw = generate_seasonality_figure(recs_y_raw, target_col, stats_raw).to_dict()
                ret_acf_raw = generate_acf_pacf_figure(recs_y_raw, target_col).to_dict()
                ret_dist_y_raw = generate_distribution_figure(recs_y_raw, metric=target_col, plot_type=plot_type_y).to_dict()
                
                if plot_type_y == "histogram":
                    ret_dist_res_raw = dmc.Alert(f"Mean: {series_raw.mean():.2f} | Med: {series_raw.median():.2f} | Skew: {series_raw.skew():.2f}", color="gray", variant="light", p="xs")
                elif plot_type_y == "boxplot":
                    q1, q3 = series_raw.quantile(0.25), series_raw.quantile(0.75)
                    iqr = q3 - q1
                    outlier_pct = (len(series_raw[(series_raw < (q1 - 1.5 * iqr)) | (series_raw > (q3 + 1.5 * iqr))]) / len(series_raw)) * 100
                    ret_dist_res_raw = dmc.Alert(f"Q1: {q1:.2f} | Q3: {q3:.2f} | Outliers: {outlier_pct:.1f}%", color="gray", variant="light", p="xs")
                else: ret_dist_res_raw = html.Div()

                if has_preds:
                    try:
                        sheet_p = next(iter(preds.keys()))
                        metric_p = next(iter(preds[sheet_p]["metrics"].keys()))
                        recs_proc = preds[sheet_p]["metrics"][metric_p].get("records", [])
                        series_proc = pd.Series([r.get("TrainActual") for r in recs_proc if r.get("TrainActual") is not None]).dropna()
                        ret_stat_proc = generate_stationarity_figure(recs_proc, target_col).to_dict()
                        stats_proc = {"adi": calculate_adi(series_proc), "cv2": calculate_cv2(series_proc), "type": classify_demand(calculate_adi(series_proc), calculate_cv2(series_proc))}
                        ret_decomp_proc = generate_seasonality_figure(recs_proc, target_col, stats_proc).to_dict()
                        ret_acf_proc = generate_acf_pacf_figure(recs_proc, target_col).to_dict()
                        ret_dist_y_proc = generate_distribution_figure(recs_proc, metric=target_col, plot_type=plot_type_y).to_dict()
                        
                        if plot_type_y == "histogram":
                            ret_dist_res_proc = dmc.Alert(f"Mean: {series_proc.mean():.2f} | Med: {series_proc.median():.2f} | Skew: {series_proc.skew():.2f}", color="blue", variant="light", p="xs")
                        elif plot_type_y == "boxplot":
                            pq1, pq3 = series_proc.quantile(0.25), series_proc.quantile(0.75)
                            piqr = pq3 - pq1
                            p_outlier_pct = (len(series_proc[(series_proc < (pq1 - 1.5 * piqr)) | (series_proc > (pq3 + 1.5 * piqr))]) / len(series_proc)) * 100
                            ret_dist_res_proc = dmc.Alert(f"Q1: {pq1:.2f} | Q3: {pq3:.2f} | Outliers: {p_outlier_pct:.1f}%", color="blue", variant="light", p="xs")
                        else: ret_dist_res_proc = html.Div()
                    except: pass
                else: ret_dist_y_proc = empty_fig
            except Exception as e: print(f"Y-Processing Error: {e}")

        return (
            style_empty, style_content, 
            style_always_visible, style_always_visible, style_always_visible, 
            ret_health_raw, ret_feat, ret_dist_x_raw, 
            ret_stat_raw, ret_stat_proc, 
            ret_decomp_raw, ret_decomp_proc, 
            ret_acf_raw, ret_acf_proc, 
            ret_dist_y_raw, ret_dist_y_proc,
            collinear_label, 
            ret_dist_res_raw, ret_dist_res_proc
        )
    
    @app.callback(
        Output("kyd-holiday-container", "children"),
        Input("store-target-dfs", "data"),
        Input("store-feature-dfs", "data"),
        Input("select-col-target", "value"),
        Input("region-select", "value"),
        State("select-sheet-target", "value"),
        prevent_initial_call=False
    )
    def render_holiday_analysis(target_store, feature_store, target_col, selected_regions, target_sheet):
        # 1. Validation check
        if not target_store or not target_sheet or not target_col:
            return dmc.Text("Upload a Target (Y) file and select a column to begin analysis.", c="dimmed", ta="center", py="xl")

        # 2. Region selection requirement
        if not selected_regions or len(selected_regions) == 0:
            return dmc.Alert(
                "Please select a Region (e.g., India or United States) in the configuration toolbar to view holiday impact.",
                title="Region Selection Required",
                color="orange",
                variant="light",
                icon=DashIconify(icon="carbon:location-hazard")
            )

        try:
            # 3. Parse Target Data with StringIO to avoid deprecation
            df_y = pd.read_json(io.StringIO(target_store[target_sheet]), orient='split')
            date_col_y = next((c for c in df_y.columns if "date" in str(c).lower()), None)
            
            if not date_col_y:
                return dmc.Alert("Date column not found in Target file.", color="red")
                
            df_y[date_col_y] = pd.to_datetime(df_y[date_col_y])
            df_y = df_y.set_index(date_col_y).sort_index()

            # 4. Anchor on Y and join X
            df_hol = df_y[[target_col]].reset_index()
            if feature_store and len(feature_store) > 0:
                try:
                    sheet_x = list(feature_store.keys())[0]
                    df_x = pd.read_json(io.StringIO(feature_store[sheet_x]), orient='split')
                    date_col_x = next((c for c in df_x.columns if "date" in str(c).lower()), None)
                    if date_col_x:
                        df_x[date_col_x] = pd.to_datetime(df_x[date_col_x])
                        df_hol = df_y[[target_col]].join(df_x.set_index(date_col_x), how="left").reset_index()
                except: pass

            # 5. DYNAMIC HOLIDAY GENERATION
            regions = selected_regions if selected_regions else []
            
            # This utility returns a DatetimeIndex
            dynamic_holidays = get_region_holidays(df_hol[date_col_y], regions)

            # FIX: Use 'isin' for boolean flag and apply conditional naming
            df_hol["Is_Holiday"] = df_hol[date_col_y].isin(dynamic_holidays).astype(int)
            
            # Use lambda to check index presence since .get() is not available
            df_hol["Holiday_Name"] = df_hol[date_col_y].apply(
                lambda x: "Regional Holiday" if x in dynamic_holidays else None
            )

            # 6. Generate Figures via Artifact Service
            records = df_hol.to_dict(orient="records")
            table_fig = generate_holiday_table(records, target_col)
            charts_fig = generate_holiday_charts(records, target_col)
            window_fig = generate_holiday_windows(records, target_col)

            return dmc.Stack(gap="lg", children=[
                dmc.Stack(gap="xs", children=[
                    dmc.Text("Holiday Inventory", fw=700, size="md", style={"color": "#1c1e21"}),
                    elevated_card(children=dcc.Graph(figure=table_fig, config={'displayModeBar': False}), height="auto", overflow="visible"),
                ]),
                dmc.Stack(gap="xs", children=[
                    dmc.Text("Holiday Impact Analysis", fw=700, size="md", style={"color": "#1c1e21"}),
                    elevated_card(children=dcc.Graph(figure=charts_fig, config={'displayModeBar': True}), height="600px", overflow="auto"),
                ]),
                dmc.Stack(gap="xs", children=[
                    dmc.Text("Holiday Temporal Impact", fw=700, size="md", style={"color": "#1c1e21"}),
                    elevated_card(children=dcc.Graph(figure=window_fig), height="900px", overflow="auto"),
                ])
            ])

        except Exception as e:
            return dmc.Alert(f"Holiday Analysis Error: {str(e)}", color="red", variant="filled")
        
    # 2.5 Render Data Treatment Analysis (Before/After & JSON)
    @app.callback(
        Output("treatment-graph", "figure"),
        Output("y-treatment-json", "children"),
        Output("x-treatment-json", "children"),
        Output("y-treatment-title", "children"), # Don't forget this output!
        Input("predictions-store", "data"),
        prevent_initial_call=True,
    )
    def render_treatment_analysis(preds):
        if not preds:
            return go.Figure(), "No Profile", "No Profile", "Target (Y)"

        try:
            sheet = next(iter(preds.keys()))
            metric = next(iter(preds[sheet]["metrics"].keys()))
            metric_data = preds[sheet]["metrics"][metric]
        except:
            return go.Figure(), "Error", "Error", "Error"
        
        records = metric_data.get("records", [])
        fig = generate_treatment_comparison_figure(records, metric)
        
        import json as json_lib
        y_json = metric_data.get("y_treatment", {})
        x_json = metric_data.get("x_treatment", {})
        
        return fig, json_lib.dumps(y_json, indent=2), json_lib.dumps(x_json, indent=2), f"{metric} (Y) Treatment Profile"
    
    # 2.6 Render Feature Analysis Graph
    @app.callback(
        Output("features-graph", "figure"), # Artifacts ID
        Input("predictions-store", "data"),
        Input("artifact-corr-method", "value"), # ADDED: New Input for correlation method
        prevent_initial_call=True,
    )
    def render_features_analysis(preds, corr_method): # ADDED: corr_method argument
        if not preds: 
            return go.Figure()
        
        try:
            sheet = next(iter(preds.keys()))
            metric = next(iter(preds[sheet]["metrics"].keys()))
            metric_data = preds[sheet]["metrics"][metric]
            records = metric_data.get("records", [])
            
            if not records:
                return go.Figure()
            
            df = pd.DataFrame(records)
            
            # Define result columns to ignore so we can find ALL features
            non_feature_cols = [
                "Date", "TrainActual", "TrainRaw", "TestActual", 
                "TestPrediction", "Forecast", "Is_Holiday"
            ]
            
            # Identify features (will include internal lags like lag_1, roll_mean_7)
            feature_cols = [c for c in df.columns if c not in non_feature_cols]

            return generate_multivariate_feature_analysis(records, metric, feature_cols, method=corr_method)
                
        except Exception as e:
            print(f"Artifacts Feature Graph Error: {e}")
            return go.Figure().update_layout(title=f"Error: {str(e)}")
        
    # --- New LLM Callback in register_processing_callbacks() ---
    @app.callback(
        [Output("adjusted-forecast-store", "data"),
        Output("chat-history", "children"),
        Output("llm-constraint-input", "value")],
        [Input("apply-llm-btn", "n_clicks"),
        Input("reset-llm-btn", "n_clicks")],
        [State("llm-constraint-input", "value"),
        State("predictions-store", "data"),
        State("adjusted-forecast-store", "data"), # NEW: Read current state to stack changes
        State("chat-history", "children")],
        prevent_initial_call=True
    )
    def handle_llm_adjustment(apply_n, reset_n, prompt, preds, adjusted_data, history):
        ctx = callback_context
        if not ctx.triggered:
            raise PreventUpdate
        
        trigger = ctx.triggered[0]["prop_id"].split(".")[0]

        # 1. Reset Logic: Returns to original baseline
        if trigger == "reset-llm-btn":
            reset_alert = dmc.Alert(
                "Forecast reset to original ML baseline.", 
                color="gray", variant="light", radius="md", mb="sm"
            )
            return None, [reset_alert], ""

        # 2. Guard Rails
        if not prompt or not preds:
            error_box = dmc.Alert(
                "No prompt or active forecast found.", 
                title="Input Error", color="red", variant="filled", radius="md", mb="sm"
            )
            return no_update, history, no_update

        try:
            # 3. Base Data Selection: Stack on existing adjustment or start from baseline
            if adjusted_data:
                df = pd.DataFrame(adjusted_data)
            else:
                sheet = next(iter(preds.keys()))
                metric = next(iter(preds[sheet]["metrics"].keys()))
                records = preds[sheet]["metrics"][metric].get("records", [])
                df = pd.DataFrame(records)
                
            df["Date"] = pd.to_datetime(df["Date"])
            
            # 4. LLM Code Generation
            metadata = {col: str(dtype) for col, dtype in df.dtypes.items()}
            generated_code = LLMService.generate_adjustment_code(prompt, metadata)
            
            if not generated_code:
                error_box = dmc.Alert(
                    "LLM failed to generate executable code.", 
                    title="Generation Error", color="red", variant="light", radius="md", mb="sm"
                )
                return no_update, history + [error_box], ""

            # 5. Execute code safely
            df_adjusted = ConstraintExecutor.execute_safely(df, generated_code)
            df_adjusted["Date"] = df_adjusted["Date"].dt.strftime('%Y-%m-%dT%H:%M:%S')
            
            # 6. Create Chat Bubble with Undo Action
            user_msg = dmc.Paper(
                p="sm", radius="md", mb="sm", withBorder=True,
                style={"backgroundColor": "#f8f9fa"},
                children=[
                    dmc.Group(justify="space-between", children=[
                        dmc.Text(f"Adjustment {len(history)}", fw=700, size="xs", c="indigo"),
                        # Pattern-matching ID for the Undo button
                        dmc.ActionIcon(
                            DashIconify(icon="carbon:undo", width=14),
                            id={"type": "undo-btn", "index": len(history)},
                            variant="subtle", color="gray", size="sm"
                        )
                    ]),
                    dmc.Text(prompt, size="sm", mt=4),
                    dmc.Code(generated_code, block=True, mt="xs", color="gray") 
                ]
            )
            history.append(user_msg)
            
            return df_adjusted.to_dict(orient="records"), history, ""

        except Exception as e:
            error_box = dmc.Alert(
                f"Logic Error: {str(e)}", title="Execution Failed",
                color="red", variant="light", radius="md", mb="sm",
                icon=DashIconify(icon="carbon:warning-alt-filled")
            )
            return no_update, history + [error_box], no_update
        

    @app.callback(
        [Output("adjusted-forecast-store", "data", allow_duplicate=True),
        Output("chat-history", "children", allow_duplicate=True)],
        Input({"type": "undo-btn", "index": ALL}, "n_clicks"),
        [State("predictions-store", "data"),
        State("chat-history", "children")],
        prevent_initial_call=True
    )
    def undo_last_adjustment(n_clicks, preds, history):
        # Check if any undo button was actually clicked
        if not any(n_clicks) or not history:
            raise PreventUpdate

        # Remove the most recent adjustment bubble
        history.pop()

        # Case: If history is now empty (or only contains the initial alert)
        if not history or (len(history) == 1 and "Ready to Assist" in str(history[0])):
            return None, history

        try:
            # Re-initialize the base DataFrame from original ML results
            sheet = next(iter(preds.keys()))
            metric = next(iter(preds[sheet]["metrics"].keys()))
            df = pd.DataFrame(preds[sheet]["metrics"][metric].get("records", []))
            df["Date"] = pd.to_datetime(df["Date"])

            # Re-apply every remaining code block in the history to rebuild the state
            for bubble in history:
                try:
                    # Dig into the dmc.Paper structure to find the dmc.Code content
                    # Structure: Paper -> [Group, Text, Code]
                    code_to_reapply = bubble['props']['children'][2]['props']['children']
                    df = ConstraintExecutor.execute_safely(df, code_to_reapply)
                except (KeyError, IndexError, TypeError):
                    continue # Skip alerts or bubbles without code
            
            df["Date"] = df["Date"].dt.strftime('%Y-%m-%dT%H:%M:%S')
            return df.to_dict(orient="records"), history
            
        except Exception as e:
            print(f"Undo Reconstruction Failed: {e}")
            return None, history