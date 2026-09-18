import io
import base64
import pandas as pd
from typing import Dict, Optional


# ── Pipeline rules ────────────────────────────────────────────────────
# The single definition of each numeric rule the forecast pipeline applies
# to a series. processing_engine / forecasting_engine enforce them and
# services/data_quality.py reports on them (F16) — both import from here so
# the pre-run report cannot drift from what a run actually does.

MIN_SERIES_POINTS = 30   # DataHandling.sanitize drops a series below this


def holdout_size(n: int, test_window: int) -> int:
    """Points held out for backtesting: the requested window, capped at 20%
    of the series, never fewer than 7."""
    return max(7, min(int(test_window), int(n * 0.20)))


def effective_horizon(n: int, horizon: int) -> int:
    """Forecast horizon after the pipeline's cap of 30% of history (min 14)."""
    return min(int(horizon), max(14, int(n * 0.30)))


def min_test_overlap(split: int) -> int:
    """Non-zero, non-null test actuals a model needs to be scored at all."""
    return max(7, int(0.3 * split))


def infer_date_column(df: pd.DataFrame, min_parse_ratio: float = 0.8) -> Optional[str]:
    """
    Detects the date/time column by parsing actual values, not by matching
    a hardcoded column name like "Date" — real datasets name this column
    Month, Period, Year, Week, Timestamp, etc. Returns the first column (in
    original order) whose non-null values parse as dates at or above
    min_parse_ratio; an already-datetime-typed column is returned outright.

    Plain numeric columns are only considered if their values look like
    4-digit calendar years: pd.to_datetime silently accepts arbitrary
    integers as nanosecond-epoch timestamps, which would otherwise make a
    numeric target column (e.g. "Sales") look like a "100% parseable" date
    column.

    Returns None if no column qualifies.
    """
    if df.empty:
        return None

    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            return col

    for col in df.columns:
        series = df[col].dropna()
        if series.empty:
            continue

        if pd.api.types.is_numeric_dtype(series):
            looks_like_year = series.between(1900, 2100).mean() >= min_parse_ratio
            if not looks_like_year:
                continue
            parsed = pd.to_datetime(series.astype(int).astype(str), format="%Y", errors="coerce")
        else:
            parsed = pd.to_datetime(series.astype(str), errors="coerce")

        if parsed.notna().mean() >= min_parse_ratio:
            return col

    return None

def parse_uploaded_data(contents: str) -> Dict[str, pd.DataFrame]:
    """
    Parse a base64-encoded uploaded Excel (or CSV) contents into a dict sheet -> DataFrame.
    """
    if not contents:
        return {}
    if "," in contents:
        _, content_string = contents.split(",", 1)
        decoded = base64.b64decode(content_string)
    else:
        decoded = contents if isinstance(contents, (bytes, bytearray)) else None
    if decoded is None:
        return {}
    try:
        xl = pd.ExcelFile(io.BytesIO(decoded))
        dfs = {s: xl.parse(s) for s in xl.sheet_names}
        return dfs
    except Exception:
        try:
            df = pd.read_csv(io.BytesIO(decoded))
            return {"Sheet1": df}
        except Exception:
            return {}