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

# Temp compatibility files
TMP_B64_PATH = "/tmp/dmc_uploaded_raw.b64"
TMP_SELECTIONS = "/tmp/dmc_last_selection.json"

# Module-level state
IN_MEMORY_LOGS: List[str] = []
CURRENT_PROGRESS: Dict[str, int] = {"total": 0, "done": 0}

WORKER_THREAD: Optional[threading.Thread] = None
WORKER_THREAD_LOCK = threading.Lock()

logger = logging.getLogger("dmc.processing")
logger.setLevel(logging.INFO)

# Helper functions
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
        is_error = any(kw in line.lower() for kw in ["error:", "exception", "failed", "critical"])
        is_success = "success:" in line.lower()
        is_intervention = any(kw in line for kw in ["🛑", "🔄", "STOPPED", "RESTARTED"]) # NEW: Manual intervention

        color = "#e6eef8" 
        if is_error: color = "#ff4d4f"
        elif is_success: color = "#2ecc71"
        elif is_intervention: color = "#f39c12" 

        rendered.append(
            dmc.Text(
                line, size="sm",
                style={"color": color, "fontFamily": "monospace", "whiteSpace": "pre-wrap"}
            )
        )
    return rendered

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
    
    # Target (Y) Upload Callbacks    
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
        
        default_sheet = sheet_opts[0]["value"] if sheet_opts else None
        short_name = filename[:20] + "..." if len(filename) > 20 else filename
        
        return store_data, short_name, sheet_opts, default_sheet, False


    # Features (X) Upload Callbacks   
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
    

    # Populate target columns from selected sheet
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
            cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and "date" not in str(c).lower()]
            opts = [{"label": c, "value": c} for c in cols]
            return opts, (opts[0]["value"] if opts else None), False
        except:
            return [], None, True
    
    # Run Forecast Callback
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
        
        SHOW_EMPTY = {"height": "100%", "display": "flex", "borderRadius": "20px"}
        HIDE_EMPTY = {"display": "none"}
        SHOW_CONSOLE = {"display": "flex", "flexDirection": "column", "height": "100%"}
        HIDE_CONSOLE = {"display": "none"}

        # Actions
        if trigger == "clear-graph":
            clear_all_outputs()
            return SHOW_EMPTY, HIDE_CONSOLE, True, [], _render_console_lines([]), {}, {}, no_update

        if trigger == "btn-stop":
            try:
                with open(STOP_FLAG, "w") as fh: fh.write("stop")
                with open(PROGRESS_JSON, "w") as fh:
                    json.dump({"percent": 0, "message": "🛑 Execution Stopped", "status": "stopped"}, fh)
            except: pass
            
            _append_log("🛑 Execution STOPPED by user request.") 
            
            return HIDE_EMPTY, SHOW_CONSOLE, False, IN_MEMORY_LOGS, _render_console_lines(IN_MEMORY_LOGS), no_update, no_update, no_update

        if trigger == "log-interval":
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

        if trigger in ["run-models-btn", "btn-restart"]:
            if trigger == "btn-restart":
                try:
                    with open(STOP_FLAG, "w") as fh: fh.write("stop")
                    if os.path.exists(PROGRESS_JSON): os.remove(PROGRESS_JSON)
                except: pass
                
                IN_MEMORY_LOGS.clear()
                restart_msg = f"[{_now_ts()}] 🔄 Execution RESTARTED by user request."
                IN_MEMORY_LOGS.append(restart_msg)
            
            missing = []
            if not target_store or not target_sheet or not target_col: missing.append("Target Data")
            if not horizon: missing.append("Forecast Horizon")
            if not selected_regions or len(selected_regions) == 0: missing.append("Region Selection")

            if missing:
                err = f"[{_now_ts()}] ❌ Error: Missing {', '.join(missing)}."
                _append_log(err)
                return SHOW_EMPTY, HIDE_CONSOLE, True, log_store + [err], _render_console_lines(log_store + [err]), {}, {}, no_update

            try:
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
                
                clear_all_outputs()
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


   # Progress bar callback 
    @app.callback(
        Output("processing-progress", "value"),
        Output("progress-text", "children"),
        Input("log-interval", "n_intervals"),
        prevent_initial_call=False,
    )
    def update_progress(n):
        progress_data = read_progress()
        
        pct = progress_data.get("percent", 0)
        msg = progress_data.get("message", "")

        if pct >= 100:
            return 100, msg 
        
        txt = f"{msg} ({pct}% completed)" if pct > 0 else msg
        return pct, txt
    
    @app.callback(
        Output("log-interval", "n_intervals"), 
        Input("log-interval", "n_intervals"),
        prevent_initial_call=False,
    )
    def reset_progress_on_load(n):
        if n == 0:
            try:
                if os.path.exists(PROGRESS_JSON):
                    os.remove(PROGRESS_JSON)
                if os.path.exists(DONE_FLAG):
                    os.remove(DONE_FLAG)
            except:
                pass
        return no_update
    

    # Graphs output callback
    @app.callback(
        Output("run-models-btn", "disabled"),
        Output("tab-graphs", "disabled"),
        Output("tab-artifacts", "disabled"),
        Output("kyd-tab", "disabled"),  
        Input("predictions-store", "data"),
        Input("log-interval", "disabled"), 
        prevent_initial_call=False,
    )
    def toggle_ui_states(preds, interval_disabled):
        is_running = not interval_disabled 
        has_preds = bool(preds and isinstance(preds, dict) and len(preds) > 0)
        
        run_btn_disabled = is_running
        
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
    

    # Render graph callback
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
            sheet = next(iter(preds.keys()))
            sheet_obj = preds[sheet]
            metric = next(iter(sheet_obj["metrics"].keys()))
            metric_obj = sheet_obj["metrics"][metric]
        except (StopIteration, KeyError, TypeError, AttributeError):
            return None, dmc.Text("Waiting for data...")
        
        model_name = metric_obj.get("best_model") or metric_obj.get("model") or "Unknown"
        acc_val = metric_obj.get("accuracy", 0.0)
        mae_val = metric_obj.get("mae") or 0.0

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

        metrics_strip = [
            dmc.Badge(f"BEST MODEL: {model_name.upper()}", color="gray", variant="outline", size="lg", radius="xl"),                
            dmc.Badge(f"ACCURACY: {int(round(float(acc_val)))}%", color="blue", variant="light", size="lg", radius="xl"),
            dmc.Badge(f"BIAS: {bias_val:+.1f}%", color="indigo", variant="light", size="lg", radius="xl"), 
            dmc.Badge(f"AVG. ERROR: {int(round(float(mae_val)))}", color="blue", variant="light", size="lg", radius="xl"),
        ]
        
        fig = go.Figure()

        # Historical Actuals
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

        # Test Set Actuals & Predictions
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

        # Forecast with adjustments 
        if "Forecast" in df.columns:
            # Forecast
            fig.add_trace(go.Scatter(
                x=df["Date"], y=df["Forecast"], mode="lines+markers",
                name="Forecast (Baseline)", 
                line=dict(color="#2ca02c", width=2), 
                opacity=0.4 if adjusted_data else 1.0 
            ))
            
            # Adjusted Forecast
            if adjusted_data:                
                df_adj = pd.DataFrame(adjusted_data)
                df_adj["Date"] = pd.to_datetime(df_adj["Date"])
                
                adj_cols = sorted([c for c in df_adj.columns if "Adjustment" in c], 
                                 key=lambda x: int(x.split(" ")[1]) if len(x.split(" ")) > 1 and x.split(" ")[1].isdigit() else 0)
                
                if adj_cols:
                    latest_adj_col = adj_cols[-1]
                    forecast_mask = df["Forecast"].notna()
                    df_plot = df_adj[forecast_mask]
                    
                    fig.add_trace(go.Scatter(
                        x=df_plot["Date"], y=df_plot[latest_adj_col], mode="lines+markers",
                        name=f"Adjusted ({latest_adj_col})", 
                        line=dict(color="#6a11cb", width=3), 
                        marker=dict(size=8, symbol="diamond")
                    ))

        fig.update_layout(
            template="plotly_white", 
            margin=dict(t=20, b=30, l=50, r=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )

        return metrics_strip, dcc.Graph(figure=fig, style={"height": "70vh"})
    

    # CSV Export callback
    @app.callback(
        Output("download-csv", "data"),
        Input("export-csv", "n_clicks"),
        [State("predictions-store", "data"),
         State("adjusted-forecast-store", "data")], 
        prevent_initial_call=True,
    )
    def export_forecast_to_csv(n_clicks, preds, adjusted_data):
        if not n_clicks:
            raise PreventUpdate

        try:
            if adjusted_data:
                df_export = pd.DataFrame(adjusted_data)
                
                sheet = next(iter(preds.keys()))
                metric = next(iter(preds[sheet]["metrics"].keys()))
            elif preds:
                sheet = next(iter(preds.keys()))
                metric = next(iter(preds[sheet]["metrics"].keys()))
                records = preds[sheet]["metrics"][metric].get("records", [])
                if not records: 
                    raise PreventUpdate
                df_export = pd.DataFrame(records)
            else:
                raise PreventUpdate

            if "Date" in df_export.columns:
                df_export["Date"] = pd.to_datetime(df_export["Date"]).dt.strftime('%Y-%m-%d')
            
            core_cols = ["Date", "TrainActual", "TrainRaw", "TestActual", "TestPrediction", "Forecast"]
            
            keep_cols = [c for c in core_cols if c in df_export.columns]
            adj_cols = [c for c in df_export.columns if "Adjustment" in c]
            
            df_export = df_export[keep_cols + adj_cols]
            
            
            filename = f"forecast_comparison_{metric}_{datetime.now().strftime('%Y%m%d')}.csv"
            return dcc.send_data_frame(df_export.to_csv, filename, index=False)
            
        except Exception as e:
            print(f"Export CSV Error: {str(e)}")
            raise PreventUpdate

    # Explanation callback
    @callback(
        [Output("forecast-explanation-content", "children"),
        Output("explanation-loader", "visible")], # Target the loader's visibility
        Input("predictions-store", "data"),
        State("region-select", "value"), 
        prevent_initial_call=True
    )
    def handle_initial_forecast_audit(original_preds, selected_regions):
        if not original_preds: 
            return no_update, False

        try:
            # 0. Setup and Data Extraction
            sheet = next(iter(original_preds.keys()))
            metric = next(iter(original_preds[sheet]["metrics"].keys()))
            meta = original_preds[sheet]["metrics"][metric]
            
            df_full = pd.DataFrame(meta.get("records", []))
            df_full['Date'] = pd.to_datetime(df_full['Date'])
            
            # Split into Historical (Actuals) and Forecast
            df_hist = df_full[df_full['TrainActual'].notna() | df_full['TestActual'].notna()].copy()
            df_fore = df_full[df_full['Forecast'].notna()].copy()
            
            # 1. Data Description (Before Forecast - Historical)
            target_values_hist = df_hist['TrainActual'].fillna(df_hist['TestActual'])
            hist_stats = target_values_hist.describe().to_dict()

            # 2. Holiday Information (Integrated Logic)
            regions = selected_regions if selected_regions else []
            # Use existing utility to get holiday dates
            holiday_lookup = get_region_holidays(df_hist['Date'], regions)
            
            import holidays
            h_obj = holidays.HolidayBase()
            years = df_hist['Date'].dt.year.unique()
            if 'US' in regions: h_obj.update(holidays.US(years=years))
            if 'IN' in regions: h_obj.update(holidays.India(years=years))
            
            df_hist["Holiday_Name"] = df_hist['Date'].apply(lambda x: h_obj.get(x))
            df_hist["Is_Holiday"] = df_hist["Holiday_Name"].notna().astype(int)
            
            # Comparison logic
            non_holiday_mask = df_hist["Is_Holiday"] == 0
            holiday_mask = df_hist["Is_Holiday"] == 1
            
            non_holiday_avg = target_values_hist[non_holiday_mask].mean()
            
            # Detail for each specific holiday
            holiday_performance = {
                "baseline_non_holiday_avg": round(float(non_holiday_avg), 2),
                "holiday_details": df_hist[holiday_mask].groupby("Holiday_Name").apply(
                    lambda x: {
                        "avg_y": round(float(target_values_hist.loc[x.index].mean()), 2),
                        "impact_percent": round(float(((target_values_hist.loc[x.index].mean() - non_holiday_avg) / (non_holiday_avg + 1e-6)) * 100), 2)
                    }
                ).to_dict()
            }

            # 3. Feature Scores (Post-Feature Selection)
            feature_impact = meta.get('feature_importance', {})

            # 4. Forecast description
            forecast_stats = df_fore['Forecast'].describe().to_dict()

            # 5. Weekend/Weekday Description
            df_fore['is_weekend'] = df_fore['Date'].dt.dayofweek >= 5
            wknd_avg = df_fore[df_fore['is_weekend']]['Forecast'].mean()
            wkdy_avg = df_fore[~df_fore['is_weekend']]['Forecast'].mean()


            # 6. Forecast Bias
            bias_val = meta.get("forecast_bias", 0)

            # 7. Time Window Breakdown
            horizon_days = (df_fore['Date'].max() - df_fore['Date'].min()).days
            time_label = "monthly_avg" if horizon_days > 60 else "weekly_avg"
            time_breakdown = df_fore.resample('M' if horizon_days > 60 else 'W', on='Date')['Forecast'].mean().to_dict()

            # 8. Model stats
            wmape_val = meta.get("wmape", 0)
            model_stats = {
                "name": meta.get("best_model"),
                "accuracy_wmape": wmape_val,
                "bias_direction": "Conservative/Under-forecasting" if wmape_val > 0 else "Optimistic/Over-forecasting",
                "avg_error_mae": meta.get("mae")
            }

            # 9. Seasonality Stats
            seasonality_info = meta.get("seasonality_summary", "Detected periodicity in historical data")

            # 10. User Role & Domain (Dynamic Placeholder)
            user_context = {"role": "Supply Chain Analyst", "domain": "Retail/E-commerce"}

            # CONSTRUCT FULL PAYLOAD
            full_audit_payload = {
                "user_role": "Demand Planner", 
                "industry": "Retail",
                "historical_data_stats": hist_stats,
                "holiday_impact": holiday_performance,
                "feature_drivers": feature_impact,
                "forecast_stats": forecast_stats,
                "day_type_split": {"weekend_avg": wknd_avg, "weekday_avg": wkdy_avg},
                "model_bias": "Under-forecasting" if bias_val > 0.05 else "Over-forecasting" if bias_val < -0.05 else "Neutral",
                "time_trajectory": {str(k.date()): v for k, v in time_breakdown.items()},
                "model_details": {
                    "name": meta.get("best_model"),
                    "accuracy": meta.get("accuracy"),
                    # Use the variable wmape_val here as well for consistency
                    "error_metrics": {"wmape": wmape_val, "mae": meta.get("mae")}
                },
                "seasonality_stats": seasonality_info,
                "user_context": user_context
            }

            # Save JSON locally for your prompt engineering tests
            with open("forecast_audit_payload.json", "w") as f:
                json.dump(full_audit_payload, f, indent=4)

            # Call Audit Service
            explanation = LLMService.generate_forecast_audit(full_audit_payload)
            return dmc.TypographyStylesProvider(children=dcc.Markdown(explanation)), False

        except Exception as e:
            logging.error(f"Audit Generation Failed: {traceback.format_exc()}")
            return dmc.Text(f"Audit Generation Failed: {str(e)}", c="red", size="xs")

    # Experiment Details Callback
    @app.callback(
        [Output("experiment-graph", "figure"),
         Output("experiment-split-info", "children")],
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
            
            records = metric_data.get("records", [])
            df = pd.DataFrame(records)
            if "Date" in df.columns:
                df["Date"] = pd.to_datetime(df["Date"])
                
                train_df = df[df["TrainActual"].notna()]
                test_df = df[df["TestActual"].notna()]
                
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

            fig = generate_experiment_figure(sheet, metric, perf_metric)
            return fig, split_badges
            
        except Exception as e: 
            return go.Figure(), [dmc.Text(f"Error loading split info: {str(e)}", size="xs", c="red")]
    

    # KYD Callback
    @app.callback(
        Output("kyd-sheet-select", "data"),
        Output("kyd-sheet-select", "value"), 
        Input("store-target-dfs", "data"),
    )
    def update_kyd_sheet_dropdown(uploaded_dfs):
        if not uploaded_dfs:
            return [], None
        sheets = list(uploaded_dfs.keys())
        return [{"label": s, "value": s} for s in sheets], sheets[0]

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
            df = pd.read_json(uploaded_dfs[sheet], orient="split")
            numeric_cols = [
                c for c in df.columns 
                if pd.api.types.is_numeric_dtype(df[c]) and "date" not in str(c).lower()
            ]
            
            options = [{"label": c, "value": c} for c in numeric_cols]            
            return options, options
        except Exception:
            return [], []

    
    # Combined KYD callback    
    @app.callback(
        Output("kyd-empty-state", "style"),
        Output("kyd-main-content", "style"),
        Output("tab-x-health", "style"),      
        Output("tab-x-collinear", "style"),   
        Output("tab-x-dist", "style"),        
        Output("health-check-content-raw", "children"),
        Output("kyd-features-graph", "children"), 
        Output("kyd-x-distribution-graph-raw", "children"), 
        Output("kyd-x-dist-results-raw", "children"), 
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
            return (no_update,) * 20 

        style_empty, style_content, style_always_visible = {"display": "none"}, {"display": "block"}, {"display": "block"}
        from layout.main_layout import create_x_placeholder
        x_placeholder = create_x_placeholder("Upload X feature file for analysis")
        
        ret_health_raw = x_placeholder
        ret_dist_x_raw = x_placeholder
        ret_dist_res_x_raw = html.Div() 
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
                # Data Statistics
                ret_health_raw = dcc.Graph(figure=generate_health_summary_table(recs_x_raw, x_cols), config={'displayModeBar': False})
                
                # Distribution Plots
                ret_dist_x_raw = dcc.Graph(
                    figure=generate_distribution_figure(recs_x_raw, x_cols=x_cols, plot_type=plot_type_x),
                    responsive=True, style={"height": "100%", "width": "100%"}
                )

                if has_x:
                    try:
                        fig_x = generate_distribution_figure(recs_x_raw, x_cols=x_cols, plot_type=plot_type_x)
                        for i, col in enumerate(x_cols):
                            series_x = df_x[col].dropna()
                            if series_x.empty: continue

                            if plot_type_x == "histogram":
                                stats_text = f"Mean: {series_x.mean():.1f} | Med: {series_x.median():.1f} | Skew: {series_x.skew():.1f}"
                            else: # Boxplot
                                q1, q3 = series_x.quantile([0.25, 0.75])
                                iqr = q3 - q1
                                outlier_mask = (series_x < (q1 - 1.5 * iqr)) | (series_x > (q3 + 1.5 * iqr))
                                out_pct = (len(series_x[outlier_mask]) / len(series_x)) * 100
                                stats_text = f"Q1: {q1:.1f} | Q3: {q3:.1f} | Outliers: {out_pct:.1f}%"

                            fig_x.update_xaxes(title_text=stats_text, row=(i // 2) + 1, col=(i % 2) + 1)

                        for anno in fig_x['layout']['annotations']:
                            anno['font'] = {'size': 12, 'color': 'black'}
                        
                        fig_x.update_layout(
                            margin=dict(t=50, b=80), 
                            showlegend=False
                        )

                        ret_dist_x_raw = dcc.Graph(
                            figure=fig_x,
                            responsive=True, 
                            style={"height": "100%", "width": "100%"}
                        )

                    except Exception as e: 
                        print(f"X-Processing Error: {e}")
                        ret_dist_x_raw = dmc.Alert(f"Failed to generate X plots: {str(e)}", color="red")
                
                # Collinearity Analysis
                recs_corr = recs_x_raw 
                if has_preds:
                    sheet_p = next(iter(preds.keys()))
                    metric_p = next(iter(preds[sheet_p]["metrics"].keys()))
                    recs_corr = preds[sheet_p]["metrics"][metric_p].get("records", [])
                elif has_y and target_col:
                    try:
                        df_y_tmp = pd.read_json(io.StringIO(target_store[target_sheet]), orient='split')
                        date_x = next((c for c in df_x.columns if "date" in str(c).lower().strip()), None)
                        date_y = next((c for c in df_y_tmp.columns if "date" in str(c).lower().strip()), None)

                        if not date_y and "DATE" in df_y_tmp.columns: date_y = "DATE"
                        if not date_x and "DATE" in df_x.columns: date_x = "DATE"
                        
                        if date_x and date_y:
                            df_x_dt = df_x.copy()
                            df_y_dt = df_y_tmp[[date_y, target_col]].copy()
                            df_x_dt[date_x] = pd.to_datetime(df_x_dt[date_x], errors='coerce').dt.normalize()
                            df_y_dt[date_y] = pd.to_datetime(df_y_dt[date_y], errors='coerce').dt.normalize()
                            df_y_dt[target_col] = pd.to_numeric(df_y_dt[target_col], errors='coerce')
                            merged_df = pd.merge(df_x_dt, df_y_dt, left_on=date_x, right_on=date_y, how='inner')
                            if not merged_df.empty:
                                recs_corr = merged_df.ffill().bfill().to_dict(orient="records")
                            else:
                                recs_corr = recs_x_raw
                    except Exception as merge_err: 
                        print(f"Collinearity Merge Warning: {merge_err}")

                ret_feat = dcc.Graph(
                    figure=generate_feature_heatmap(recs_corr, target_col=target_col, x_cols=x_cols, method=corr_method),
                    responsive=True, style={"height": "100%", "width": "100%"}
                )
            except Exception as e: print(f"X-Processing Error: {e}")

        # Y analysis
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
            ret_health_raw, ret_feat, 
            ret_dist_x_raw, 
            ret_dist_res_x_raw,
            ret_stat_raw, ret_stat_proc, 
            ret_decomp_raw, ret_decomp_proc, 
            ret_acf_raw, ret_acf_proc, 
            ret_dist_y_raw, ret_dist_y_proc,
            collinear_label, 
            ret_dist_res_raw, ret_dist_res_proc
        )
    
    
    # Holiday Analysis callback
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
        if not target_store or not target_sheet or not target_col:
            return dmc.Text("Upload a Target (Y) file and select a column to begin analysis.", c="dimmed", ta="center", py="xl")

        if not selected_regions or len(selected_regions) == 0:
            return dmc.Alert(
                "Please select a Region (e.g., India or United States) in the configuration toolbar to view holiday impact.",
                title="Region Selection Required",
                color="orange",
                variant="light",
                icon=DashIconify(icon="carbon:location-hazard")
            )

        try:            
            df_y = pd.read_json(io.StringIO(target_store[target_sheet]), orient='split')
            date_col_y = next((c for c in df_y.columns if "date" in str(c).lower()), None)
            
            if not date_col_y:
                return dmc.Alert("Date column not found in Target file.", color="red")
                
            df_y[date_col_y] = pd.to_datetime(df_y[date_col_y])
            df_y = df_y.set_index(date_col_y).sort_index()

            
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

            
            regions = selected_regions if selected_regions else []            
            holiday_lookup = get_region_holidays(df_hol[date_col_y], regions)            
            df_hol["Is_Holiday"] = df_hol[date_col_y].isin(holiday_lookup).astype(int)

            import holidays
            h_obj = holidays.HolidayBase()
            years = df_hol[date_col_y].dt.year.unique()
            if 'US' in regions: h_obj.update(holidays.US(years=years))
            if 'IN' in regions: h_obj.update(holidays.India(years=years))
            
            df_hol["Holiday_Name"] = df_hol[date_col_y].apply(lambda x: h_obj.get(x))
            
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
        

    #  Data Treatment Analysis callback
    @app.callback(
        Output("treatment-graph", "figure"),
        Output("y-treatment-json", "children"),
        Output("x-treatment-json", "children"),
        Output("y-treatment-title", "children"), 
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
    

    # Feature Analysis callback
    @app.callback(
        Output("features-graph", "figure"), 
        Input("predictions-store", "data"),
        Input("artifact-corr-method", "value"), 
        prevent_initial_call=True,
    )
    def render_features_analysis(preds, corr_method):
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
            non_feature_cols = [
                "Date", "TrainActual", "TrainRaw", "TestActual", 
                "TestPrediction", "Forecast", "Is_Holiday"
            ]
            feature_cols = [c for c in df.columns if c not in non_feature_cols]

            return generate_multivariate_feature_analysis(records, metric, feature_cols, method=corr_method)
                
        except Exception as e:
            print(f"Artifacts Feature Graph Error: {e}")
            return go.Figure().update_layout(title=f"Error: {str(e)}")
        
    # llm callback
    @app.callback(
        [Output("adjusted-forecast-store", "data"),
        Output("chat-history", "children"),
        Output("llm-constraint-input", "value")],
        [Input("apply-llm-btn", "n_clicks"),
        Input("reset-llm-btn", "n_clicks")],
        [State("llm-constraint-input", "value"),
        State("predictions-store", "data"),
        State("adjusted-forecast-store", "data"), 
        State("chat-history", "children")],
        prevent_initial_call=True
    )
    def handle_llm_adjustment(apply_n, reset_n, prompt, preds, adjusted_data, history):
        ctx = callback_context
        if not ctx.triggered:
            raise PreventUpdate
        
        trigger = ctx.triggered[0]["prop_id"].split(".")[0]

        if trigger == "reset-llm-btn":
            reset_alert = dmc.Alert("Forecast reset to original ML baseline.", color="gray", variant="light", radius="md", mb="sm")
            return None, [reset_alert], ""

        if not prompt or not preds:
            return no_update, history, no_update

        try:
            sheet = next(iter(preds.keys()))
            metric = next(iter(preds[sheet]["metrics"].keys()))
            baseline_records = preds[sheet]["metrics"][metric].get("records", [])
            df_base = pd.DataFrame(baseline_records)
            
            is_initial = history and len(history) == 1 and any(word in str(history[0]) for word in ["Ready", "business", "rules"])
            adj_count = 1 if is_initial else len(history) + 1
            
            if adjusted_data:
                df_adj_input = pd.DataFrame(adjusted_data)
                adj_cols = [c for c in df_adj_input.columns if "Adjustment" in str(c)]
                for col in adj_cols: df_base[col] = df_adj_input[col]
                source_col = sorted(adj_cols, key=lambda x: int(x.split(" ")[1]))[-1]
            else:
                source_col = "Forecast"

            df = df_base.copy()
            df["Date"] = pd.to_datetime(df["Date"])
            df['target'] = df[source_col] 
            df['actual_combined'] = df['TrainActual'].fillna(df['TestActual']).fillna(df['target'])

            forecast_dates = df[df['Forecast'].notna()]['Date']

            metadata = {
                **{col: str(dtype) for col, dtype in df.dtypes.items()},
                "Date_Range": [
                    forecast_dates.min().strftime('%Y-%m-%d'), 
                    forecast_dates.max().strftime('%Y-%m-%d')
                ]
            }

            generated_code = LLMService.generate_adjustment_code(prompt, metadata)
            
            if not generated_code:
                return no_update, history, ""

            if generated_code.startswith("REFUSAL:"):
                msg = generated_code.replace("REFUSAL:", "")
                refusal_ui = dmc.Alert(
                    msg, 
                    title="Assistant Note", 
                    color="gray", 
                    variant="outline", 
                    radius="md", mb="sm",
                    icon=DashIconify(icon="carbon:information-square-filled"),
                    withCloseButton=True
                )
                
                updated_history = [refusal_ui] if is_initial else history + [refusal_ui]
                return no_update, updated_history, ""

            df_adjusted = ConstraintExecutor.execute_safely(df, generated_code)
            
            df_adjusted["Forecast"] = df_base["Forecast"].values
            df_adjusted = df_adjusted.drop(columns=['target', 'actual_combined'], errors='ignore')
            df_adjusted["Date"] = df_adjusted["Date"].dt.strftime('%Y-%m-%dT%H:%M:%S')
            
            user_msg = dmc.Paper(
                p="sm", radius="md", mb="sm", withBorder=True,
                style={"backgroundColor": "#ffffff", "borderLeft": "4px solid #1a73e8", "boxShadow": "0 2px 4px rgba(0,0,0,0.05)"},
                children=[
                    dmc.Group(justify="space-between", children=[
                        dmc.Group(gap="xs", children=[
                            DashIconify(icon="carbon:checkmark-filled", color="#1a73e8", width=16),
                            dmc.Text(f"Adjustment {adj_count}", fw=700, size="xs", c="blue"),
                        ]),
                        dmc.ActionIcon(
                            DashIconify(icon="carbon:undo", width=14),
                            id={"type": "undo-btn", "index": adj_count},
                            variant="subtle", color="gray", size="sm"
                        )
                    ]),
                    dmc.Text(prompt, size="sm", mt=4, fw=500),
                    dmc.Code(generated_code, block=True, mt="xs", color="blue", style={"fontSize": "11px"}) 
                ]
            )

            updated_history = [user_msg] if is_initial else history + [user_msg]

            return df_adjusted.to_dict(orient="records"), updated_history, ""

        except Exception as e:
            error_ui = dmc.Alert(
                f"Execution Error: {str(e)}", 
                title="System Error", 
                color="red", variant="light", radius="md", mb="sm"
            )
            updated_history = [error_ui] if is_initial else history + [error_ui]
            return no_update, updated_history, no_update
    
    # Undo Adjustment callback
    @app.callback(
        [Output("adjusted-forecast-store", "data", allow_duplicate=True),
        Output("chat-history", "children", allow_duplicate=True)],
        Input({"type": "undo-btn", "index": ALL}, "n_clicks"),
        [State("predictions-store", "data"),
        State("chat-history", "children")],
        prevent_initial_call=True
    )
    def undo_last_adjustment(n_clicks, preds, history):
        if not any(n_clicks) or not history:
            raise PreventUpdate

        history.pop()

        if not history or (len(history) == 1 and "Ready to Assist" in str(history[0])):
            return None, history

        try:
            sheet = next(iter(preds.keys()))
            metric = next(iter(preds[sheet]["metrics"].keys()))
            records = preds[sheet]["metrics"][metric].get("records", [])
            df = pd.DataFrame(records)
            df["Date"] = pd.to_datetime(df["Date"])

            for i, bubble in enumerate(history):
                try:
                    code_to_reapply = bubble['props']['children'][2]['props']['children']
                    
                    adj_num = i + 1
                    source_col = f"Adjustment {adj_num - 1}" if adj_num > 1 else "Forecast"
                    
                    df["target"] = df[source_col]
                    df = ConstraintExecutor.execute_safely(df, code_to_reapply)
                    df["Forecast"] = pd.DataFrame(records)["Forecast"].values
                    
                except Exception:
                    continue 
            
            df["Date"] = df["Date"].dt.strftime('%Y-%m-%dT%H:%M:%S')
            return df.to_dict(orient="records"), history
            
        except Exception as e:
            print(f"Undo Failed: {e}")
            return None, history