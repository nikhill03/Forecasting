"""
backend/tests/test_metrics.py
==============================
Unit tests for utils/metrics.py (v2.0).
Covers all fixed bugs from the tech debt register.
"""

import numpy as np
import pandas as pd
import pytest

from utils.metrics import (
    DemandProfile,
    calculate_adi,
    calculate_cv2,
    classify_demand,
    composite_score,
    coverage_score,
    forecast_accuracy,
    mae,
    mape,
    rmse,
    trend_error,
    variance_penalty,
    wmape,
)


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def perfect_pred():
    idx = pd.date_range("2024-01-01", periods=10, freq="D")
    actual = pd.Series([10.0] * 10, index=idx)
    return actual, actual.copy()


@pytest.fixture
def simple_series():
    idx    = pd.date_range("2024-01-01", periods=20, freq="D")
    actual = pd.Series(range(1, 21), index=idx, dtype=float)
    pred   = pd.Series(range(2, 22), index=idx, dtype=float)
    return actual, pred


@pytest.fixture
def zero_series():
    idx = pd.date_range("2024-01-01", periods=10, freq="D")
    return pd.Series([0.0] * 10, index=idx)


# ── wmape tests ───────────────────────────────────────────────────

class TestWmape:
    def test_perfect_prediction(self, perfect_pred):
        actual, pred = perfect_pred
        assert wmape(actual, pred) == 0.0

    def test_no_artificial_floor(self, zero_series):
        """TD-011 FIX: wmape should not apply a floor of 5.0."""
        idx  = zero_series.index
        pred = pd.Series([1.0] * 10, index=idx)
        # With floor=5.0 (v1.0), wmape would be 10/5 = 2.0
        # With eps=1e-8 (v2.0), wmape should be very large (10/1e-8)
        result = wmape(zero_series, pred)
        # Should NOT be 2.0 (the artificial floor result)
        assert result != pytest.approx(2.0, rel=0.01)
        assert result > 1e6  # numerator >> denominator

    def test_known_value(self, simple_series):
        actual, pred = simple_series
        result = wmape(actual, pred)
        assert 0.0 < result < 1.0

    def test_returns_float(self, simple_series):
        actual, pred = simple_series
        assert isinstance(wmape(actual, pred), float)


# ── mape tests ────────────────────────────────────────────────────

class TestMape:
    def test_returns_none_on_all_zeros(self, zero_series):
        """TD-012 FIX: mape should return None, not 0.0, on all-zero actuals."""
        idx  = zero_series.index
        pred = pd.Series([1.0] * 10, index=idx)
        result = mape(zero_series, pred)
        assert result is None, "mape() must return None when all actuals are zero"

    def test_normal_calculation(self, simple_series):
        actual, pred = simple_series
        result = mape(actual, pred)
        assert result is not None
        assert result > 0.0

    def test_perfect_prediction_returns_zero(self, perfect_pred):
        actual, pred = perfect_pred
        assert mape(actual, pred) == pytest.approx(0.0)


# ── rmse tests ────────────────────────────────────────────────────

class TestRmse:
    def test_perfect_prediction(self, perfect_pred):
        actual, pred = perfect_pred
        assert rmse(actual, pred) == pytest.approx(0.0)

    def test_known_value(self):
        idx    = pd.date_range("2024-01-01", periods=3, freq="D")
        actual = pd.Series([1.0, 2.0, 3.0], index=idx)
        pred   = pd.Series([2.0, 3.0, 4.0], index=idx)
        # errors all 1.0, RMSE = sqrt(mean([1,1,1])) = 1.0
        assert rmse(actual, pred) == pytest.approx(1.0)

    def test_returns_float(self, simple_series):
        actual, pred = simple_series
        assert isinstance(rmse(actual, pred), float)


# ── forecast_accuracy tests ───────────────────────────────────────

class TestForecastAccuracy:
    def test_clamped_at_100(self, perfect_pred):
        actual, pred = perfect_pred
        result = forecast_accuracy(actual, pred)
        assert result <= 100.0

    def test_clamped_at_zero(self, zero_series):
        """v2.0 clamps accuracy to [0, 100] — v1.0 allowed > 100."""
        idx  = zero_series.index
        pred = pd.Series([1000.0] * 10, index=idx)
        result = forecast_accuracy(zero_series, pred)
        assert result >= 0.0

    def test_perfect_gives_100(self, perfect_pred):
        actual, pred = perfect_pred
        assert forecast_accuracy(actual, pred) == pytest.approx(100.0)


# ── trend_error tests ─────────────────────────────────────────────

class TestTrendError:
    def test_same_trend_gives_zero(self):
        idx  = pd.date_range("2024-01-01", periods=10, freq="D")
        vals = pd.Series(range(10), index=idx, dtype=float)
        assert trend_error(vals, vals) == pytest.approx(0.0)

    def test_opposite_trend_gives_high_score(self):
        idx    = pd.date_range("2024-01-01", periods=10, freq="D")
        actual = pd.Series(range(10), index=idx, dtype=float)
        pred   = pd.Series(range(9, -1, -1), index=idx, dtype=float)
        result = trend_error(actual, pred)
        # actual slope=1.0, pred slope=-1.0, diff=2.0, normalised by mean(|actual|)=4.5
        # => 2.0 / 4.5 ≈ 0.444. Asserting it's clearly non-trivial (>0.3) and
        # strictly greater than the same-trend case (which is 0.0).
        assert result > 0.3
        assert result > trend_error(actual, actual)

    def test_returns_float(self, simple_series):
        actual, pred = simple_series
        assert isinstance(trend_error(actual, pred), float)


# ── variance_penalty tests ────────────────────────────────────────

class TestVariancePenalty:
    def test_no_penalty_within_tolerance(self):
        idx   = pd.date_range("2024-01-01", periods=50, freq="D")
        train = pd.Series(np.random.normal(10, 1, 50), index=idx)
        fc    = pd.Series(np.random.normal(10, 2, 50), index=idx)
        # 2x std of train — within default tolerance of 2.5
        assert variance_penalty(train, fc) == 0.0

    def test_penalty_beyond_tolerance(self):
        idx   = pd.date_range("2024-01-01", periods=50, freq="D")
        train = pd.Series(np.ones(50), index=idx)
        fc    = pd.Series(np.random.normal(10, 10, 50), index=idx)
        assert variance_penalty(train, fc) > 0.0

    def test_returns_in_zero_one(self, simple_series):
        actual, pred = simple_series
        result = variance_penalty(actual, pred)
        assert 0.0 <= result <= 1.0


# ── composite_score tests ─────────────────────────────────────────

class TestCompositeScore:
    def test_lower_is_better(self, simple_series):
        actual, pred = simple_series
        idx    = actual.index
        worse  = pd.Series([100.0] * 20, index=idx)
        score_good  = composite_score(actual, pred,   actual, pred)
        score_bad   = composite_score(actual, worse,  actual, worse)
        assert score_good < score_bad

    def test_returns_float(self, simple_series):
        actual, pred = simple_series
        result = composite_score(actual, pred, actual, pred)
        assert isinstance(result, float)
        assert result >= 0.0


# ── coverage_score tests ──────────────────────────────────────────

class TestCoverageScore:
    def test_perfect_coverage(self):
        idx    = pd.date_range("2024-01-01", periods=10, freq="D")
        actual = pd.Series([5.0] * 10, index=idx)
        lower  = pd.Series([0.0] * 10, index=idx)
        upper  = pd.Series([10.0] * 10, index=idx)
        assert coverage_score(actual, lower, upper) == pytest.approx(1.0)

    def test_zero_coverage(self):
        idx    = pd.date_range("2024-01-01", periods=10, freq="D")
        actual = pd.Series([50.0] * 10, index=idx)
        lower  = pd.Series([0.0]  * 10, index=idx)
        upper  = pd.Series([1.0]  * 10, index=idx)
        assert coverage_score(actual, lower, upper) == pytest.approx(0.0)


# ── classify_demand tests ─────────────────────────────────────────

class TestClassifyDemand:
    def test_returns_demand_profile(self):
        result = classify_demand(adi_val=1.0, cv2_val=0.3)
        assert isinstance(result, DemandProfile)

    def test_smooth_demand(self):
        result = classify_demand(adi_val=1.0, cv2_val=0.3)
        assert result.demand_type == "Smooth"
        assert not result.is_intermittent
        assert not result.is_erratic

    def test_erratic_demand(self):
        result = classify_demand(adi_val=1.0, cv2_val=0.6)
        assert result.demand_type == "Erratic"
        assert result.is_erratic

    def test_intermittent_demand(self):
        result = classify_demand(adi_val=2.0, cv2_val=0.3)
        assert result.demand_type == "Intermittent"
        assert result.is_intermittent
        assert "Croston" in result.recommended_models

    def test_lumpy_demand(self):
        result = classify_demand(adi_val=2.0, cv2_val=0.6)
        assert result.demand_type == "Lumpy"
        assert result.is_intermittent
        assert result.is_erratic
        assert "Croston" in result.recommended_models

    def test_to_dict(self):
        result = classify_demand(adi_val=1.0, cv2_val=0.3)
        d = result.to_dict()
        assert "demand_type" in d
        assert "recommended_models" in d
        assert isinstance(d["recommended_models"], list)

    def test_from_series(self):
        """classify_demand accepts a series directly."""
        idx    = pd.date_range("2024-01-01", periods=20, freq="D")
        series = pd.Series([10.0] * 20, index=idx)
        result = classify_demand(series=series)
        assert isinstance(result, DemandProfile)