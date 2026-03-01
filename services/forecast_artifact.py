import pandas as pd
import plotly.graph_objects as go
import plotly.subplots as sp
import plotly.figure_factory as ff
from statsmodels.tsa.seasonal import seasonal_decompose
import os
from services.processing_engine import HISTORY_LOG
from sklearn.ensemble import RandomForestRegressor
from statsmodels.tsa.stattools import adfuller, acf, pacf
import numpy as np
from scipy.stats import skew

# X Data Statistics  
def generate_health_summary_table(records: list, target_col: str, external_col: str = None) -> go.Figure:
    """
    Enhanced UI version of the Health Summary Table.
    Preserves all statistical logic, column widths, and responsive scaling.
    """
    if not records:
        return go.Figure(layout=go.Layout(title="No data available"))

    try:
        df = pd.DataFrame(records)
        
        full_idx = None
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"], errors='coerce')
            df = df.sort_values("Date").set_index("Date")
            
            if not df.index.empty:
                start_date = df.index.min()
                end_date = df.index.max()
                full_idx = pd.date_range(start=start_date, end=end_date, freq="D")

        if isinstance(target_col, list):
            features = [c for c in target_col if c in df.columns]
            
            if not features:
                return go.Figure(layout=go.Layout(title="No valid features found"))
            
            headers = [
                "<b>Feature</b>", 
                "<b>Total Miss</b>", "<b>WkDay Miss</b>", "<b>WkEnd Miss</b>", "<b>Zeros</b>",
                "<b>Min</b>", "<b>Max</b>", 
                "<b>Mean</b>", "<b>Std Dev</b>", 
                "<b>25% / 50% / 75%</b>",
                "<b>Skew</b>"
            ]
            
            rows = []
            for f in features:
                series = df[f]
                if full_idx is not None:
                    series = series.reindex(full_idx)
                
                total = len(series)
                is_missing = series.isna()
                missing_total = is_missing.sum()
                
                if full_idx is not None:
                    is_weekend = series.index.weekday >= 5
                    miss_we = (is_missing & is_weekend).sum()
                    miss_wd = (is_missing & ~is_weekend).sum()
                else:
                    miss_we = "-"
                    miss_wd = "-"
                
                clean = series.dropna()
                if clean.empty:
                    rows.append([f, f"{missing_total} (100%)", "-", "-", "-", "-", "-", "-", "-", "-", "-"])
                    continue

                zeros = (clean == 0).sum()
                min_v, max_v = clean.min(), clean.max()
                mean_v, std_v = clean.mean(), clean.std()
                p25, p50, p75 = clean.quantile(0.25), clean.median(), clean.quantile(0.75)
                sk = clean.skew()
                
                perc_str = f"{p25:.2f} / <b>{p50:.2f}</b> / {p75:.2f}"
                
                rows.append([
                    f"<b>{f}</b>",
                    f"{missing_total} ({missing_total/total:.1%})",
                    f"{miss_wd}", f"{miss_we}",
                    f"{zeros} ({zeros/len(clean):.1%})",
                    f"{min_v:.2f}", f"{max_v:.2f}",
                    f"{mean_v:.2f}", f"{std_v:.2f}",
                    perc_str, f"{sk:.2f}"
                ])
            
            cell_values = list(zip(*rows))
            col_widths = [2.0, 1.2, 1.0, 1.0, 1.2, 0.8, 0.8, 0.8, 0.9, 1.8, 0.8]
            alignments = ['left'] + ['center'] * 10
            
            fig = go.Figure(data=[go.Table(
                columnwidth=col_widths,
                header=dict(
                    values=headers,
                    fill_color='#1a73e8', 
                    font=dict(color='white', size=11, family="Inter, sans-serif"),
                    align=alignments,
                    height=38,
                    line_color='rgba(255,255,255,0.1)'
                ),
                cells=dict(
                    values=cell_values,
                    fill_color=[['#f8f9fa' if i % 2 == 0 else '#ffffff' for i in range(len(rows))]] * len(headers),
                    align=alignments,
                    font=dict(color='#3c4043', size=11, family="Inter, sans-serif"),
                    height=32,
                    line_color="#e9ecef" 
                )
            )])
            
            fig.update_layout(
                margin=dict(t=5, b=5, l=5, r=5, autoexpand=True),
                height=max(350, 120 + len(features) * 35),
                autosize=True,
                paper_bgcolor='rgba(0,0,0,0)', 
                plot_bgcolor='rgba(0,0,0,0)',
                template="plotly_white"
            )
            return fig

        return go.Figure(layout=go.Layout(title="Comparison Mode Not Active"))

    except Exception as e:
        return go.Figure(layout=go.Layout(title=f"Error: {str(e)}"))
    

# Seasonal Decomposition 
def generate_seasonality_figure(records: list, metric_name: str, stats: dict = None) -> go.Figure:
    """
    Enhanced UI version of Seasonal Decomposition.
    Standardizes colors to Blue/Indigo and polishes the Demand Analysis table.
    """
    if not records:
        return go.Figure(layout=go.Layout(title="No data available"))

    try:
        df = pd.DataFrame(records)
        dates = pd.to_datetime(df["Date"])
        brand_blue = '#1a73e8'
        brand_indigo = '#6a11cb'
        font_family = "Inter, sans-serif"
 
        # Data Selection 
        if "TrainImputed" in df.columns:
            series = df["TrainImputed"]
        else:
            series = df["TrainActual"]
            
        series = pd.to_numeric(series, errors='coerce').dropna()
        series.index = dates.loc[series.index]

        # Decomposition 
        period = 7 if len(series) > 14 else 2
        decomposition = seasonal_decompose(series, model='additive', period=period, extrapolate_trend='freq')

        fig = sp.make_subplots(
            rows=5, cols=1,
            shared_xaxes=False, 
            vertical_spacing=0.05, 
            row_heights=[0.18, 0.18, 0.18, 0.18, 0.28], 
            specs=[
                [{"type": "xy"}],    
                [{"type": "xy"}],    
                [{"type": "xy"}],    
                [{"type": "xy"}],    
                [{"type": "table"}]
            ],
            subplot_titles=(
                "<b>Actual Observed Data</b>", 
                "<b>Trend Component (Long-term)</b>", 
                "<b>Seasonal Component (Cyclical)</b>", 
                "<b>Residual Component (Noise)</b>", 
                "<b>Demand Analysis Summary</b>"
            )
        )

        # Row 1: Observed 
        fig.add_trace(go.Scatter(x=series.index, y=decomposition.observed, name="Observed", line=dict(color='#3c4043', width=1.5)), row=1, col=1)
        # Row 2: Trend (
        fig.add_trace(go.Scatter(x=series.index, y=decomposition.trend, name="Trend", line=dict(color=brand_blue, width=2.5)), row=2, col=1)
        # Row 3: Seasonal 
        fig.add_trace(go.Scatter(x=series.index, y=decomposition.seasonal, name="Seasonal", line=dict(color=brand_indigo, width=2)), row=3, col=1)
        # Row 4: Residual 
        fig.add_trace(go.Scatter(x=series.index, y=decomposition.resid, name="Residual", mode='lines', line=dict(color='#d62728', width=1)), row=4, col=1)
        fig.add_hline(y=0, line_dash="dash", line_color="#3c4043", row=4, col=1)

        # Row 5: Summary Table 
        if stats:
            adi = stats.get('adi', 0)
            cv2 = stats.get('cv2', 0)
            d_type = stats.get('type', 'Unknown')
            
            header_vals = ["<b>Statistic</b>", "<b>Value</b>"]
            cell_vals = [
                ["ADI (Intermittency)", "CV² (Volatility)", "Demand Type"],
                [f"<b>{adi:.2f}</b>", f"<b>{cv2:.2f}</b>", f"<b>{d_type}</b>"]
            ]
            
            type_bg = "#d1e7dd" if "Smooth" in str(d_type) else "#fff3cd" if "Erratic" in str(d_type) else "#f8d7da"
            
            fill_colors = [
                ['#f8f9fa', '#f8f9fa', '#f8f9fa'], 
                ['#ffffff', '#ffffff', type_bg]
            ]

            fig.add_trace(go.Table(
                header=dict(
                    values=header_vals, 
                    fill_color=brand_blue, 
                    font=dict(color='white', size=13, family=font_family), 
                    align='left', 
                    height=35
                ),
                cells=dict(
                    values=cell_vals, 
                    fill_color=fill_colors, 
                    align='left', 
                    font=dict(color='#3c4043', size=13, family=font_family), 
                    height=35,
                    line_color='#e9ecef'
                )
            ), row=5, col=1)
        else:
            fig.add_trace(go.Table(header=dict(values=["No Stats Available"])), row=5, col=1)

        fig.update_xaxes(matches='x', gridcolor='#f1f3f5', row=1, col=1)
        fig.update_xaxes(matches='x', gridcolor='#f1f3f5', row=2, col=1)
        fig.update_xaxes(matches='x', gridcolor='#f1f3f5', row=3, col=1)
        fig.update_xaxes(matches='x', gridcolor='#f1f3f5', row=4, col=1)
        
        fig.update_yaxes(gridcolor='#f1f3f5', automargin=True)

        fig.update_layout(
            height=1100, 
            margin=dict(b=20, t=80, l=40, r=40, autoexpand=True), 
            showlegend=False,
            template="plotly_white",
            paper_bgcolor='rgba(0,0,0,0)',
            font=dict(family=font_family)
        )
        return fig

    except Exception as e:
        return go.Figure(layout=go.Layout(title=f"Decomposition Error: {str(e)}"))


# Stationarity (ADF Test + Rolling)
def generate_stationarity_figure(records: list, metric_name: str) -> go.Figure:
    if not records:
        return go.Figure(layout=go.Layout(title="No data available"))

    try:
        df = pd.DataFrame(records)
        brand_blue = '#1a73e8'
        brand_indigo = '#6a11cb'
        font_family = "Inter, sans-serif"
        
        plot_df = df.copy()
        plot_df["Date"] = pd.to_datetime(plot_df["Date"])
        
        target_key = "TrainImputed" if "TrainImputed" in plot_df.columns else "TrainActual"
        
        plot_df[target_key] = pd.to_numeric(plot_df[target_key], errors='coerce')
        plot_df = plot_df.dropna(subset=[target_key])
        
        if len(plot_df) < 10:
             return go.Figure(layout=go.Layout(title="Not enough data for Stationarity Test (Need 10+ points)"))

        series = plot_df[target_key]
        series.index = plot_df["Date"]

        # Statistics CAlc.
        adf_result = adfuller(series, autolag='AIC')
        adf_stat, p_value, critical_values = adf_result[0], adf_result[1], adf_result[4]
        
        is_stationary = p_value < 0.05
        status_color = "#2ca02c" if is_stationary else "#d62728"
        status_text = "STATIONARY" if is_stationary else "NON-STATIONARY"

        window = max(7, int(len(series) * 0.1))
        rolling_mean = series.rolling(window=window).mean()
        rolling_std = series.rolling(window=window).std()

        fig = sp.make_subplots(
            rows=4, cols=1,
            row_heights=[0.45, 0.05, 0.40, 0.10],
            vertical_spacing=0.06,
            specs=[[{"type": "xy"}], [{"type": "xy"}], [{"type": "table"}], [{"type": "xy"}]],
            subplot_titles=(f"<b>Rolling Mean & Std (Window={window})</b>", "", "<b>ADF Test Statistics</b>", "<b>ADF Test Conclusion</b>")
        )

        # Graph component
        fig.add_trace(go.Scatter(x=series.index, y=series, name="Original", line=dict(color='#bdc3c7', width=1), opacity=0.5), row=1, col=1)
        fig.add_trace(go.Scatter(x=rolling_mean.index, y=rolling_mean, name="Rolling Mean", line=dict(color=brand_blue, width=2.5)), row=1, col=1)
        fig.add_trace(go.Scatter(x=rolling_std.index, y=rolling_std, name="Rolling Std", line=dict(color=brand_indigo, width=2, dash='dot')), row=1, col=1)

        # Hypothesis Text
        fig.add_trace(go.Scatter(
            x=[0.5], y=[0.5], text=[f"<span style='font-size: 14px; color: #3c4043; font-family: {font_family};'>ADF Hypothesis - H0: Unit root present (Non-Stationary) | H1: No unit root (Stationary)</span>"],
            mode="text", showlegend=False
        ), row=2, col=1)
        fig.update_xaxes(visible=False, row=2, col=1); fig.update_yaxes(visible=False, row=2, col=1)

        # Table
        fig.add_trace(go.Table(
            header=dict(values=["<b>Metric</b>", "<b>Value</b>"], fill_color=brand_blue, align='center', height=35, font=dict(color='white', size=13, family=font_family)),
            cells=dict(
                values=[["ADF Statistic", "P-Value", "Critical 1%", "Critical 5%", "Critical 10%"],
                        [f"<b>{adf_stat:.4f}</b>", f"<b>{p_value:.4f}</b>", f"{critical_values['1%']:.4f}", f"{critical_values['5%']:.4f}", f"{critical_values['10%']:.4f}"]],
                fill_color=[['#f8f9fa', '#ffffff']*3], align='center', height=35, font=dict(color='#3c4043', size=13, family=font_family), line_color='#e9ecef'
            )
        ), row=3, col=1)

        # Conclusion Text
        fig.add_trace(go.Scatter(
            x=[0.5], y=[0.5], text=[f"<span style='font-size:18px; color:{status_color}; font-family: {font_family}; font-weight: bold;'>{status_text} (p = {p_value:.4f})</span>"],
            mode="text", showlegend=False
        ), row=4, col=1)
        fig.update_xaxes(visible=False, row=4, col=1); fig.update_yaxes(visible=False, row=4, col=1)

        fig.update_layout(height=900, template="plotly_white", margin=dict(t=80, b=20, l=20, r=20), paper_bgcolor='rgba(0,0,0,0)', font=dict(family=font_family))
        return fig

    except Exception as e:
        return go.Figure(layout=go.Layout(title=f"Stationarity Error: {str(e)}"))
    

# Lag Analysis (ACF / PACF)
def generate_acf_pacf_figure(records: list, metric_name: str) -> go.Figure:
    """
    Standardizes Lag Analysis with Significant Lags displayed as a single 
    text line below the X-axis instead of on the ticks.
    """
    if not records:
        return go.Figure(layout=go.Layout(title="No data available"))

    try:
        df = pd.DataFrame(records)
        brand_blue, brand_indigo = '#1a73e8', '#6a11cb'
        font_family = "Inter, sans-serif"
        
        series_col = "TrainActual" if "TrainActual" in df.columns else df.columns[0]
        series = pd.to_numeric(df[series_col], errors='coerce').dropna().reset_index(drop=True)
        
        if len(series) < 5:
             return go.Figure(layout=go.Layout(title="Insufficient history"))

        n_lags = min(40, len(series) // 2 - 1)
        from statsmodels.tsa.stattools import acf, pacf
        acf_vals = acf(series, nlags=n_lags, fft=True)
        pacf_vals = pacf(series, nlags=n_lags)
        limit = 1.96 / np.sqrt(len(series))

        # Internal helper to extract significant lag strings
        def get_sig_text(vals):
            sigs = [str(i) for i, v in enumerate(vals) if abs(v) > limit and i > 0]
            if not sigs: return "None"
            return ", ".join(sigs)

        fig = sp.make_subplots(
            rows=2, cols=1,
            subplot_titles=("<b>Auto-Correlation (ACF)</b>", "<b>Partial Auto-Correlation (PACF)</b>"),
            vertical_spacing=0.25 # Increased spacing to accommodate text below axes
        )

        def add_lollipop(vals, row, name, color):
            x_range = list(range(len(vals)))
            for x, y in zip(x_range, vals):
                fig.add_trace(go.Scatter(
                    x=[x, x], y=[0, y], mode='lines', 
                    line=dict(color='#dee2e6', width=1), showlegend=False
                ), row=row, col=1)
            
            fig.add_trace(go.Scatter(
                x=x_range, y=vals, mode='markers',
                marker=dict(color=color, size=7, line=dict(width=1, color='white')),
                name=name
            ), row=row, col=1)

            # Standard X-axis ticks (No custom labeling)
            fig.update_xaxes(dtick=5, row=row, col=1)
            
            fig.add_shape(
                type="rect", x0=-0.5, x1=len(vals)-0.5, y0=-limit, y1=limit, 
                fillcolor=color, opacity=0.05, line_width=0, row=row, col=1
            )

        add_lollipop(acf_vals, 1, "ACF", brand_blue)
        add_lollipop(pacf_vals, 2, "PACF", brand_indigo)

        # ADD TEXT BELOW X-AXIS FOR ACF
        fig.add_annotation(
            text=f"<b>Significant lags :</b> {get_sig_text(acf_vals)}",
            xref="x1", yref="paper",
            x=n_lags/2, y=0.48, # Positioned just below top chart
            showarrow=False, font=dict(size=12, color="#3c4043")
        )

        # ADD TEXT BELOW X-AXIS FOR PACF
        fig.add_annotation(
            text=f"<b>Significant lags :</b> {get_sig_text(pacf_vals)}",
            xref="x2", yref="paper",
            x=n_lags/2, y=-0.15, # Positioned at the very bottom
            showarrow=False, font=dict(size=12, color="#3c4043")
        )

        fig.update_layout(
            height=550, 
            showlegend=False, 
            template="plotly_white",
            margin=dict(t=40, b=80, l=60, r=40),
            font=dict(family=font_family)
        )
        return fig

    except Exception as e:
        return go.Figure(layout=go.Layout(title=f"Lag Plot Error: {str(e)}"))
    

# Feature Analysis (Correlation Heatmap)
def generate_feature_heatmap(records: list, target_col: str = None, x_cols: list = None, method: str = "pearson") -> go.Figure:
    """
    Enhanced UI version of the Correlation Matrix (Heatmap).
    Explicitly includes the Target Feature for collinearity analysis.
    """
    if not records:
        return go.Figure(layout=go.Layout(title="No data available"))

    try:
        df = pd.DataFrame(records)
        
        # Priority 1: Use the specific target_col selected by the user
        if isinstance(target_col, list) and len(target_col) > 0:
            target_col = target_col[0]
        
        # Priority 2: Fallback to common naming conventions if target_col is missing
        if not target_col:
            target_col = next((c for c in ["TrainActual", "Target", "Actuals", "Daily_Sales"] if c in df.columns), None)

        valid_cols = []
        # Ensure Target Y is included if found in the dataframe
        if target_col and target_col in df.columns:
            valid_cols.append(target_col)
        
        if x_cols and isinstance(x_cols, list):
            for c in x_cols:
                # Add column only if it exists and is not the target
                if c in df.columns and c != target_col:
                    valid_cols.append(c)
        
        if len(valid_cols) < 2:
             return go.Figure(layout=go.Layout(
                title="Correlation requires Target (Y) and at least one Feature (X)",
                font=dict(family="Inter, sans-serif")
            ))
            
        df_subset = df[valid_cols].apply(pd.to_numeric, errors='coerce').dropna(axis=1, how='all')
        
        # Ensure we still have enough columns after dropping non-numeric ones
        if df_subset.shape[1] < 2:
            return go.Figure(layout=go.Layout(title="Not enough numeric data for correlation"))

        corr_matrix = df_subset.corr(method=method)

        fig = go.Figure(data=go.Heatmap(
            z=corr_matrix.values,
            x=corr_matrix.columns,
            y=corr_matrix.columns,
            colorscale='RdBu', 
            reversescale=True,
            zmin=-1, zmax=1,
            text=np.round(corr_matrix.values, 2),
            texttemplate="<b>%{text}</b>",
            showscale=False
        ))       

        fig.update_layout(
            height=600, # Optimized height for standard dashboard cards
            autosize=True,
            template="plotly_white",
            xaxis=dict(tickangle=-45, automargin=True, side="bottom"),
            yaxis=dict(autorange="reversed", automargin=True),
            margin=dict(l=50, r=50, t=50, b=50), # Tighter margins to prevent cutting
            font=dict(family="Inter, sans-serif", size=11)
        )
        return fig

    except Exception as e:
        return go.Figure(layout=go.Layout(title=f"Correlation Error: {str(e)}"))
    

# Data Distribution Analysis
def generate_distribution_figure(records: list, metric: str = None, x_cols: list = None, plot_type: str = "histogram") -> go.Figure:
    """
    Enhanced UI version of Distribution Plots optimized for dynamic side-by-side UI.
    Supports Grid (X) and Single (Y) modes.
    """
    if not records:
        return go.Figure(layout=go.Layout(title="No data available"))

    try:
        df = pd.DataFrame(records)
        brand_blue, brand_indigo = '#1a73e8', '#6a11cb'
        font_family = "Inter, sans-serif"
        
        # Case 1: Bulk X Features (Remains same for Multi-plot view)
        if x_cols:
            valid_cols = [c for c in x_cols if c in df.columns and pd.api.types.is_numeric_dtype(df[c])]
            if not valid_cols: return go.Figure(layout=go.Layout(title="No numeric features"))

            num_plots = len(valid_cols)
            rows = (num_plots // 3) + (1 if num_plots % 3 > 0 else 0)
            fig = sp.make_subplots(rows=rows, cols=3, subplot_titles=[f"<b>{c}</b>" for c in valid_cols], vertical_spacing=0.4)

            for i, col in enumerate(valid_cols):
                row, col_idx = (i // 3) + 1, (i % 3) + 1
                series = df[col].dropna()
                if series.empty: continue

                if plot_type == "boxplot":
                    fig.add_trace(go.Box(y=series, name=col, marker_color=brand_indigo, boxpoints='outliers'), row=row, col=col_idx)
                elif plot_type == "scatterplot":
                    fig.add_trace(go.Scatter(y=series, mode='markers', marker=dict(color=brand_blue, size=4)), row=row, col=col_idx)
                else: # Histogram
                    fig.add_trace(go.Histogram(x=series, marker_color=brand_blue, opacity=0.7), row=row, col=col_idx)

            fig.update_layout(height=350 * rows, template="plotly_white", font=dict(family=font_family))
            return fig

        # Case 2: Single Target Y (Optimized for side-by-side)
        series = df[metric] if metric in df.columns else df.get("TrainActual")
        if series is None or series.dropna().empty: return go.Figure()

        values = pd.to_numeric(series, errors='coerce').dropna()
        fig = go.Figure()

        if plot_type == "boxplot":
            fig.add_trace(go.Box(y=values, name=metric, marker_color=brand_indigo, boxmean='sd'))
        elif plot_type == "scatterplot":
            date_col = df["Date"] if "Date" in df.columns else df.index
            fig.add_trace(go.Scatter(y=values, x=date_col, mode='markers', marker=dict(color=brand_blue, size=7, opacity=0.6)))
        else: # Histogram
            fig.add_trace(go.Histogram(x=values, nbinsx=40, marker_color=brand_blue, opacity=0.75))
            fig.add_vline(x=values.mean(), line_width=3, line_dash="dash", line_color="#d62728")

        # Compact layout for Grid cards
        fig.update_layout(
            height=400, 
            showlegend=False,         
            autosize=True,
            margin=dict(t=20, b=20, l=40, r=20), 
            template="plotly_white", 
            paper_bgcolor='rgba(0,0,0,0)'
        )
        return fig
    except Exception as e: return go.Figure()
    

# Experiment Details (Model Comparison)
def generate_experiment_figure(sheet: str, metric: str, perf_metric: str = "WMAPE") -> go.Figure:
    """
    Enhanced UI version of the Model Comparison (Experiment) Figure.
    Standardizes colors to Corporate Blue/Green and applies Inter typography.
    """
    if not perf_metric:
        perf_metric = "WMAPE"

    if not os.path.exists(HISTORY_LOG):
        return go.Figure(layout=go.Layout(title="No experiment history found."))

    try:
        df = pd.read_csv(HISTORY_LOG)
        mask = (df["Sheet"] == sheet) & (df["Metric"] == metric)
        df_filtered = df[mask].copy()
        
        brand_blue = '#1a73e8'
        brand_green = '#2ca02c'
        baseline_orange = '#FF8C00'
        font_family = "Inter, sans-serif"

        if df_filtered.empty:
            return go.Figure(layout=go.Layout(title="No experiments recorded for this metric."))

        if "Timestamp" in df_filtered.columns:
            df_filtered["Timestamp"] = pd.to_datetime(df_filtered["Timestamp"], errors='coerce')
            df_filtered = df_filtered.sort_values("Timestamp")
        
        df_filtered = df_filtered.drop_duplicates(subset=["Model", "Stage"], keep="last")

        if perf_metric not in df_filtered.columns:
            return go.Figure(layout=go.Layout(title=f"Metric '{perf_metric}' not found in logs."))

        ascending = True if perf_metric == "Accuracy" else False
        uni_df = df_filtered[df_filtered["Stage"] == "Univariate"].sort_values(perf_metric, ascending=ascending)
        multi_df = df_filtered[df_filtered["Stage"] == "Multivariate"].sort_values(perf_metric, ascending=ascending)

        def get_colors(models, default_color):
            return [baseline_orange if "Baseline_SMA" in str(m) else default_color for m in models]

        fig = sp.make_subplots(
            rows=1, cols=2,
            subplot_titles=("<b>Univariate Models</b>", "<b>Multivariate Models</b>"),
            horizontal_spacing=0.15
        )

        def fmt_text(vals):
            return [f"<b>{v:.2f}</b>" for v in vals]

        if not uni_df.empty:
            fig.add_trace(go.Bar(
                y=uni_df["Model"], 
                x=uni_df[perf_metric], 
                orientation='h', 
                name="Univariate", 
                marker_color=get_colors(uni_df["Model"], brand_blue), 
                text=fmt_text(uni_df[perf_metric]), 
                textposition="auto",
                marker=dict(line=dict(width=0)) 
            ), row=1, col=1)

        if not multi_df.empty:
            fig.add_trace(go.Bar(
                y=multi_df["Model"], 
                x=multi_df[perf_metric], 
                orientation='h',
                name="Multivariate", 
                marker_color=get_colors(multi_df["Model"], brand_green), 
                text=fmt_text(multi_df[perf_metric]), 
                textposition="auto",
                marker=dict(line=dict(width=0))
            ), row=1, col=2)
       

        fig.update_xaxes(title_text=f"<b>{perf_metric}</b>", gridcolor='#f1f3f5', row=1, col=1, automargin=True)
        fig.update_xaxes(title_text=f"<b>{perf_metric}</b>", gridcolor='#f1f3f5', row=1, col=2, automargin=True)
        fig.update_yaxes(automargin=True, gridcolor='#f1f3f5')

        fig.update_layout(
            showlegend=False, 
            height=500,
            margin=dict(t=80, b=50, l=20, r=20, autoexpand=True),
            autosize=True,
            template="plotly_white",
            paper_bgcolor='rgba(0,0,0,0)', 
            font=dict(family=font_family, color="#3c4043")
        )
        return fig

    except Exception as e:
        return go.Figure(layout=go.Layout(title=f"Error generating plot: {str(e)}"))
    

# Multivariate Feature Analysis
def generate_multivariate_feature_analysis(records: list, target_col: str, x_cols: list = None, method: str = "pearson") -> go.Figure:
    """
    Unified Analysis for Artifacts: Combines filtered internal math features (lags/rolling) 
    with external uploaded features for a comprehensive Random Forest ranking.
    """
    if not records:
        return go.Figure(layout=go.Layout(title="No data available"))

    try:
        df = pd.DataFrame(records)
        brand_blue = '#1a73e8'   # Internal Math (Lags/Rolling)
        brand_indigo = '#6a11cb' # Internal Time (Calendar/Holidays)
        brand_red = '#d62728'    # External Uploads
        font_family = "Inter, sans-serif"
        
        # 1. Target Column Identification
        y_col = next((c for c in ["TrainActual", "Actual", "y", target_col] if c in df.columns), None)
        if not y_col: 
            return go.Figure(layout=go.Layout(title=f"Target '{target_col}' not found"))
            
        df[y_col] = pd.to_numeric(df[y_col], errors='coerce')
        df = df.dropna(subset=[y_col])
        
        # 2. Smart Feature Selection & Unification
        # A. ALWAYS generate eligible internal math features
        df["Lag_1"] = df[y_col].shift(1)
        df["Lag_7"] = df[y_col].shift(7)
        df["Rolling_Mean_7"] = df[y_col].shift(1).rolling(7).mean()
        
        # B. Define ineligible patterns (cyclic/binary noise to ignore)
        ignore_patterns = ["sin", "cos", "month", "day", "week", "hour", "is_"]
        non_feature_cols = ["Date", "TrainActual", "TrainRaw", "TestActual", "TestPrediction", "Forecast", "Is_Holiday"]

        # C. Filter all available columns to build the final unified list
        analysis_features = [
            c for c in df.columns 
            if c not in non_feature_cols 
            and c != y_col 
            and not any(p in c.lower() for p in ignore_patterns)
        ]
        
        # Create feat_df and rename internal y_col to actual name for display consistency
        feat_df = df[analysis_features + [y_col]].copy()
        feat_df = feat_df.rename(columns={y_col: target_col}) 
        feat_df = feat_df.apply(pd.to_numeric, errors='coerce').fillna(0)
        
        # 3. Model Driver Ranking (Random Forest)
        X = feat_df.drop(columns=[target_col])
        y = feat_df[target_col]
        
        from sklearn.ensemble import RandomForestRegressor
        rf = RandomForestRegressor(n_estimators=100, random_state=42, max_depth=6)
        rf.fit(X, y)
        
        importance = pd.Series(rf.feature_importances_, index=X.columns).sort_values(ascending=True)
        corr_matrix = feat_df.corr(method=method)

        # 4. Categorical Coloring Logic
        colors = []
        for feat in importance.index:
            f_low = feat.lower()
            if any(x in f_low for x in ["lag_", "roll_", "trend_", "spike_"]):
                colors.append(brand_blue)
            elif any(x in f_low for x in ["sin", "cos", "month", "holiday", "week", "day", "is_"]):
                colors.append(brand_indigo)
            else:
                colors.append(brand_red)

        # 5. Build Subplots
        fig = sp.make_subplots(
            rows=2, cols=1,
            row_heights=[0.40, 0.60], 
            subplot_titles=(
                f"<b>Feature Importance Score: {target_col}</b>", 
                f"<b>{method.title()} Correlation Matrix</b>"
            ),
            vertical_spacing=0.3
        )

        # Model Driver Bar Chart
        fig.add_trace(go.Bar(
            x=importance.values, y=importance.index, orientation='h',
            marker=dict(color=colors, line=dict(width=0)),
            text=[f"<b>{v:.4f}</b>" for v in importance.values], 
            textposition="outside",
            name="Weight"
        ), row=1, col=1)

        # Correlation Heatmap
        fig.add_trace(go.Heatmap(
            z=corr_matrix.values, x=corr_matrix.columns, y=corr_matrix.columns,
            colorscale='RdBu', 
            reversescale=True, 
            zmin=-1, zmax=1,
            text=np.round(corr_matrix.values, 2), 
            texttemplate="<b>%{text}</b>",
            showscale=False,
            hoverongaps=False
        ), row=2, col=1)

        # 6. Formatting
        fig.update_yaxes(autorange="reversed", row=2, col=1, automargin=True, gridcolor='#f1f3f5')
        fig.update_yaxes(automargin=True, row=1, col=1, gridcolor='#f1f3f5')
        fig.update_xaxes(automargin=True, row=1, col=1, gridcolor='#f1f3f5')
        fig.update_xaxes(tickangle=-45, automargin=True, row=2, col=1, gridcolor='#f1f3f5')

        fig.update_layout(
            height=max(850, 400 + (len(importance) * 30)), 
            margin=dict(l=120, r=40, t=80, b=100, autoexpand=True), 
            showlegend=False,
            template="plotly_white",
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font=dict(family=font_family, color="#3c4043")
        )
        
        return fig

    except Exception as e:
        return go.Figure(layout=go.Layout(title=f"Analysis Error: {str(e)}"))
    

# Data treatment Comparison
def generate_treatment_comparison_figure(records: list, metric_name: str) -> go.Figure:
    """
    Enhanced UI version of the Data Treatment comparison plot.
    Standardizes colors to Corporate Blue/Red and adds Inter typography.
    """
    if not records:
        return go.Figure(layout=go.Layout(title="No data available"))

    try:
        df = pd.DataFrame(records)
        brand_blue = '#1a73e8'  
        brand_red = '#d62728'   
        font_family = "Inter, sans-serif"
        
        if "TrainRaw" not in df.columns or "TrainActual" not in df.columns:
            return go.Figure(layout=go.Layout(title="Raw data not available for comparison"))
            
        fig = go.Figure()
        
        # Raw Data: Pre-Treatment
        fig.add_trace(go.Scatter(
            x=df["Date"], y=df["TrainRaw"], 
            mode="markers", 
            name="Raw Data (Pre-Treatment)", 
            marker=dict(color=brand_red, symbol="x", size=7), 
            opacity=0.4 # Subdued to let cleaned line stand out
        ))
        
        # Cleaned Data: Post-Treatment 
        fig.add_trace(go.Scatter(
            x=df["Date"], y=df["TrainActual"], 
            mode="lines", 
            name="Cleaned Data (Post-Treatment)", 
            line=dict(color=brand_blue, width=2.5)
        ))
        
        fig.update_xaxes(
            tickangle=-45, 
            automargin=True, 
            gridcolor='#f1f3f5', 
            rangeslider=dict(visible=True, thickness=0.05)
        )
        fig.update_yaxes(
            title_text="Volume", 
            automargin=True, 
            gridcolor='#f1f3f5'
        )

        fig.update_layout(
            title=dict(
                text=f"<b>Data Treatment: Before vs After</b> ({metric_name})", 
                y=0.98,
                x=0.02,
                font=dict(size=18, family=font_family, color="#3c4043")
            ),
            height=500, 
            margin=dict(l=20, r=20, t=80, b=20, autoexpand=True),
            template="plotly_white",
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            legend=dict(
                orientation="h", 
                yanchor="bottom", 
                y=1.02, 
                xanchor="right", 
                x=1,
                font=dict(family=font_family, size=11)
            ),
            hovermode="x unified", 
            autosize=True
        )
        return fig
        
    except Exception as e:
        return go.Figure(layout=go.Layout(title=f"Error plotting treatment comparison: {str(e)}"))
    

# Holiday Analysis
def generate_holiday_table(records: list, target_col: str, holiday_col: str = "Is_Holiday") -> go.Figure:
    """Branded Stats Table with Modern UI Blue Branding."""
    df = pd.DataFrame(records)
    
    if holiday_col not in df.columns:
        potentials = [c for c in df.columns if "holiday" in c.lower() and "name" not in c.lower()]
        holiday_col = potentials[0] if potentials else "Is_Holiday"

    df["is_hol_bool"] = pd.to_numeric(df[holiday_col], errors='coerce').fillna(0).astype(bool)
    stats = df.groupby("is_hol_bool")[target_col].agg(['count', 'sum', 'mean', 'std', 'max'])
    total_sum = df[target_col].sum()
    
    non_hol = stats.loc[False] if False in stats.index else pd.Series(0, index=stats.columns)
    yes_hol = stats.loc[True] if True in stats.index else pd.Series(0, index=stats.columns)
    
    def calc_diff(h, n):
        if n == 0: return "N/A"
        diff = ((h - n) / n) * 100
        return f"{diff:+.1f}%"

    headers = ["<b>Metric</b>", "<b>Non-Holiday</b>", "<b>Holiday</b>", "<b>Difference (%)</b>"]
    rows = [
        ["Count (Days)", f"{int(non_hol['count'])}", f"{int(yes_hol['count'])}", "-"],
        ["Total Volume", f"{non_hol['sum']:,.0f}", f"{yes_hol['sum']:,.0f}", f"{(yes_hol['sum']/total_sum)*100:.1f}% (Contrib)"],
        ["Average Daily", f"{non_hol['mean']:,.2f}", f"{yes_hol['mean']:,.2f}", calc_diff(yes_hol['mean'], non_hol['mean'])],
        ["Max Daily", f"{non_hol['max']:,.2f}", f"{yes_hol['max']:,.2f}", calc_diff(yes_hol['max'], non_hol['max'])],
        ["Volatility (Std)", f"{non_hol['std']:,.2f}", f"{yes_hol['std']:,.2f}", calc_diff(yes_hol['std'], non_hol['std'])],
    ]

    fig = go.Figure(data=[go.Table(
        header=dict(
            values=headers, 
            fill_color='#1a73e8',
            font=dict(color='white', size=13, family="Inter, sans-serif"),
            align='left', 
            height=45
        ),
        cells=dict(
            values=list(zip(*rows)), 
            fill_color=[['#f8f9fa', '#ffffff']*3], 
            line_color='#e9ecef',
            align='left', 
            height=40, 
            font=dict(size=12, family="Inter, sans-serif", color="#3c4043")
        )
    )])
    
    fig.update_layout(height=320, margin=dict(t=10, b=10, l=0, r=0), paper_bgcolor='rgba(0,0,0,0)')
    return fig

def generate_holiday_charts(records: list, target_col: str, holiday_col: str = "Is_Holiday") -> go.Figure:
    """Branded dual-chart view using Corporate Blue and Indigo."""
    df = pd.DataFrame(records)
    
    if "Date" in df.columns: 
        df["DateStr"] = pd.to_datetime(df["Date"]).dt.strftime('%Y-%m-%d')
    else:
        df["DateStr"] = df.index.astype(str)

    df["is_hol_bool"] = pd.to_numeric(df[holiday_col], errors='coerce').fillna(0).astype(bool)
    df["Label"] = df["is_hol_bool"].map({True: "Holiday", False: "Non-Holiday"})

    fig = sp.make_subplots(
        rows=1, cols=2, horizontal_spacing=0.12,
        subplot_titles=("<b>Distribution (Violin Plot)</b>", "<b>Top 5 Holiday Performance</b>")
    )

    # Violin Plot
    for label, color in [("Holiday", "#6a11cb")]:
        subset = df[df["Label"] == label][target_col]
        fig.add_trace(go.Violin(
            y=subset, name=label, box_visible=True, meanline_visible=True,
            line_color=color, fillcolor=color, opacity=0.5, points='outliers', showlegend=True
        ), row=1, col=1)

    # Top 5 Bars 
    hol_only = df[df["is_hol_bool"]].copy()
    if not hol_only.empty:
        if "Holiday_Name" in hol_only.columns:
            hol_only["BarLabel"] = hol_only.apply(lambda x: f"{x['Holiday_Name']}<br>({x['DateStr']})", axis=1)
        else:
            hol_only["BarLabel"] = hol_only["DateStr"]
            
        top5 = hol_only.nlargest(5, target_col).sort_values(target_col, ascending=False)
        fig.add_trace(go.Bar(
            x=top5["BarLabel"], y=top5[target_col], 
            marker_color='#6a11cb',
            text=top5[target_col].apply(lambda x: f"{x:,.0f}"), 
            textposition='auto', 
            showlegend=False
        ), row=1, col=2)

    fig.update_layout(
        height=500, 
        margin=dict(t=60, b=40, l=40, r=40), 
        template="plotly_white",
        font=dict(family="Inter, sans-serif") 
    )
    return fig

def generate_holiday_windows(records: list, target_col: str) -> go.Figure:
    """3x3 Grid showing trend from 7 days before to 3 days after Top 5 holidays with Modern UI."""
    df = pd.DataFrame(records)
    
    if df.empty:
        return go.Figure().update_layout(title="No data available")

    date_col = next((c for c in df.columns if "date" in str(c).lower()), "Date")
    df[date_col] = pd.to_datetime(df[date_col])
    df = df.sort_values(date_col)

    hol_only = df[df["Is_Holiday"] == 1].copy()
    if hol_only.empty:
        return go.Figure().update_layout(
            title="No Holiday Data Available",
            template="plotly_white",
            font=dict(family="Inter, sans-serif")
        )
    
    top5 = hol_only.nlargest(5, target_col)
    
    sub_titles = [
        f"<b>{r['Holiday_Name']}</b><br><span style='font-size:10px; color:#6a11cb'>{r[date_col].strftime('%Y-%m-%d')}</span>" 
        for _, r in top5.iterrows()
    ]

    fig = sp.make_subplots(
        rows=3, cols=3,
        subplot_titles=sub_titles,
        horizontal_spacing=0.1,
        vertical_spacing=0.15
    )

    for i, (_, hol_row) in enumerate(top5.iterrows()):
        row = (i // 3) + 1
        col = (i % 3) + 1
        
        target_date = hol_row[date_col]
        start_date = target_date - pd.Timedelta(days=7)
        end_date = target_date + pd.Timedelta(days=3)
        
        window_df = df[(df[date_col] >= start_date) & (df[date_col] <= end_date)].copy()
        window_df["Delta"] = (window_df[date_col] - target_date).dt.days
        
        fig.add_trace(
            go.Scatter(
                x=window_df["Delta"], 
                y=window_df[target_col],
                mode='lines+markers',
                line=dict(color='#1a73e8', width=3), 
                marker=dict(size=7, color='#6a11cb', line=dict(width=1, color='white')),
                hovertemplate="Day %{x}<br>Value: %{y:,.2f}<extra></extra>",
                showlegend=False
            ), row=row, col=col
        )
        
        fig.add_vline(x=0, line_dash="dash", line_color="#3c4043", opacity=0.4, row=row, col=col)
        
        fig.update_xaxes(
            title_text="Days Offset", 
            tickvals=[-7, -4, 0, 3], 
            gridcolor='#f1f3f5',
            row=row, col=col
        )
        fig.update_yaxes(gridcolor='#f1f3f5', row=row, col=col)

    fig.update_layout(
        height=850,
        template="plotly_white",
        font=dict(family="Inter, sans-serif", color="#3c4043"),
        margin=dict(t=100, b=50, l=50, r=50),
        title=dict(
            text="<b>Top 5 Holiday Window Impact</b>",
            x=0.05,
            font=dict(size=20)
        )
    )
    
    return fig