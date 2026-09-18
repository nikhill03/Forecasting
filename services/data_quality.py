"""
services/data_quality.py
=========================
Pre-run data-quality profiling (F16). Pure pandas — no DB, no FastAPI, and
deliberately no import of forecasting_engine / processing_engine, which pull
in prophet and statsmodels.

The report describes what processing_worker *will do* to each selected
series, not a generic data-science checklist. Every check below maps to a
concrete, otherwise-silent pipeline behaviour:

    insufficient_history   DataHandling.sanitize drops a series < MIN_SERIES_POINTS   (blocking)
    unparseable_dates      rows with an unparseable date are dropped
    non_numeric_values     non-numeric metric values become NaN
    duplicate_timestamps   duplicate dates: last row kept, values NOT summed
    non_daily_frequency    the series is always reindexed to daily
    date_gaps              ... and missing days are imputed
    negative_values        negatives are clipped to 0
    outliers               values > Q3 + 3·IQR are clipped, only when |skew| > 2
    horizon_capped         horizon capped at 30% of history
    sparse_test_window     too few non-zero test actuals → models are skipped
    short_history          seasonal-median imputation needs > 90 days

Pipeline thresholds come from utils/forecasting.py, shared with the
pipeline itself. Thresholds that exist only for this report are defined
here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from utils.forecasting import (
    MIN_SERIES_POINTS,
    effective_horizon,
    holdout_size,
    infer_date_column,
    min_test_overlap,
)

# ── Report-only thresholds ────────────────────────────────────────────
DATE_GAP_WARN_PCT      = 0.10   # daily data with more than this share imputed
SHORT_HISTORY_DAYS     = 90     # treatment_analyzer.py: seasonal imputation needs > 90 days
OUTLIER_IQR_MULTIPLIER = 3.0    # data_handling.py clip threshold
OUTLIER_CLIP_SKEW      = 2.0    # treatment_analyzer.py: clip only when |skew| > 2

BLOCKING = "blocking"
WARNING  = "warning"


# ── Helpers ───────────────────────────────────────────────────────────
def _issue(code: str, severity: str, message: str) -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message}


def _plural(n: int, word: str) -> str:
    return f"{n:,} {word}" if n == 1 else f"{n:,} {word}s"


def _pct(fraction: float) -> str:
    return f"{fraction * 100:.0f}%"


def _infer_frequency(index: pd.DatetimeIndex) -> str | None:
    if len(index) < 3:
        return None
    try:
        return pd.infer_freq(index)
    except (TypeError, ValueError):
        return None


def _prepare_sheet(df_raw: pd.DataFrame, date_col: str) -> tuple[pd.DataFrame, int]:
    """Mirror processing_worker's per-sheet prep (processing_engine.py:~505):
    coerce dates, drop the unparseable rows, index and sort."""
    df = df_raw.copy()
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    unparseable = int(df[date_col].isna().sum())
    df = df.dropna(subset=[date_col]).set_index(date_col).sort_index()
    return df, unparseable


def _sanitize_with_counts(df: pd.DataFrame, metric: str) -> tuple[pd.Series, int, int]:
    """DataHandling.sanitize (data_handling.py:31-41), counting what each
    step removes. Returns (series, non_numeric_values, duplicate_timestamps).
    Unlike sanitize it never returns None — the report needs the counts
    precisely when the series is too short."""
    out = df.reset_index()
    date_col = out.columns[0]
    out = out[[date_col, metric]].copy()

    before_numeric = out[metric].notna()
    out[metric] = pd.to_numeric(out[metric], errors="coerce")
    non_numeric = int((before_numeric & out[metric].isna()).sum())

    out[date_col] = pd.to_datetime(out[date_col], errors="coerce")
    out = out.dropna(subset=[date_col])

    rows_before = len(out)
    out = out.drop_duplicates(subset=[date_col], keep="last")
    duplicates = rows_before - len(out)

    out = out.sort_values(date_col).set_index(date_col)
    return out[metric], non_numeric, duplicates


# ── Per-series profile ────────────────────────────────────────────────
def profile_series(
    df_raw: pd.DataFrame,
    sheet: str,
    metric: str,
    forecast_horizon: int,
    test_window: int,
) -> dict[str, Any]:
    """Profile one (sheet, metric) series as the pipeline will see it."""
    issues: list[dict[str, str]] = []

    profile: dict[str, Any] = {
        "sheet"               : sheet,
        "metric"              : metric,
        "rows_total"          : int(len(df_raw)),
        "usable_points"       : 0,
        "start"               : None,
        "end"                 : None,
        "span_days"           : None,
        "inferred_frequency"  : None,
        "imputed_pct"         : None,
        "duplicate_timestamps": 0,
        "unparseable_dates"   : 0,
        "non_numeric_values"  : 0,
        "negative_values"     : 0,
        "zero_pct"            : 0.0,
        "outliers"            : 0,
        "test_split_size"     : 0,
        "effective_horizon"   : 0,
        "issues"              : issues,
    }

    date_col = infer_date_column(df_raw)
    if date_col is None or metric not in df_raw.columns:
        issues.append(_issue(
            "insufficient_history", BLOCKING,
            "No usable date column was found, so there is nothing to forecast.",
        ))
        return profile

    df, unparseable = _prepare_sheet(df_raw, date_col)
    series, non_numeric, duplicates = _sanitize_with_counts(df, metric)
    values = series.dropna()
    usable = int(len(values))
    n      = int(len(series))   # the pipeline splits and caps on len(raw_series), NaNs included

    profile.update(
        usable_points        = usable,
        unparseable_dates    = unparseable,
        non_numeric_values   = non_numeric,
        duplicate_timestamps = duplicates,
    )

    # ── Row-level warnings — valid even for a series too short to run ──
    if unparseable:
        issues.append(_issue(
            "unparseable_dates", WARNING,
            f"{_plural(unparseable, 'row')} with a missing or unreadable date will be dropped.",
        ))
    if non_numeric:
        issues.append(_issue(
            "non_numeric_values", WARNING,
            f"{_plural(non_numeric, 'value')} in '{metric}' aren't numbers and will be treated as missing.",
        ))
    if duplicates:
        issues.append(_issue(
            "duplicate_timestamps", WARNING,
            f"{_plural(duplicates, 'duplicate date')}: only the last value for each date is kept — "
            "values are not summed.",
        ))

    if n > 0:
        # Facts, not checks — worth showing even when the series is blocked.
        # The range is the pipeline's: its daily reindex spans every dated
        # row, including rows whose value is missing.
        profile.update(
            start     = series.index.min().to_pydatetime(),
            end       = series.index.max().to_pydatetime(),
            span_days = int((series.index.max() - series.index.min()).days),
        )

    if usable < MIN_SERIES_POINTS:
        issues.append(_issue(
            "insufficient_history", BLOCKING,
            f"Only {_plural(usable, 'usable data point')}; at least {MIN_SERIES_POINTS} "
            "are needed to train and test a model.",
        ))
        return profile

    # ── Shape of the series ────────────────────────────────────────────
    start, end = series.index.min(), series.index.max()
    span_days  = int((end - start).days)
    median_gap = series.index.to_series().diff().dropna().median()

    daily_index  = pd.date_range(start=start, end=end, freq="D")
    on_daily     = series.reindex(daily_index)
    imputed_pct  = float(on_daily.isna().mean()) if len(daily_index) else 0.0
    kept_on_grid = int(on_daily.notna().sum())

    split   = holdout_size(n, test_window)
    horizon = effective_horizon(n, forecast_horizon)

    profile.update(
        inferred_frequency = _infer_frequency(series.index),
        imputed_pct        = round(imputed_pct, 4),
        test_split_size    = split,
        effective_horizon  = horizon,
    )

    # ── Frequency / gaps ───────────────────────────────────────────────
    if median_gap > pd.Timedelta(days=1):
        issues.append(_issue(
            "non_daily_frequency", WARNING,
            f"Data is spaced about every {median_gap.days} days, but the pipeline works on daily "
            f"data — {_pct(imputed_pct)} of the daily points it trains on will be filled in, "
            "not observed.",
        ))
    elif median_gap < pd.Timedelta(days=1):
        dropped = usable - kept_on_grid
        issues.append(_issue(
            "non_daily_frequency", WARNING,
            f"Data is recorded more often than daily, but the pipeline keeps one reading per day — "
            f"{_plural(dropped, 'data point')} of {usable:,} will be ignored.",
        ))
    elif imputed_pct > DATE_GAP_WARN_PCT:
        issues.append(_issue(
            "date_gaps", WARNING,
            f"{_pct(imputed_pct)} of the days between {start.date()} and {end.date()} have no value "
            "and will be filled in by the pipeline.",
        ))

    # ── Value checks ───────────────────────────────────────────────────
    negatives = int((values < 0).sum())
    zero_pct  = float((values == 0).mean())
    q1, q3    = values.quantile(0.25), values.quantile(0.75)
    iqr       = q3 - q1
    upper     = q3 + OUTLIER_IQR_MULTIPLIER * iqr
    outliers  = int((values > upper).sum()) if iqr > 0 else 0
    skew      = values.skew()
    will_clip = bool(pd.notna(skew) and abs(skew) > OUTLIER_CLIP_SKEW)

    profile.update(
        negative_values = negatives,
        zero_pct        = round(zero_pct, 4),
        outliers        = outliers,
    )

    if negatives:
        issues.append(_issue(
            "negative_values", WARNING,
            f"{_plural(negatives, 'negative value')} will be clipped to 0.",
        ))
    if outliers:
        treatment = (
            f"they will be clipped to {upper:,.2f}" if will_clip
            else "they will be left as-is, and may pull the forecast"
        )
        issues.append(_issue(
            "outliers", WARNING,
            f"{_plural(outliers, 'unusually high value')} (above {upper:,.2f}); {treatment}.",
        ))

    # ── Run-configuration checks ───────────────────────────────────────
    if int(forecast_horizon) > horizon:
        issues.append(_issue(
            "horizon_capped", WARNING,
            f"The {forecast_horizon}-day horizon will be shortened to {horizon} days — the pipeline "
            "caps it at 30% of the available history.",
        ))

    test_values = series.iloc[-split:].dropna()
    scoreable   = int((test_values != 0).sum())
    required    = min_test_overlap(split)
    if scoreable < required:
        issues.append(_issue(
            "sparse_test_window", WARNING,
            f"Only {_plural(scoreable, 'non-zero value')} in the last {split} points used for "
            f"testing; models need {required} to be scored, so most will be skipped and the run "
            "may fall back to a simple moving average.",
        ))

    if span_days <= SHORT_HISTORY_DAYS:
        issues.append(_issue(
            "short_history", WARNING,
            f"Only {span_days} days of history — too short for seasonal patterns, so the forecast "
            "will mostly follow recent levels.",
        ))

    return profile


# ── Whole report ──────────────────────────────────────────────────────
def build_report(
    sheets: dict[str, pd.DataFrame],
    selected_sheets: list[str],
    selected_metrics: list[str],
    forecast_horizon: int,
    test_window: int,
) -> dict[str, Any]:
    """Profile every selected (sheet, metric) pair the pipeline will run.

    processing_worker silently skips a selected sheet that isn't in the file
    and a selected metric that isn't a column of a sheet; those become
    report-level warnings. If *no* pair exists at all the run would produce
    nothing, so that is blocking.
    """
    series_profiles: list[dict[str, Any]] = []
    report_issues:   list[dict[str, str]] = []

    for sheet in selected_sheets:
        df_raw = sheets.get(sheet)
        if df_raw is None:
            report_issues.append(_issue(
                "metric_missing_in_sheet", WARNING,
                f"Sheet '{sheet}' isn't in this file and will be skipped.",
            ))
            continue
        for metric in dict.fromkeys(selected_metrics):
            if metric not in df_raw.columns:
                report_issues.append(_issue(
                    "metric_missing_in_sheet", WARNING,
                    f"'{metric}' isn't a column in sheet '{sheet}', so it won't be forecast there.",
                ))
                continue
            series_profiles.append(
                profile_series(df_raw, sheet, metric, forecast_horizon, test_window)
            )

    if not series_profiles:
        report_issues.append(_issue(
            "insufficient_history", BLOCKING,
            "None of the selected metrics exist in the selected sheets, so there is nothing to forecast.",
        ))

    has_blocking = any(i["severity"] == BLOCKING for i in report_issues) or any(
        i["severity"] == BLOCKING for p in series_profiles for i in p["issues"]
    )

    return {
        "generated_at": datetime.now(timezone.utc),
        "has_blocking": has_blocking,
        "series"      : series_profiles,
        "issues"      : report_issues,
    }
