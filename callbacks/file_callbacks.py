from dash import Input, Output, State, callback_context, no_update, html
import dash_mantine_components as dmc
from dash_iconify import DashIconify
import pandas as pd

UPLOAD_TMP_META = "/tmp/dmc_last_selection.json"

def register_callbacks(app):
    group = "article"

    def _handle_ui(contents, filename):
        triggered = callback_context.triggered[0]["prop_id"] if callback_context.triggered else None

        if filename:
            short = filename if len(filename) < 24 else filename[:20] + "..."
            ok = filename.lower().endswith((".xls", ".xlsx", ".csv"))
            icon = "carbon:checkmark-filled" if ok else "carbon:warning-filled"
            color = "green" if ok else "red"

            return [
                dmc.Group(gap="xs", children=[
                    DashIconify(icon=icon, width=12, color=color),
                    dmc.Text(short, size="xs", c=color, fw=600)
                ])
            ]

        return []

    app.callback(
        Output(f"{group}-message", "children"),
        Input(f"{group}-upload", "contents"),
        State(f"{group}-upload", "filename"),
        prevent_initial_call=False,
    )(_handle_ui)

    @app.callback(
        Output("sheet-select", "value"),
        Input("sheet-select", "options"),
        State("sheet-select", "value"),
        prevent_initial_call=False,
    )
    def _auto_select_sheet(options, current):
        if current:
            return current

        if options and len(options) > 0:
            return options[0]["value"]

        return None

    @app.callback(
        Output("article-sheet-select", "placeholder"),
        Input("article-sheet-select", "value"),
    )
    def toggle_sheet_placeholder(value):
        if value and len(value) > 0:
            return ""
        return "Select one or more processes"
    
    @app.callback(
        Output("metric-select", "placeholder"),
        Input("metric-select", "value"),
    )
    def toggle_metric_placeholder(value):
        if value and len(value) > 0:
            return ""
        return "Select metric columns for modeling"

    @app.callback(
        Output("x-variable-select", "data"),
        Output("x-variable-select", "disabled"),
        Input("article-sheet-select", "value"),
        Input("metric-select", "value"),
        State("uploaded-dfs", "data"), 
        prevent_initial_call=False
    )
    def populate_x_vars(sheets, target_metrics, uploaded_dfs):
        if not sheets or not uploaded_dfs:
            return [], True
        
        sheet = sheets[0] if isinstance(sheets, list) else sheets
        if sheet not in uploaded_dfs:
            return [], True
            
        try:
            df = pd.read_json(uploaded_dfs[sheet], orient="split")
            
            exclude_cols = []
            if target_metrics:
                targets = target_metrics if isinstance(target_metrics, list) else [target_metrics]
                for t in targets:
                    col = t.split("||")[-1] if "||" in t else t
                    exclude_cols.append(col)
            
            options = []
            for col in df.columns:
                if col in exclude_cols: 
                    continue
                if "date" in str(col).lower(): 
                    continue
                if pd.api.types.is_numeric_dtype(df[col]):
                    options.append({"label": col, "value": col})
            
            return options, False
        except Exception:
            return [], True