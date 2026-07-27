"""
metrics.py — ML Evaluation Metrics
===================================
Version : 2.0.0
Changes vs v1.0
---------------
TD-011 FIXED : wmape() floor removed; now configurable (default eps=1e-8, no artificial floor)
TD-012 FIXED : mape() no longer silently returns 0.0 on all-zero actuals; returns None
TD-013 FIXED : trend_error() and variance_penalty() now integrated into composite_score()
               and actually used in model selection
NEW    : rmse() added — standard metric missing in v1.0
NEW    : coverage_score() — prediction interval coverage metric for probabilistic forecasting
NEW    : composite_score() — unified model ranking: WMAPE + trend_error + variance_penalty
NEW    : DemandProfile dataclass — classify_demand() now returns a typed object used for routing
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Optional


# ── Demand classification constants (Syntetos-Boylan thresholds) ────
ADI_THRESHOLD  = 1.32
CV2_THRESHOLD  = 0.49


@dataclass
class DemandProfile:
    """
    Typed result from classify_demand().
    Used by forecasting_engine to route series to the correct model set.
    """
    demand_type : str          # "Smooth" | "Erratic" | "Intermittent" | "Lumpy"
    adi         : float
    cv2         : float
    is_intermittent : bool     # True when ADI >= ADI_THRESHOLD
    is_erratic      : bool     # True when CV2 >= CV2_THRESHOLD
    recommended_models : list  # ordered list of preferred model names

    def to_dict(self) -> dict:
        return {
            "demand_type"        : self.demand_type,
            "adi"                : round(self.adi, 4),
            "cv2"                : round(self.cv2, 4),
            "is_intermittent"    : self.is_intermittent,
            "is_erratic"         : self.is_erratic,
            "recommended_models" : self.recommended_models,
        }


# ════════════════════════════════════════════════════════════════════
# POINT-FORECAST METRICS
# ════════════════════════════════════════════════════════════════════

def wmape(
    actual: pd.Series,
    predicted: pd.Series,
    eps: float = 1e-8,
) -> float:
    """
    Weighted Mean Absolute Percentage Error.

    FIX (TD-011): Removed the hard floor of 5.0 on the denominator that
    artificially suppressed errors on low-volume series. Replaced with
    a tiny epsilon (1e-8) to prevent division-by-zero without distortion.

    Returns: float in [0, ∞).  Lower is better.
    """
    actual    = pd.to_numeric(actual,    errors="coerce").fillna(0)
    predicted = pd.to_numeric(predicted, errors="coerce").fillna(0)

    common = actual.index.intersection(predicted.index)
    a = actual.loc[common].values.astype(float)
    p = predicted.loc[common].values.astype(float)

    numerator   = np.sum(np.abs(a - p))
    denominator = np.sum(np.abs(a)) + eps
    return float(numerator / denominator)


def mae(actual: pd.Series, predicted: pd.Series) -> float:
    """Mean Absolute Error."""
    common = actual.index.intersection(predicted.index)
    a = actual.loc[common].values.astype(float)
    p = predicted.loc[common].values.astype(float)
    return float(np.mean(np.abs(a - p)))


def mape(actual: pd.Series, predicted: pd.Series) -> Optional[float]:
    """
    Mean Absolute Percentage Error.

    FIX (TD-012): Returns None when all actuals are zero instead of
    silently returning 0.0 — which was a misleading result.

    Returns: float percentage, or None if undefined.
    """
    common = actual.index.intersection(predicted.index)
    a = actual.loc[common].values.astype(float)
    p = predicted.loc[common].values.astype(float)

    nonzero_mask = np.abs(a) > 1e-8
    if not nonzero_mask.any():
        return None  # undefined — caller must handle

    a_nz = a[nonzero_mask]
    p_nz = p[nonzero_mask]
    return float(np.mean(np.abs((a_nz - p_nz) / a_nz)) * 100)


def rmse(actual: pd.Series, predicted: pd.Series) -> float:
    """
    Root Mean Squared Error.
    NEW in v2.0 — was missing from v1.0 despite being a standard metric.
    """
    common = actual.index.intersection(predicted.index)
    a = actual.loc[common].values.astype(float)
    p = predicted.loc[common].values.astype(float)
    return float(np.sqrt(np.mean((a - p) ** 2)))


def forecast_accuracy(actual: pd.Series, predicted: pd.Series) -> float:
    """
    Human-readable forecast accuracy: (1 - WMAPE) * 100, clamped to [0, 100].
    Clamp added in v2.0 — v1.0 allowed values > 100%.
    """
    score = (1.0 - wmape(actual, predicted)) * 100.0
    return float(max(0.0, min(100.0, score)))


def trend_error(actual: pd.Series, predicted: pd.Series) -> float:
    """
    Measures directional accuracy — compares the slope of actuals vs
    the slope of predictions over the evaluation window.

    Returns: float in [0, 1]. 0 = perfect trend match. 1 = opposite trend.

    FIX (TD-013): Now integrated into composite_score() so it actually
    influences model selection.
    """
    common = actual.index.intersection(predicted.index)
    a = actual.loc[common].values.astype(float)
    p = predicted.loc[common].values.astype(float)

    # A model whose forecast contains even one non-finite value (observed
    # with ExponentialSmoothing on erratic series) would otherwise poison
    # polyfit with a NaN slope, propagating into composite_score and making
    # any comparison against it silently return False — permanently
    # disqualifying an otherwise-good model from ever being selected.
    valid = np.isfinite(a) & np.isfinite(p)
    a, p = a[valid], p[valid]

    if len(a) < 2:
        return 0.0

    n = np.arange(len(a), dtype=float)
    actual_slope = np.polyfit(n, a, 1)[0]
    pred_slope   = np.polyfit(n, p, 1)[0]

    # Normalise by mean of actuals to make scale-invariant
    scale = np.mean(np.abs(a)) + 1e-8
    return float(np.abs(actual_slope - pred_slope) / scale)


def variance_penalty(
    train_series : pd.Series,
    forecast_series: pd.Series,
    tolerance: float = 2.5,
) -> float:
    """
    Penalises forecasts that are far more volatile than the training history.
    A well-calibrated model should not dramatically amplify noise.

    Returns: float in [0, 1]. 0 = no penalty. 1 = maximum penalty.

    FIX (TD-013): Now integrated into composite_score() so it actually
    influences model selection.
    """
    train_std = float(train_series.std()) + 1e-8
    fc_std    = float(forecast_series.std())
    if np.isnan(fc_std):
        return 0.0
    ratio     = fc_std / train_std

    if ratio <= tolerance:
        return 0.0
    # Soft sigmoid penalty beyond the tolerance band
    excess = ratio - tolerance
    return float(min(1.0, excess / (excess + 1.0)))


def composite_score(
    actual         : pd.Series,
    predicted      : pd.Series,
    train_series   : pd.Series,
    forecast_series: pd.Series,
    w_wmape        : float = 0.70,
    w_trend        : float = 0.20,
    w_variance     : float = 0.10,
) -> float:
    """
    Unified model ranking score combining WMAPE, trend accuracy, and
    forecast variance control.

    NEW in v2.0 — replaces pure WMAPE-based model selection.

    Weights (tunable):
      w_wmape    : 0.70  — primary accuracy signal
      w_trend    : 0.20  — directional accuracy on test window
      w_variance : 0.10  — penalise over-volatile forecasts

    Returns: float. Lower is better (same convention as WMAPE).
    """
    score_wmape    = wmape(actual, predicted)
    score_trend    = trend_error(actual, predicted)
    score_variance = variance_penalty(train_series, forecast_series)

    # Defense in depth: trend_error/variance_penalty are now hardened against
    # non-finite inputs above, but a NaN anywhere in this sum makes the whole
    # composite NaN, and any `<` comparison against NaN is silently False —
    # permanently disqualifying an otherwise-good model from selection rather
    # than raising. Treat an uncomputable penalty term as neutral (0), never
    # as an automatic disqualification.
    if np.isnan(score_trend):
        score_trend = 0.0
    if np.isnan(score_variance):
        score_variance = 0.0

    return float(
        w_wmape    * score_wmape
        + w_trend  * score_trend
        + w_variance * score_variance
    )


def coverage_score(
    actual: pd.Series,
    lower : pd.Series,
    upper : pd.Series,
) -> float:
    """
    Prediction interval coverage score.

    NEW in v2.0 — required for probabilistic forecasting evaluation
    once quantile-based models output upper/lower bounds.

    Returns: float in [0, 1]. Higher is better.
    Target: 0.90 for a 90% prediction interval.
    """
    common = actual.index.intersection(lower.index).intersection(upper.index)
    a = actual.loc[common].values.astype(float)
    l = lower.loc[common].values.astype(float)
    u = upper.loc[common].values.astype(float)

    in_interval = np.sum((a >= l) & (a <= u))
    return float(in_interval / len(a)) if len(a) > 0 else 0.0


def calculate_performance_metrics(
    actual   : pd.Series,
    predicted: pd.Series,
    train_series   : Optional[pd.Series] = None,
    forecast_series: Optional[pd.Series] = None,
) -> dict:
    """
    Returns all metrics in one call for logging / history CSV.

    Extended in v2.0: now includes RMSE, composite_score.
    composite_score only computed when train_series and forecast_series provided.
    """
    w    = wmape(actual, predicted)
    m    = mae(actual, predicted)
    mp   = mape(actual, predicted)
    r    = rmse(actual, predicted)
    acc  = forecast_accuracy(actual, predicted)

    result = {
        "wmape"    : w,
        "mae"      : m,
        "mape"     : mp,       # None when all actuals are zero
        "rmse"     : r,
        "accuracy" : acc,
    }

    if train_series is not None and forecast_series is not None:
        result["composite_score"] = composite_score(
            actual, predicted, train_series, forecast_series
        )

    return result


# ════════════════════════════════════════════════════════════════════
# DEMAND CLASSIFICATION  (Syntetos-Boylan Matrix)
# ════════════════════════════════════════════════════════════════════

def calculate_adi(series: pd.Series) -> float:
    """Average Demand Interval — total periods / non-zero periods."""
    n_total    = len(series)
    n_nonzero  = int((series > 0).sum())
    if n_nonzero == 0:
        return float("inf")
    return float(n_total / n_nonzero)


def calculate_cv2(series: pd.Series) -> float:
    """Squared Coefficient of Variation on non-zero demand values."""
    nonzero = series[series > 0]
    if len(nonzero) < 2:
        return 0.0
    mu  = float(nonzero.mean())
    std = float(nonzero.std())
    return float((std / (mu + 1e-8)) ** 2)


def classify_demand(
    adi_val: Optional[float] = None,
    cv2_val: Optional[float] = None,
    series : Optional[pd.Series] = None,
) -> DemandProfile:
    """
    Syntetos-Boylan demand classification returning a typed DemandProfile.

    FIX (TD-009): v1.0 returned a bare string that was logged but never
    used to route models. v2.0 returns a DemandProfile with
    `recommended_models` — a priority-ordered list consumed by
    ForecastingEngine to select the appropriate model set.

    Can be called with either:
      classify_demand(adi_val=1.5, cv2_val=0.6)
      classify_demand(series=my_series)
    """
    if series is not None:
        adi_val = calculate_adi(series)
        cv2_val = calculate_cv2(series)

    adi = adi_val if adi_val is not None else 0.0
    cv2 = cv2_val if cv2_val is not None else 0.0

    is_intermittent = adi >= ADI_THRESHOLD
    is_erratic      = cv2 >= CV2_THRESHOLD

    # ── Syntetos-Boylan quadrant ──────────────────────────────────
    if not is_intermittent and not is_erratic:
        demand_type = "Smooth"
        # Regular, predictable demand — statistical models shine
        recommended = [
            "ExpSmoothing", "Prophet", "TBATS",
            "LightGBM", "HistGB", "SARIMAX",
        ]

    elif not is_intermittent and is_erratic:
        demand_type = "Erratic"
        # High variance but frequent — ML/robust models preferred
        recommended = [
            "LightGBM", "HistGB", "Prophet",
            "ExpSmoothing", "TBATS",
        ]

    elif is_intermittent and not is_erratic:
        demand_type = "Intermittent"
        # Sparse but regular size when it occurs — Croston ideal
        recommended = [
            "Croston", "ExpSmoothing", "LightGBM",
            "HistGB", "TBATS",
        ]

    else:  # is_intermittent and is_erratic
        demand_type = "Lumpy"
        # Sparse AND variable — most models struggle; use robust ML
        recommended = [
            "Croston", "LightGBM", "HistGB",
            "ExpSmoothing",
        ]

    return DemandProfile(
        demand_type        = demand_type,
        adi                = adi,
        cv2                = cv2,
        is_intermittent    = is_intermittent,
        is_erratic         = is_erratic,
        recommended_models = recommended,
    )