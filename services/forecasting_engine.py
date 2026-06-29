"""
forecasting_engine.py — Univariate Forecasting Engine
======================================================
Version : 2.0.0
Changes vs v1.0
---------------
TD-005 FIXED : TBATS now uses make_future_dataframe / model.forecast() for true hold-out
               test prediction instead of in-sample y_hat
TD-006 FIXED : SARIMAX now uses pmdarima.auto_arima for order selection with fallback to (1,1,1)
TD-007 FIXED : QUANTILE_LEVEL is now a constructor parameter (default 0.75, user-configurable)
TD-008 FIXED : fillna(method='ffill') replaced with .ffill() everywhere (pandas 2.x compat)
TD-009 FIXED : Model selection now demand-routing aware via DemandProfile.recommended_models
TD-010 FIXED : Prophet seasonality now inferred from detected frequency instead of always True
TD-016 PARTIAL: SMA window is now adaptive (min 7, max 28, based on series length)
NEW   : Croston's Method re-enabled for Intermittent and Lumpy demand types
NEW   : Theta Method added — strong M3/M4 competition benchmark
NEW   : Linear Regression baseline added — better than SMA for trended series
NEW   : _infer_prophet_seasonality() helper — freq-aware Prophet config
NEW   : composite_score used in model selection (WMAPE + trend + variance penalty)
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

logger = logging.getLogger("ml.forecasting_engine")


# ── Result container ─────────────────────────────────────────────────
@dataclass
class ModelResult:
    model_name       : str
    model_object     : object
    wmape            : float
    composite        : float = 0.0
    predictions_test : Optional[pd.Series] = None
    forecast         : Optional[pd.Series] = None
    error            : Optional[str] = None


# ── Frequency helpers ────────────────────────────────────────────────
_FREQ_ALIAS_MAP = {
    "D"  : "D",   "B"  : "B",
    "W"  : "W",   "W-SUN": "W", "W-MON": "W",
    "MS" : "MS",  "M"  : "MS",
    "QS" : "QS",  "Q"  : "QS",
    "AS" : "AS",  "A"  : "AS", "Y": "AS", "YS": "AS",
    "H"  : "H",   "T"  : "T",
}

_SEASONAL_PERIOD_MAP = {
    "D" : 7,    # weekly seasonality for daily data
    "B" : 5,    # business-week
    "W" : 52,   # yearly for weekly
    "MS": 12,   # yearly for monthly
    "QS": 4,    # yearly for quarterly
    "AS": 1,    # no seasonality for annual
    "H" : 24,   # daily for hourly
    "T" : 60,   # hourly for minute-level
}


def _infer_prophet_seasonality(freq: str) -> dict:
    """
    FIX (TD-010): Returns Prophet seasonality kwargs based on detected frequency.
    v1.0 always set daily_seasonality=True regardless of freq — caused severe
    overfitting on weekly/monthly data.
    """
    f = freq.upper()
    if f in ("D", "B", "H", "T"):
        return dict(daily_seasonality=True,  weekly_seasonality=True,  yearly_seasonality=True)
    elif f in ("W", "W-SUN", "W-MON"):
        return dict(daily_seasonality=False, weekly_seasonality=False, yearly_seasonality=True)
    elif f in ("MS", "M"):
        return dict(daily_seasonality=False, weekly_seasonality=False, yearly_seasonality=True)
    elif f in ("QS", "Q"):
        return dict(daily_seasonality=False, weekly_seasonality=False, yearly_seasonality=False)
    else:
        return dict(daily_seasonality=False, weekly_seasonality=True,  yearly_seasonality=True)


# ════════════════════════════════════════════════════════════════════
class ForecastingEngine:
    """
    Univariate Forecasting Engine v2.0

    Parameters
    ----------
    freq          : pandas frequency string (e.g. 'D', 'W', 'MS')
    horizon       : number of future periods to forecast
    test_size     : number of periods for hold-out evaluation
    quantile_level: quantile for ML models (default 0.75 = upper-biased)
                    FIX TD-007: now user-configurable, was hardcoded in v1.0
    """

    def __init__(
        self,
        freq           : str   = "D",
        horizon        : int   = 60,
        test_size      : int   = 30,
        quantile_level : float = 0.75,
    ):
        self.freq           = _FREQ_ALIAS_MAP.get(freq.upper(), freq)
        self.horizon        = horizon
        self.test_size      = test_size
        self.quantile_level = quantile_level   # FIX TD-007
        self.seasonal_period = _SEASONAL_PERIOD_MAP.get(self.freq.upper(), 7)

        # Full model registry — keys used for demand routing
        self.models: Dict[str, Callable] = {
            "TBATS"        : self._run_tbats,
            "Prophet"      : self._run_prophet,
            "LightGBM"     : self._run_lightgbm,
            "HistGB"       : self._run_hist_gb,
            "ExpSmoothing" : self._run_expsmoothing,
            "SARIMAX"      : self._run_sarimax,
            "Croston"      : self._run_croston,      # RE-ENABLED TD-009
            "Theta"        : self._run_theta,         # NEW
            "LinearBaseline": self._run_linear,       # NEW
        }

    # ── Train / Test split ───────────────────────────────────────────
    def _train_test_split(
        self, series: pd.Series
    ) -> tuple[pd.Series, pd.Series]:
        n = len(series)
        if n < 15:
            raise ValueError(f"Series too short ({n} points). Minimum 15 required.")
        split = max(7, min(self.test_size, int(n * 0.20)))
        return series.iloc[:-split], series.iloc[-split:]

    # ── Future date index ────────────────────────────────────────────
    def _future_index(
        self,
        last_date : pd.Timestamp,
        horizon   : int,
        ref_index : pd.DatetimeIndex,
    ) -> pd.DatetimeIndex:
        try:
            inferred = pd.infer_freq(ref_index[-10:]) or self.freq
        except Exception:
            inferred = self.freq
        return pd.date_range(
            start=last_date + pd.tseries.frequencies.to_offset(inferred),
            periods=horizon,
            freq=inferred,
        )

    # ── Frequency inference with fallback ───────────────────────────
    def _safe_infer_freq(self, series: pd.Series) -> str:
        try:
            f = pd.infer_freq(series.index)
            return f or self.freq
        except Exception:
            return self.freq

    # ── Feature engineering (pandas 2.x compatible) ─────────────────
    def _make_features_robust(self, series: pd.Series) -> pd.DataFrame:
        """
        FIX (TD-008): Replaced fillna(method='ffill') with .ffill()
        throughout this function. pandas 2.x deprecated the method= kwarg.
        """
        df = pd.DataFrame({"y": series})
        idx = series.index

        # Lag features
        for lag in [1, 2, 3, 7, 14, 21, 28]:
            df[f"lag_{lag}"] = series.shift(lag)

        # Rolling features — FIX TD-008: .ffill() not fillna(method='ffill')
        df["roll_mean_7"]  = series.shift(1).rolling(7,  min_periods=1).mean()
        df["roll_std_7"]   = series.shift(1).rolling(7,  min_periods=2).std().ffill().fillna(0)
        df["roll_mean_14"] = series.shift(1).rolling(14, min_periods=1).mean()
        df["roll_mean_28"] = series.shift(1).rolling(28, min_periods=1).mean()
        df["roll_max_7"]   = series.shift(1).rolling(7,  min_periods=1).max()

        # Calendar features
        if isinstance(idx, pd.DatetimeIndex):
            df["dow"]         = idx.dayofweek
            df["month"]       = idx.month
            df["dom"]         = idx.day
            df["doy"]         = idx.dayofyear
            df["is_month_end"]   = idx.is_month_end.astype(int)
            df["is_month_start"] = idx.is_month_start.astype(int)
            df["is_weekend"]     = (idx.dayofweek >= 5).astype(int)
            # Cyclical encoding — prevents ordinality bias
            df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12)
            df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12)
            df["dow_sin"]   = np.sin(2 * np.pi * df["dow"] / 7)
            df["dow_cos"]   = np.cos(2 * np.pi * df["dow"] / 7)

        df = df.ffill().fillna(0)   # FIX TD-008
        return df

    # ── External test prediction ─────────────────────────────────────
    def predict_external_test(
        self,
        model_name : str,
        train      : pd.Series,
        test_index : pd.DatetimeIndex,
    ) -> pd.Series:
        """Run a model on train and return predictions aligned to test_index."""
        dummy_test = train.iloc[-1:]
        result = self.models[model_name](train, dummy_test)
        if result is None or result.predictions_test is None:
            raise RuntimeError(f"{model_name} returned no predictions")
        # Realign to actual test dates
        preds = result.predictions_test
        if len(preds) != len(test_index):
            preds = preds.reindex(test_index).ffill().fillna(0)
        preds.index = test_index
        return preds

    # ── Fallback SMA ─────────────────────────────────────────────────
    def run_fallback_model(
        self,
        series  : pd.Series,
        horizon : Optional[int] = None,
    ) -> pd.Series:
        h = horizon or self.horizon
        # Adaptive window: FIX TD-016 — was hardcoded 14 days
        window = max(7, min(28, len(series) // 4))
        mean_val = float(series.tail(window).mean())
        future_idx = self._future_index(series.index[-1], h, series.index)
        return pd.Series([mean_val] * h, index=future_idx)

    # ════════════════════════════════════════════════════════════════
    # MODEL RUNNERS
    # ════════════════════════════════════════════════════════════════

    def _run_sma(
        self,
        train: pd.Series,
        test : Optional[pd.Series],
    ) -> ModelResult:
        """Simple Moving Average — adaptive window."""
        window   = max(7, min(28, len(train) // 4))  # FIX TD-016
        mean_val = float(train.tail(window).mean())

        test_pred = None
        if test is not None and len(test) > 0:
            test_pred = pd.Series(
                [mean_val] * len(test), index=test.index, dtype=float
            )

        future_idx = self._future_index(train.index[-1], self.horizon, train.index)
        forecast   = pd.Series([mean_val] * self.horizon, index=future_idx, dtype=float)

        return ModelResult(
            model_name="Baseline_SMA",
            model_object=None,
            wmape=0.0,
            predictions_test=test_pred,
            forecast=forecast,
        )

    # ── Linear Regression baseline (NEW) ────────────────────────────
    def _run_linear(
        self,
        train: pd.Series,
        test : pd.Series,
    ) -> Optional[ModelResult]:
        """
        NEW in v2.0: Simple OLS trend extrapolation.
        Better than SMA for trended series without seasonality.
        """
        try:
            from sklearn.linear_model import LinearRegression
            n = np.arange(len(train)).reshape(-1, 1)
            lr = LinearRegression().fit(n, train.values)

            n_test    = np.arange(len(train), len(train) + len(test)).reshape(-1, 1)
            test_pred = pd.Series(
                np.maximum(lr.predict(n_test), 0), index=test.index
            )

            n_fc  = np.arange(len(train), len(train) + self.horizon).reshape(-1, 1)
            fc    = pd.Series(
                np.maximum(lr.predict(n_fc), 0),
                index=self._future_index(train.index[-1], self.horizon, train.index),
            )
            return ModelResult("LinearBaseline", lr, 0.0, predictions_test=test_pred, forecast=fc)
        except Exception as e:
            logger.warning(f"LinearBaseline failed: {e}")
            return None

    # ── TBATS ────────────────────────────────────────────────────────
    def _run_tbats(
        self,
        train: pd.Series,
        test : pd.Series,
    ) -> Optional[ModelResult]:
        """
        FIX (TD-005): v1.0 used model.y_hat[-len(test):] which is the
        in-sample fitted values — NOT a real held-out prediction. This
        made TBATS appear artificially accurate on the test window.

        v2.0: Uses model.forecast(steps=len(test)) for a genuine
        out-of-sample prediction, then refits on full series for the
        future forecast.
        """
        try:
            from tbats import TBATS as TBATSEstimator

            sp = self.seasonal_period
            estimator = TBATSEstimator(
                seasonal_periods=[sp] if sp > 1 else None,
                use_arma_errors=True,
                use_box_cox=None,
                n_jobs=1,
            )

            # Fit on train only
            model = estimator.fit(train.values)

            # TRUE out-of-sample forecast for test window — FIX TD-005
            test_pred_vals = model.forecast(steps=len(test))
            test_pred      = pd.Series(
                np.maximum(test_pred_vals, 0), index=test.index
            )

            # Refit on full series for future horizon
            model_full = estimator.fit(
                pd.concat([train, test]).values
            )
            fc_vals  = model_full.forecast(steps=self.horizon)
            future_idx = self._future_index(
                pd.concat([train, test]).index[-1], self.horizon, train.index
            )
            forecast = pd.Series(np.maximum(fc_vals, 0), index=future_idx)

            return ModelResult("TBATS", model, 0.0, predictions_test=test_pred, forecast=forecast)
        except Exception as e:
            logger.warning(f"TBATS failed: {e}")
            return None

    # ── Prophet ──────────────────────────────────────────────────────
    def _run_prophet(
        self,
        train: pd.Series,
        test : pd.Series,
    ) -> Optional[ModelResult]:
        """
        FIX (TD-010): Seasonality is now inferred from self.freq via
        _infer_prophet_seasonality(). v1.0 always set daily_seasonality=True
        regardless of data frequency.
        """
        try:
            from prophet import Prophet

            df_train = pd.DataFrame({
                "ds": train.index,
                "y" : train.values,
            })

            seasonality_kwargs = _infer_prophet_seasonality(self.freq)  # FIX TD-010

            m = Prophet(
                changepoint_prior_scale=0.05,
                seasonality_prior_scale=10.0,
                interval_width=0.80,
                **seasonality_kwargs,
            )
            m.fit(df_train)

            # Predict test window
            future_test = pd.DataFrame({"ds": test.index})
            fc_test     = m.predict(future_test)
            test_pred   = pd.Series(
                np.maximum(fc_test["yhat"].values, 0), index=test.index
            )

            # Predict future horizon
            future_df = m.make_future_dataframe(periods=self.horizon, freq=self.freq)
            fc_future = m.predict(future_df)
            fc_future = fc_future[fc_future["ds"] > train.index[-1]].head(self.horizon)
            forecast  = pd.Series(
                np.maximum(fc_future["yhat"].values, 0),
                index=pd.DatetimeIndex(fc_future["ds"].values),
            )

            return ModelResult("Prophet", m, 0.0, predictions_test=test_pred, forecast=forecast)
        except Exception as e:
            logger.warning(f"Prophet failed: {e}")
            return None

    # ── Exponential Smoothing ─────────────────────────────────────────
    def _run_expsmoothing(
        self,
        train: pd.Series,
        test : pd.Series,
    ) -> Optional[ModelResult]:
        """
        FIX: seasonal_periods now uses self.seasonal_period (freq-derived)
        instead of the hardcoded 7 in v1.0.
        """
        try:
            from statsmodels.tsa.holtwinters import ExponentialSmoothing

            sp = self.seasonal_period
            use_seasonal = sp > 1 and len(train) >= 2 * sp

            model = ExponentialSmoothing(
                train,
                trend    ="add",
                seasonal ="add" if use_seasonal else None,
                seasonal_periods=sp if use_seasonal else None,
                initialization_method="estimated",
            ).fit(optimized=True)

            test_pred = pd.Series(
                np.maximum(model.forecast(len(test)), 0), index=test.index
            )

            # Refit on full series
            full = pd.concat([train, test])
            model_full = ExponentialSmoothing(
                full,
                trend    ="add",
                seasonal ="add" if use_seasonal else None,
                seasonal_periods=sp if use_seasonal else None,
                initialization_method="estimated",
            ).fit(optimized=True)
            forecast = pd.Series(
                np.maximum(model_full.forecast(self.horizon), 0),
                index=self._future_index(full.index[-1], self.horizon, full.index),
            )

            return ModelResult("ExpSmoothing", model, 0.0, predictions_test=test_pred, forecast=forecast)
        except Exception as e:
            logger.warning(f"ExpSmoothing failed: {e}")
            return None

    # ── SARIMAX ──────────────────────────────────────────────────────
    def _run_sarimax(
        self,
        train: pd.Series,
        test : pd.Series,
    ) -> Optional[ModelResult]:
        """
        FIX (TD-006): Uses pmdarima.auto_arima for automatic order selection.
        v1.0 hardcoded (1,1,1) which frequently underperforms.
        Falls back to (1,1,1) if auto_arima fails or times out.
        """
        try:
            import pmdarima as pm
            from statsmodels.tsa.statespace.sarimax import SARIMAX

            sp = self.seasonal_period
            use_seasonal = sp > 1 and len(train) >= 2 * sp

            try:
                auto = pm.auto_arima(
                    train,
                    seasonal=use_seasonal,
                    m=sp if use_seasonal else 1,
                    stepwise=True,
                    suppress_warnings=True,
                    error_action="ignore",
                    max_p=3, max_q=3, max_d=2,
                    max_P=2, max_Q=2,
                    information_criterion="aic",
                    n_jobs=1,
                )
                order         = auto.order
                seasonal_order = auto.seasonal_order
                logger.info(f"auto_arima selected: order={order}, seasonal={seasonal_order}")
            except Exception as ae:
                logger.warning(f"auto_arima failed ({ae}), falling back to (1,1,1)")
                order          = (1, 1, 1)
                seasonal_order = (0, 0, 0, 0)

            model = SARIMAX(
                train,
                order=order,
                seasonal_order=seasonal_order,
                enforce_stationarity=False,
                enforce_invertibility=False,
            ).fit(disp=False)

            fc_test  = model.forecast(steps=len(test))
            test_pred = pd.Series(np.maximum(fc_test, 0), index=test.index)

            model_full = SARIMAX(
                pd.concat([train, test]),
                order=order,
                seasonal_order=seasonal_order,
                enforce_stationarity=False,
                enforce_invertibility=False,
            ).fit(disp=False)

            fc_vals  = model_full.forecast(steps=self.horizon)
            forecast = pd.Series(
                np.maximum(fc_vals, 0),
                index=self._future_index(
                    pd.concat([train, test]).index[-1], self.horizon, train.index
                ),
            )

            return ModelResult("SARIMAX", model, 0.0, predictions_test=test_pred, forecast=forecast)
        except Exception as e:
            logger.warning(f"SARIMAX failed: {e}")
            return None

    # ── LightGBM ─────────────────────────────────────────────────────
    def _run_lightgbm(
        self,
        train: pd.Series,
        test : pd.Series,
    ) -> Optional[ModelResult]:
        """
        FIX (TD-007): quantile level now uses self.quantile_level
        instead of the hardcoded 0.75 constant.
        FIX (TD-008): feature engineering uses .ffill() not method='ffill'.
        """
        try:
            import lightgbm as lgb

            df = self._make_features_robust(train)
            df = df.dropna()
            feature_cols = [c for c in df.columns if c != "y"]

            X_tr = df[feature_cols].values
            y_tr = df["y"].values

            model = lgb.LGBMRegressor(
                objective      ="quantile",
                alpha          =self.quantile_level,   # FIX TD-007
                metric         ="quantile",
                n_estimators   =300,
                learning_rate  =0.05,
                num_leaves     =31,
                min_child_samples=10,
                verbose        =-1,
            )
            model.fit(X_tr, y_tr)

            # Recursive test prediction
            history     = train.copy()
            test_preds  = []
            for _ in range(len(test)):
                df_step  = self._make_features_robust(history)
                last_row = df_step[feature_cols].iloc[[-1]].values
                pred_val = max(0.0, float(model.predict(last_row)[0]))
                test_preds.append(pred_val)
                next_ts  = history.index[-1] + (history.index[-1] - history.index[-2])
                history  = pd.concat([history, pd.Series([pred_val], index=[next_ts])])

            test_pred = pd.Series(test_preds, index=test.index)

            # Recursive future forecast from full train+test
            history_full = pd.concat([train, test])
            fc_preds     = []
            for _ in range(self.horizon):
                df_step  = self._make_features_robust(history_full)
                last_row = df_step[feature_cols].iloc[[-1]].values
                pred_val = max(0.0, float(model.predict(last_row)[0]))
                fc_preds.append(pred_val)
                next_ts  = history_full.index[-1] + (history_full.index[-1] - history_full.index[-2])
                history_full = pd.concat([history_full, pd.Series([pred_val], index=[next_ts])])

            forecast = pd.Series(
                fc_preds,
                index=self._future_index(
                    pd.concat([train, test]).index[-1], self.horizon, train.index
                ),
            )
            return ModelResult("LightGBM", model, 0.0, predictions_test=test_pred, forecast=forecast)
        except Exception as e:
            logger.warning(f"LightGBM failed: {e}")
            return None

    # ── HistGradientBoosting ─────────────────────────────────────────
    def _run_hist_gb(
        self,
        train: pd.Series,
        test : pd.Series,
    ) -> Optional[ModelResult]:
        """
        FIX (TD-007): quantile level now uses self.quantile_level.
        FIX (TD-008): .ffill() used instead of method='ffill'.
        """
        try:
            from sklearn.ensemble import HistGradientBoostingRegressor

            df = self._make_features_robust(train)
            df = df.dropna()
            feature_cols = [c for c in df.columns if c != "y"]

            model = HistGradientBoostingRegressor(
                loss         ="quantile",
                quantile     =self.quantile_level,  # FIX TD-007
                max_iter     =300,
                max_depth    =8,
                learning_rate=0.05,
                random_state =42,
            )
            model.fit(df[feature_cols].values, df["y"].values)

            # Recursive test prediction
            history    = train.copy()
            test_preds = []
            for _ in range(len(test)):
                df_step  = self._make_features_robust(history)
                last_row = df_step[feature_cols].iloc[[-1]].values
                pred_val = max(0.0, float(model.predict(last_row)[0]))
                test_preds.append(pred_val)
                next_ts  = history.index[-1] + (history.index[-1] - history.index[-2])
                history  = pd.concat([history, pd.Series([pred_val], index=[next_ts])])

            test_pred = pd.Series(test_preds, index=test.index)

            # Recursive future forecast
            history_full = pd.concat([train, test])
            fc_preds     = []
            for _ in range(self.horizon):
                df_step  = self._make_features_robust(history_full)
                last_row = df_step[feature_cols].iloc[[-1]].values
                pred_val = max(0.0, float(model.predict(last_row)[0]))
                fc_preds.append(pred_val)
                next_ts  = history_full.index[-1] + (history_full.index[-1] - history_full.index[-2])
                history_full = pd.concat([history_full, pd.Series([pred_val], index=[next_ts])])

            forecast = pd.Series(
                fc_preds,
                index=self._future_index(
                    pd.concat([train, test]).index[-1], self.horizon, train.index
                ),
            )
            return ModelResult("HistGB", model, 0.0, predictions_test=test_pred, forecast=forecast)
        except Exception as e:
            logger.warning(f"HistGB failed: {e}")
            return None

    # ── Croston's Method (RE-ENABLED) ────────────────────────────────
    def _run_croston(
        self,
        train: pd.Series,
        test : pd.Series,
    ) -> Optional[ModelResult]:
        """
        RE-ENABLED (TD-009): Was implemented in v1.0 but commented out.

        Croston's Method for Intermittent/Lumpy demand.
        Separately smooths demand sizes (non-zero values) and
        inter-demand intervals, then combines to estimate average demand.

        Best suited to: ADI >= 1.32 (Intermittent / Lumpy quadrant).
        """
        try:
            alpha = 0.1  # Smoothing parameter

            # Separate demand sizes and intervals
            values    = train.values.astype(float)
            nonzero   = values[values > 0]
            intervals = []
            last_nz   = None
            for i, v in enumerate(values):
                if v > 0:
                    if last_nz is not None:
                        intervals.append(i - last_nz)
                    last_nz = i
            intervals = np.array(intervals) if intervals else np.array([1.0])

            if len(nonzero) == 0:
                # All-zero series — return zero forecast
                test_pred = pd.Series([0.0] * len(test), index=test.index)
                forecast  = pd.Series(
                    [0.0] * self.horizon,
                    index=self._future_index(train.index[-1], self.horizon, train.index),
                )
                return ModelResult("Croston", None, 0.0, predictions_test=test_pred, forecast=forecast)

            # Smooth demand sizes
            d_smooth = nonzero[0]
            for d in nonzero[1:]:
                d_smooth = alpha * d + (1 - alpha) * d_smooth

            # Smooth intervals
            p_smooth = float(np.mean(intervals))
            for p in intervals[1:]:
                p_smooth = alpha * p + (1 - alpha) * p_smooth

            # Croston forecast: average demand per period
            avg_demand = d_smooth / max(p_smooth, 1.0)
            avg_demand = max(0.0, avg_demand)

            test_pred = pd.Series([avg_demand] * len(test), index=test.index)
            forecast  = pd.Series(
                [avg_demand] * self.horizon,
                index=self._future_index(train.index[-1], self.horizon, train.index),
            )

            return ModelResult("Croston", None, 0.0, predictions_test=test_pred, forecast=forecast)
        except Exception as e:
            logger.warning(f"Croston failed: {e}")
            return None

    # ── Theta Method (NEW) ───────────────────────────────────────────
    def _run_theta(
        self,
        train: pd.Series,
        test : pd.Series,
    ) -> Optional[ModelResult]:
        """
        NEW in v2.0: The Theta Method (Assimakopoulos & Nikolopoulos, 2000).

        Won the M3 forecasting competition. Decomposes series into:
          - Theta=0 line (linear regression — trend component)
          - Theta=2 line (double exponential smoothing — short-term dynamics)
        and averages their forecasts.

        Excellent benchmark for smooth and erratic demand; consistently
        outperforms ARIMA on M3/M4 benchmarks.
        """
        try:
            from statsmodels.tsa.holtwinters import SimpleExpSmoothing

            n = len(train)
            t = np.arange(1, n + 1, dtype=float)

            # Theta=0: pure linear regression trend
            coeffs   = np.polyfit(t, train.values, 1)
            slope, intercept = coeffs
            t_future_test = np.arange(n + 1, n + len(test) + 1, dtype=float)
            theta0_test   = slope * t_future_test + intercept

            # Theta=2: double exponential smoothing
            ses = SimpleExpSmoothing(train.values, initialization_method="estimated").fit(
                optimized=True
            )
            # Forecast test window
            theta2_test = ses.forecast(len(test))

            # Average the two theta lines
            test_pred_vals = np.maximum(
                (theta0_test + theta2_test) / 2.0, 0
            )
            test_pred = pd.Series(test_pred_vals, index=test.index)

            # Refit on train + test for future horizon
            full  = pd.concat([train, test])
            n_full = len(full)
            t_full = np.arange(1, n_full + 1, dtype=float)
            coeffs_full    = np.polyfit(t_full, full.values, 1)
            slope_f, int_f = coeffs_full

            t_fc    = np.arange(n_full + 1, n_full + self.horizon + 1, dtype=float)
            theta0_fc = slope_f * t_fc + int_f

            ses_full  = SimpleExpSmoothing(full.values, initialization_method="estimated").fit(
                optimized=True
            )
            theta2_fc = ses_full.forecast(self.horizon)

            fc_vals  = np.maximum((theta0_fc + theta2_fc) / 2.0, 0)
            forecast = pd.Series(
                fc_vals,
                index=self._future_index(full.index[-1], self.horizon, full.index),
            )

            return ModelResult("Theta", None, 0.0, predictions_test=test_pred, forecast=forecast)
        except Exception as e:
            logger.warning(f"Theta failed: {e}")
            return None

    # ════════════════════════════════════════════════════════════════
    # DEMAND-AWARE MODEL SELECTION
    # ════════════════════════════════════════════════════════════════

    def get_models_for_demand_type(
        self,
        demand_profile,           # DemandProfile from metrics.py
        mean_val   : float,
        zero_ratio : float,
        cv         : float,
        n_points   : int,
    ) -> Dict[str, Callable]:
        """
        NEW in v2.0: Returns an ordered dict of models appropriate for
        the given demand profile and series characteristics.

        FIX (TD-009): v1.0 computed demand type but never used it for routing.
        Now demand type drives which models are included and their priority order.

        Also incorporates the existing gating logic from processing_engine.py.
        """
        # Start from demand profile's recommended order
        preferred = demand_profile.recommended_models

        # Build candidate dict in preferred order
        candidates = {}
        for name in preferred:
            if name in self.models:
                candidates[name] = self.models[name]

        # Add any non-preferred models not already in candidates
        for name, fn in self.models.items():
            if name not in candidates:
                candidates[name] = fn

        # ── Gating rules (preserved from v1.0, now applied post-routing) ──
        to_remove = set()

        if mean_val < 10:
            to_remove |= {"Prophet", "SARIMAX"}

        if zero_ratio > 0.80:
            to_remove.add("Prophet")

        if cv > 1.5:
            to_remove.add("SARIMAX")

        if n_points < 90 or (zero_ratio > 0.70 and mean_val < 5):
            # Sparse fallback — only keep Croston and SMA-family
            return {}   # caller switches to run_fallback_model

        # Croston only relevant for intermittent/lumpy
        if not demand_profile.is_intermittent:
            to_remove.add("Croston")

        # Theta is poor on very short series
        if n_points < 30:
            to_remove.add("Theta")

        # Linear is poor on purely seasonal data
        if demand_profile.demand_type == "Smooth" and self.seasonal_period > 1:
            to_remove.add("LinearBaseline")

        filtered = {k: v for k, v in candidates.items() if k not in to_remove}
        return filtered