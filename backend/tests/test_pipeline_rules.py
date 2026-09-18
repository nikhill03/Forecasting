"""
backend/tests/test_pipeline_rules.py
=====================================
Pins the shared pipeline rules in utils/forecasting.py (F16) to the inline
formulas they replaced in services/forecasting_engine.py and
services/processing_engine.py. The helpers exist so the data-quality report
and the pipeline can't drift apart; this file is what proves extracting
them changed no forecast.

The "legacy" expressions below are copied verbatim from the pre-F16 code
on purpose — do not rewrite them in terms of the helpers.
"""

from __future__ import annotations

import pytest

from services.data_handling import DataHandling
from utils.forecasting import (
    MIN_SERIES_POINTS,
    effective_horizon,
    holdout_size,
    min_test_overlap,
)

SERIES_LENGTHS = [0, 1, 14, 15, 29, 30, 34, 35, 36, 46, 47, 60, 99, 100, 150, 365, 730, 2000]


class TestHoldoutSize:

    @pytest.mark.parametrize("n", SERIES_LENGTHS)
    @pytest.mark.parametrize("test_window", [7, 8, 14, 30, 60, 90, 180])
    def test_matches_legacy_train_test_split(self, n, test_window):
        legacy = max(7, min(test_window, int(n * 0.20)))
        assert holdout_size(n, test_window) == legacy


class TestEffectiveHorizon:

    @pytest.mark.parametrize("n", SERIES_LENGTHS)
    @pytest.mark.parametrize("horizon", [1, 7, 14, 15, 30, 60, 180, 365])
    def test_matches_legacy_horizon_cap(self, n, horizon):
        absolute_max_limit = max(14, int(n * 0.30))
        legacy = min(int(horizon), absolute_max_limit)
        assert effective_horizon(n, horizon) == legacy

    @pytest.mark.parametrize("n", SERIES_LENGTHS)
    @pytest.mark.parametrize("horizon", [1, 14, 60, 365])
    def test_capped_notice_condition_unchanged(self, n, horizon):
        # Pre-F16 logged "capped" when horizon > absolute_max_limit; the
        # pipeline now compares against the helper's result.
        absolute_max_limit = max(14, int(n * 0.30))
        assert (horizon > absolute_max_limit) == (horizon > effective_horizon(n, horizon))


class TestMinTestOverlap:

    @pytest.mark.parametrize("split", [0, 1, 7, 10, 23, 24, 30, 60, 180])
    def test_matches_legacy_min_required(self, split):
        assert min_test_overlap(split) == max(7, int(0.3 * split))


class TestMinSeriesPoints:

    def test_value(self):
        assert MIN_SERIES_POINTS == 30

    def test_data_handling_default_agrees(self):
        # DataHandling's own default is what processing_engine used to pass
        # literally; if it ever changes, this constant needs a decision.
        assert DataHandling().min_points == MIN_SERIES_POINTS
