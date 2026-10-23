"""
services/realized_accuracy.py
==============================
Realized-accuracy maths (F17). Pure pandas — no DB, no FastAPI, and no import
of forecasting_engine / processing_engine.

Realized accuracy compares a stored forecast with the values that actually
arrived later. It is deliberately a different number from the backtest
WMAPE the pipeline reports, and is never blended with it.

Definitions (pinned by tests):
    - only dates where BOTH a forecast and a non-null actual exist are compared
    - dates are normalised to calendar days
    - wmape = Σ|actual − forecast| / Σ|actual|          (None when Σ|actual| == 0)
    - mae   = mean |actual − forecast|
    - bias  = (Σforecast − Σactual) / Σ|actual|          (positive = over-forecast)
    - actuals are NOT clipped at 0; forecasts are compared as stored
"""

from __future__ import annotations

from typing import Any, Iterable, Literal

import pandas as pd

from services.data_quality import prepare_sheet, sanitize_with_counts
from utils.forecasting import infer_date_column

RealizedStatus = Literal["awaiting_actuals", "no_overlap", "partial", "complete"]


# ── Series builders ───────────────────────────────────────────────────
def actual_series(df_raw: pd.DataFrame, metric: str) -> pd.Series:
    """Actuals for one metric, cleaned by the pipeline's own rules (F16
    helpers). NaN values are kept — `compare` drops them. Empty when the
    sheet has no usable date column or no such metric."""
    date_col = infer_date_column(df_raw)
    if date_col is None or metric not in df_raw.columns:
        return pd.Series(dtype=float)

    df, _ = prepare_sheet(df_raw, date_col)
    series, _, _ = sanitize_with_counts(df, metric)
    return _by_day(series)


def forecast_series(records: Iterable[dict[str, Any]], key: str = "Forecast") -> pd.Series:
    """Forecast values from results.json records (`Date` + `key`), non-null only."""
    dates: list[pd.Timestamp] = []
    values: list[float] = []
    for rec in records:
        value = rec.get(key)
        if value is None:
            continue
        date = pd.to_datetime(rec.get("Date"), errors="coerce")
        number = pd.to_numeric(value, errors="coerce")
        if pd.isna(date) or pd.isna(number):
            continue
        dates.append(date)
        values.append(float(number))

    if not dates:
        return pd.Series(dtype=float)
    return _by_day(pd.Series(values, index=pd.DatetimeIndex(dates)))


def _by_day(series: pd.Series) -> pd.Series:
    """Normalise the index to calendar days; a repeated day keeps the last value."""
    out       = series.copy()
    out.index = pd.DatetimeIndex(out.index).normalize()
    return out[~out.index.duplicated(keep="last")].sort_index()


# ── Comparison ────────────────────────────────────────────────────────
def compare(actual: pd.Series, forecast: pd.Series) -> dict[str, Any]:
    """Compare a forecast with actuals on the dates both have a value."""
    actual   = actual.dropna()
    forecast = forecast.dropna()
    dates    = actual.index.intersection(forecast.index)

    if len(dates) == 0:
        return {
            "matched_points": 0, "wmape": None, "mae": None, "bias": None,
            "actual_total": 0.0, "forecast_total": 0.0, "points": [],
        }

    a = actual.loc[dates].astype(float)
    f = forecast.loc[dates].astype(float)

    abs_actual = float(a.abs().sum())
    abs_error  = float((a - f).abs().sum())
    wmape      = abs_error / abs_actual if abs_actual > 0 else None
    bias       = (float(f.sum()) - float(a.sum())) / abs_actual if abs_actual > 0 else None

    return {
        "matched_points": int(len(dates)),
        "wmape"         : wmape,
        "mae"           : abs_error / len(dates),
        "bias"          : bias,
        "actual_total"  : float(a.sum()),
        "forecast_total": float(f.sum()),
        "points"        : [
            {"date": d.strftime("%Y-%m-%d"), "actual": float(a.loc[d]), "forecast": float(f.loc[d])}
            for d in dates
        ],
    }


def status_for(forecast_points: int, matched_points: int) -> RealizedStatus:
    """Status of an evaluation that has been run (never `awaiting_actuals`)."""
    if matched_points <= 0:
        return "no_overlap"
    if matched_points >= forecast_points:
        return "complete"
    return "partial"
