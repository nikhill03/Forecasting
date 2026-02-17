import base64
import html
import io
import json
import os
import threading
import traceback
from datetime import datetime
from typing import Dict, Any, List, Optional

import dash_mantine_components as dmc
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, dcc, html, callback_context, no_update
from dash.exceptions import PreventUpdate

import plotly.subplots as sp
from services.processing_engine import HISTORY_LOG, PROGRESS_JSON  

from services.data_handling import DataHandling 

from services.forecast_artifact import (
    generate_experiment_figure, generate_health_summary_table, generate_seasonality_figure, generate_stationarity_figure,
    generate_acf_pacf_figure, generate_distribution_figure, generate_feature_heatmap,
    generate_multivariate_feature_analysis, generate_treatment_comparison_figure
)

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


def _now_ts():
    return datetime.now().strftime("%H:%M:%S")

def _append_log(msg: str):
    line = f"[{_now_ts()}] {msg}"
    IN_MEMORY_LOGS.append(line)
    try:
        with open(DEBUG_LOG, "a") as fh:
            fh.write(line + "\n")
    except Exception:
        pass

def _render_console_lines(lines):
    rendered = []
    for line in lines:
        is_error = (
            "error:" in line.lower()
            or "exception" in line.lower()
            or "failed" in line.lower()
            or "critical" in line.lower()
        )

        is_success = "success:" in line.lower()

        rendered.append(
            dmc.Text(
                line,
                size="xs",
                style={
                    "color": (
                        "#ff4d4f" if is_error
                        else "#2ecc71" if is_success
                        else "#e6eef8"
                    ),
                    "fontFamily": "monospace",
                    "whiteSpace": "pre-wrap",
                },
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
        Output("log-interval", "disabled"),
        Output("log-store", "data"),
        Output("console-output", "children"),
        Output("predictions-store", "data"),
        Output("graph-store", "data"),
        Output("content-tabs", "value"),
        
        Input("run-models-btn", "n_clicks"),
        Input("btn-stop", "n_clicks"),
        Input("btn-restart", "n_clicks"),
        Input("log-interval", "n_intervals"),
        Input("clear-graph", "n_clicks"),
        
        # Data Inputs
        State("store-target-dfs", "data"),
        State("select-sheet-target", "value"),
        State("select-col-target", "value"),
        State("store-feature-dfs", "data"),
        
        # Config Inputs
        State("forecast-horizon-input", "value"),
        
        prevent_initial_call=True
    )
    def control_run(n_click, stop_click, restart_click, n_int, clear_click,
                    target_store, target_sheet, target_col, 
                    feature_store, horizon):
        
        global WORKER_THREAD
        global IN_MEMORY_LOGS

        ctx = callback_context
        trigger = ctx.triggered[0]["prop_id"].split(".")[0]
        log_store = IN_MEMORY_LOGS
        
        # --- UI Interactions ---
        if trigger == "clear-graph":
            clear_all_outputs()
            _append_log("Graph cleared.")
            return True, log_store, _render_console_lines(log_store), {}, {}, no_update

        if trigger == "btn-stop":
            # 1. Create the Stop Flag file
            try:
                with open(STOP_FLAG, "w") as fh:
                    fh.write("stop")
            except Exception as e:
                _append_log(f"Error triggering stop: {e}")

            stop_msg = "🛑 Execution STOPPED by user request."
            
            # 2. WRITE TO DISK
            _append_log(stop_msg) 

            # 3. RELOAD FULL HISTORY
            full_history = read_log_tail()
            
            # Sync global memory (Declaration already done at top)
            IN_MEMORY_LOGS = full_history[:]
            
            return True, full_history, _render_console_lines(full_history), no_update, no_update, no_update
        
        # --- Log Polling ---
        if trigger == "log-interval":
            try:
                progress = read_progress() or {}
                preds, figs = read_predictions_and_figs()
                tail = read_log_tail()

                merged = IN_MEMORY_LOGS[:]
                for l in tail:
                    if l not in merged: merged.append(l)

                if preds and os.path.exists(DONE_FLAG):
                    if not any("Execution Successful" in s for s in merged):
                        merged.append(f"[{_now_ts()}] Execution Successful.")
                    return True, merged, _render_console_lines(merged), preds, figs, no_update
                
                if preds:
                    return False, merged, _render_console_lines(merged), preds, figs, no_update

                return False, merged, _render_console_lines(merged), no_update, no_update, no_update
            except:
                pass
            return no_update

        # --- RUN LOGIC ---
        if trigger == "run-models-btn" or trigger == "btn-restart":
            
            # Validation
            if not target_store or not target_sheet or not target_col:
                err = f"[{_now_ts()}] Error: Target data (File + Sheet + Column) is missing."
                _append_log(err)
                return True, log_store + [err], _render_console_lines(log_store + [err]), {}, {}, no_update

            try:
                # 1. Prepare Target (Y)
                df_y = pd.read_json(target_store[target_sheet], orient='split')
                date_col_y = next((c for c in df_y.columns if "date" in str(c).lower()), None)
                
                if not date_col_y: 
                    raise ValueError("Target file missing Date column")
                
                df_y[date_col_y] = pd.to_datetime(df_y[date_col_y])
                df_y = df_y.set_index(date_col_y).sort_index()
                
                # 2. Prepare Features (X) & Merge
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
                        _append_log(f"Merged {len(x_cols_list)} features from X file.")
                    else:
                        _append_log("Warning: X file has no Date column. Skipping merge.")

                # 3. Create "Virtual" CSV
                csv_buffer = io.StringIO()
                df_merged.reset_index().to_csv(csv_buffer, index=False)
                csv_str = csv_buffer.getvalue()
                b64_merged = base64.b64encode(csv_str.encode('utf-8')).decode('utf-8')
                
                # 4. CLEAR EVERYTHING & LAUNCH
                clear_all_outputs()
                IN_MEMORY_LOGS.clear() # Wipe global memory
                
                def _thread_target():
                    try:
                        processing_worker(
                            b64_merged, 
                            ["Sheet1"],
                            [target_col],
                            selected_x_cols=x_cols_list,
                            x_clean_weekday="median",
                            x_clean_weekend="zero",
                            forecast_horizon=int(horizon or 60)
                        )
                    except Exception as e:
                        _append_log(f"Worker Error: {str(e)}")
                        traceback.print_exc()

                with WORKER_THREAD_LOCK:
                    WORKER_THREAD = threading.Thread(target=_thread_target, daemon=True)
                    WORKER_THREAD.start()

                # FIX: Return empty list AND empty rendered lines to wipe console immediately
                return False, [], _render_console_lines([]), {}, {}, "console"

            except Exception as e:
                traceback.print_exc()
                err = f"Error: {str(e)}"
                return True, [err], _render_console_lines([err]), {}, {}, no_update
        
        raise PreventUpdate

   # Progress bar callback (FIXED: Resets on page load)
    @app.callback(
        Output("processing-progress", "value"),
        Output("progress-text", "children"),
        Input("log-interval", "n_intervals"),
        prevent_initial_call=False,
    )
    def update_progress(n):
        # FIX: On initial load (n=0), force reset regardless of file state
        if n == 0 or n is None:
            return 0, "Ready to start..."

        progress_data = read_progress() 
        
        # Default safety
        if not progress_data:
            return 0, "Ready to start..."

        pct = progress_data.get("percent", 0)
        msg = progress_data.get("message", "")

        # Format text: Percentage based
        if pct >= 100:
            txt = "Processing Completed. 100%"
        elif pct > 0:
            txt = f"{msg} ({pct}% completed)"
        else:
            txt = msg 

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
        Output("tab-graphs", "disabled"),
        Output("tab-artifacts", "disabled"),  
        Input("predictions-store", "data"),
        Input("log-interval", "disabled"),
        prevent_initial_call=False,
    )
    def toggle_tabs(preds, interval_disabled):
        has_preds = bool(preds and isinstance(preds, dict) and len(preds) > 0)
        should_enable = has_preds and interval_disabled
        return not should_enable, not should_enable

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
    # Render graphs (Auto-detected Single Y)
    @app.callback(
        Output("graph-container", "children"),
        Input("predictions-store", "data"),
        prevent_initial_call=False,
    )
    def render_graph(preds):
        if not preds:
            return dmc.Text("No predictions available. Run the pipeline first.")

        # 1. AUTO-DETECT SHEET & METRIC
        try:
            sheet = next(iter(preds.keys()))
            sheet_obj = preds[sheet]
            if "metrics" not in sheet_obj or not sheet_obj["metrics"]:
                 return dmc.Text("No metrics found in predictions.")
            
            metric = next(iter(sheet_obj["metrics"].keys()))
            metric_obj = sheet_obj["metrics"][metric]
        except (StopIteration, KeyError, TypeError, AttributeError):
             return dmc.Text("Waiting for data...")
        
        # 2. Retrieve values
        model_name = metric_obj.get("best_model") or metric_obj.get("model") or "Unknown"
        acc_val = metric_obj.get("accuracy", 0.0)
        mae_val = metric_obj.get("mae") or 0.0

        # 3. Format Badges
        try:
            final_acc = int(round(float(acc_val)))
            acc_text = f"Accuracy: {final_acc}%"
        except (ValueError, TypeError):
            acc_text = "Accuracy: N/A"

        try:
            final_mae = int(round(float(mae_val)))
            mae_text = f"Avg. Error: {final_mae}"
        except (ValueError, TypeError):
            mae_text = "Avg. Error: N/A"

        metrics_strip = dmc.Group(
            children=[
                dmc.Badge(f"Best Model: {model_name}", color="gray", variant="outline", size="lg"),                
                dmc.Badge(acc_text, color="blue", variant="light", size="lg"),
                dmc.Badge(mae_text, color="blue", variant="light", size="lg"),
            ],
            gap="sm",
            style={"marginBottom": "15px", "marginTop": "5px"}
        )
        
        df = pd.DataFrame(metric_obj.get("records", []))
        
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

        fig = go.Figure()

        # Train actuals
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

        # Test actuals
        if "TestActual" in df.columns:
            fig.add_trace(go.Scatter(
                x=df["Date"], y=df["TestActual"], mode="lines+markers",
                name="Test Actual", line=dict(color="#ff7f0e"), connectgaps=False
            ))

        # Test predictions
        if "TestPrediction" in df.columns:
            fig.add_trace(go.Scatter(
                x=df["Date"], y=df["TestPrediction"], mode="lines",
                name="Test Prediction", line=dict(color="#d62728", dash="dot"), 
            ))

        # Future forecast
        if "Forecast" in df.columns:
            fig.add_trace(go.Scatter(
                x=df["Date"], y=df["Forecast"], mode="lines",
                name="Forecast", line=dict(color="#2ca02c"), 
            ))

        fig.update_layout(
            title=f"Forecast: {metric}", 
            xaxis_title="Date",
            yaxis_title="Volume",
            margin=dict(t=30, b=30, l=50, r=10),
            template="plotly_white",
            autosize=True
        )

        return [metrics_strip, dcc.Graph(figure=fig, style={"height": "60vh"})]

    

    # 2. Render Seasonal Decomposition (Using Service)
    @app.callback(
        Output("decomposition-graph", "figure"),
        Input("predictions-store", "data"), # Changed to Input
        prevent_initial_call=True,
    )
    def render_decomposition_artifact(preds):
        if not preds: return go.Figure()
        try:
            sheet = next(iter(preds.keys()))
            metric = next(iter(preds[sheet]["metrics"].keys()))
            metric_data = preds[sheet]["metrics"][metric]
            records = metric_data.get("records", [])

            stats = {
                "adi": metric_data.get("adi", 0),
                "cv2": metric_data.get("cv2", 0),
                "type": metric_data.get("demand_type", "Unknown")
            }
            return generate_seasonality_figure(records, metric, stats)
        except: return go.Figure()

    # 3. Render Experiment Details (Using Service)
    @app.callback(
        Output("experiment-graph", "figure"),
        Input("predictions-store", "data"), # Trigger on data load
        Input("experiment-perf-metric", "value"), # Trigger on metric change
        prevent_initial_call=True,
    )
    def render_experiment_artifact(preds, perf_metric):
        if not preds or not perf_metric:
            return go.Figure()

        try:
            sheet = next(iter(preds.keys()))
            metric = next(iter(preds[sheet]["metrics"].keys()))
            return generate_experiment_figure(sheet, metric, perf_metric)
        except: return go.Figure()

    # 4. Render Distribution (Using Service)
    @app.callback(
        Output("distribution-graph", "figure"),
        Input("predictions-store", "data"),
        Input("artifact-y-plot-type", "value"), # <--- NEW INPUT
        prevent_initial_call=True,
    )
    def render_distribution_artifact(preds, plot_type):
        if not preds: return go.Figure()
        
        # Default to histogram if plot_type is None (on initial load)
        current_plot_type = plot_type if plot_type else "histogram"

        try:
            sheet = next(iter(preds.keys()))
            metric = next(iter(preds[sheet]["metrics"].keys()))
            records = preds[sheet]["metrics"][metric].get("records", [])
            
            # Pass the plot_type to the generator
            return generate_distribution_figure(records, metric=metric, plot_type=current_plot_type)
        except: return go.Figure()

    # 5. Render Stationarity
    @app.callback(
        Output("stationarity-graph", "figure"),
        Input("predictions-store", "data"), # Changed to Input
        prevent_initial_call=True,
    )
    def render_stationarity_artifact(preds):
        if not preds: return go.Figure()
        try:
            sheet = next(iter(preds.keys()))
            metric = next(iter(preds[sheet]["metrics"].keys()))
            records = preds[sheet]["metrics"][metric].get("records", [])
            return generate_stationarity_figure(records, metric)
        except: return go.Figure()

    # 6. Render ACF / PACF
    @app.callback(
        Output("acf-pacf-graph", "figure"),
        Input("predictions-store", "data"), # Changed to Input
        prevent_initial_call=True,
    )
    def render_acf_pacf_artifact(preds):
        if not preds: return go.Figure()
        try:
            sheet = next(iter(preds.keys()))
            metric = next(iter(preds[sheet]["metrics"].keys()))
            records = preds[sheet]["metrics"][metric].get("records", [])
            return generate_acf_pacf_figure(records, metric)
        except: return go.Figure()
    
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
    #  3. RUN HEALTH CHECK & GENERATE ALL KYD CHARTS
    # ------------------------------------------------------------------
    @app.callback(
        # X Outputs
        Output("health-check-content", "children"),
        Output("kyd-features-graph", "figure"),
        Output("kyd-x-distribution-graph", "figure"),
        
        # Y Outputs
        Output("kyd-stationarity-graph", "figure"),
        Output("kyd-decomposition-graph", "figure"),
        Output("kyd-acf-pacf-graph", "figure"),
        Output("kyd-y-distribution-graph", "figure"),
        
        Input("btn-check-health", "n_clicks"),
        Input("kyd-x-plot-type", "value"),
        Input("kyd-y-plot-type", "value"),
        
        # Data Sources
        State("store-target-dfs", "data"),
        State("select-sheet-target", "value"),
        State("select-col-target", "value"),
        State("store-feature-dfs", "data"),
        
        prevent_initial_call=True
    )
    def run_health_check(n_clicks, plot_type_x, plot_type_y, target_store, target_sheet, target_col, feature_store):
        ctx = callback_context
        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0] if ctx.triggered else None
        
        empty = go.Figure()
        no_data_alert = dmc.Alert("Data missing. Please upload files.", color="red")
        
        # Default Returns (no_update prevents flickering of untouched graphs)
        ret_health = no_update
        ret_feat = no_update
        ret_dist_x = no_update
        ret_stat = no_update
        ret_decomp = no_update
        ret_acf = no_update
        ret_dist_y = no_update

        # Flags for efficiency
        update_x = (trigger_id == "btn-check-health")
        update_y = (trigger_id == "btn-check-health")
        
        only_update_x_dist = (trigger_id == "kyd-x-plot-type")
        only_update_y_dist = (trigger_id == "kyd-y-plot-type")

        # ---------------------------
        # PROCESS X (FEATURES)
        # ---------------------------
        if (update_x or only_update_x_dist) and feature_store:
            try:
                sheet_x = list(feature_store.keys())[0]
                df_x = pd.read_json(feature_store[sheet_x], orient='split')
                date_col_x = next((c for c in df_x.columns if "date" in str(c).lower()), None)
                x_cols = [c for c in df_x.columns if pd.api.types.is_numeric_dtype(df_x[c]) and c != date_col_x]
                
                if x_cols:
                    records_x = df_x.to_dict(orient="records")
                    
                    # Always generate distribution if triggered
                    fig_dist_x = generate_distribution_figure(records_x, x_cols=x_cols, plot_type=plot_type_x)
                    ret_dist_x = fig_dist_x
                    
                    # Generate heavy charts ONLY on button click
                    if update_x:
                        fig_health = generate_health_summary_table(records_x, x_cols)
                        ret_health = dcc.Graph(figure=fig_health, config={'displayModeBar': False})
                        ret_feat = generate_feature_heatmap(records_x, x_cols)

            except Exception as e:
                if update_x: ret_health = dmc.Alert(f"Error processing Features: {str(e)}", color="red")

        # ---------------------------
        # PROCESS Y (TARGET)
        # ---------------------------
        if (update_y or only_update_y_dist) and target_store and target_sheet and target_col:
            try:
                df_y = pd.read_json(target_store[target_sheet], orient='split')
                date_col_y = next((c for c in df_y.columns if "date" in str(c).lower()), None)
                
                if date_col_y:
                    df_y[date_col_y] = pd.to_datetime(df_y[date_col_y])
                    df_y = df_y.sort_values(date_col_y)
                    valid_y = df_y.dropna(subset=[target_col])
                    
                    records_y = []
                    for _, r in valid_y.iterrows():
                        records_y.append({"Date": r[date_col_y], "TrainActual": r[target_col]})
                    
                    if records_y:
                        # Always generate Y distribution if triggered (Passing plot_type_y)
                        records_y_dist = valid_y.to_dict(orient="records")
                        ret_dist_y = generate_distribution_figure(records_y_dist, metric=target_col, plot_type=plot_type_y)
                        
                        # Generate heavy charts ONLY on button click
                        if update_y:
                            ret_stat = generate_stationarity_figure(records_y, target_col)
                            
                            series = pd.Series([r["TrainActual"] for r in records_y])
                            adi = calculate_adi(series); cv2 = calculate_cv2(series)
                            d_type = classify_demand(adi, cv2)
                            ret_decomp = generate_seasonality_figure(records_y, target_col, {"adi": adi, "cv2": cv2, "type": d_type})
                            
                            ret_acf = generate_acf_pacf_figure(records_y, target_col)
                        
            except Exception as e:
                 print(f"Error processing Target: {e}")

        return (ret_health, ret_feat, ret_dist_x, ret_stat, ret_decomp, ret_acf, ret_dist_y)
    
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
    # 2.6 Render Feature Analysis Graph
    @app.callback(
        Output("features-graph", "figure"),
        Input("predictions-store", "data"),
        prevent_initial_call=True,
    )
    def render_features_analysis(preds):
        if not preds: return go.Figure()
        try:
            sheet = next(iter(preds.keys()))
            metric = next(iter(preds[sheet]["metrics"].keys()))
            metric_data = preds[sheet]["metrics"][metric]
            records = metric_data.get("records", [])
            
            df = pd.DataFrame(records)
            standard_cols = ["Date", "TrainActual", "TrainRaw", "TestActual", "TestPrediction", "Forecast"]
            feature_cols = [c for c in df.columns if c not in standard_cols]

            if feature_cols:
                return generate_multivariate_feature_analysis(records, metric, feature_cols)
            else:
                return generate_feature_heatmap(records, metric)
        except: return go.Figure()