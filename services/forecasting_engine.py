from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Any, Dict, Tuple, Optional
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
import lightgbm as lgb
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.tsa.statespace.sarimax import SARIMAX

from prophet import Prophet
from tbats import TBATS
from utils.metrics import wmape, trend_error, variance_penalty

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

@dataclass
class ModelResult:
    name: str
    wmape: float
    model_obj: Any
    forecast: pd.Series
    predictions_test: pd.Series

class ForecastingEngine:
    def __init__(self, freq: str = "D", horizon: int = 60, test_size: int = 30):
        self.freq = freq
        self.horizon = horizon
        self.test_size = test_size
        self.models = {
            "TBATS": self._run_tbats,
            "Prophet": self._run_prophet,
            "LightGBM": self._run_lightgbm,
            "HistGB": self._run_hist_gb,
            "ExpSmoothing": self._run_expsmoothing,
            "SARIMAX": self._run_sarimax,
            # "Croston": self._run_croston,
        }

    def _safe_infer_freq(self, index):
        freq = pd.infer_freq(index)
        if freq:
            return freq
        # fallback using median 
        deltas = index.to_series().diff().dropna()
        median_days = deltas.median().days
        if median_days >= 28:
            return "M"
        if median_days >= 7:
            return "W"
        return "D"

    def _infer_offset(self, freq_or_offset):
        try:
            return pd.tseries.frequencies.to_offset(freq_or_offset)
        except Exception:
            try:
                return pd.tseries.frequencies.to_offset(self.freq)
            except Exception:
                return pd.tseries.frequencies.to_offset("D")
    
    def _run_sma(self, train, test=None):
        """
        Simple Moving Average Runner.
        Calculates baseline (mean of last 14 days), returns ModelResult.
        """
        window = 14
        if len(train) >= window:
            val = float(train.tail(window).mean())
        else:
            val = float(train.mean())
        
        if pd.isna(val): 
            val = 0.0

        # Test Predictions
        preds_test = pd.Series(dtype=float)
        w = None
        
        if test is not None:
            preds_test = pd.Series([val] * len(test), index=test.index)
            w = wmape(test, preds_test)

        # Future Forecast
        future_steps = self.horizon
        future_idx = self._future_index(train.index.max(), future_steps, train.index)
        future_pred = pd.Series([val] * len(future_idx), index=future_idx)

        return ModelResult("Baseline_SMA", w, None, future_pred, preds_test)

    def _croston_forecast(self, series: pd.Series, horizon: int, alpha: float = 0.3) -> pd.Series:
        try:
            y = series.values
            n = len(y)
            nonzero_indices = np.where(y > 0)[0]
            
            if len(nonzero_indices) == 0:
                pred = 0.0
            else:
                first_idx = nonzero_indices[0]
                z = y[first_idx]
                p = float(first_idx + 1)
                q = 0
                
                for i in range(first_idx + 1, n):
                    val = y[i]
                    q += 1 
                    if val > 0:
                        z = alpha * val + (1 - alpha) * z
                        p = alpha * q + (1 - alpha) * p
                        q = 0
                pred = z / p

            last_idx = series.index.max()
            future_idx = self._future_index(last_idx, horizon, series.index)
            return pd.Series([pred] * len(future_idx), index=future_idx)
            
        except Exception as e:
            logger.error(f"Croston forecast failed: {e}")
            res = self._run_sma(series, None)
            return res.forecast

    def run_fallback_model(self, train_series: pd.Series, horizon: Optional[int] = None) -> pd.Series:
        """
        Fallback Model defaults strictly to SMA.
        """
        res = self._run_sma(train_series, None)
        
        forecast = res.forecast
        if horizon is not None:
            return forecast.head(horizon)
        return forecast
        
    def _future_index(self, start, steps, index=None):
        freq = self._safe_infer_freq(index) if index is not None else self.freq
        offset = self._infer_offset(freq)
        return pd.date_range(start=start + offset, periods=steps, freq=offset)
    
    def _run_croston(self, train, test):
        preds_test = self._croston_forecast(train, len(test))
        preds_test.index = test.index
        
        w = wmape(test, preds_test)
        future_steps = self.horizon
        future_pred = self._croston_forecast(train, future_steps)
        
        return ModelResult("Croston", w, None, future_pred, preds_test)


    def _train_test_split(self, series: pd.Series) -> Tuple[pd.Series, pd.Series]:
        if not isinstance(series.index, pd.DatetimeIndex):
            raise ValueError("series index must be DatetimeIndex")
        n = len(series)
        if n < 15:
            raise ValueError("series too short for train/test split")
            
        test_size = int(round(n * 0.2))
        test_size = max(7, test_size)
        test_size = min(self.test_size, test_size) 
        
        if n - test_size < 5:
            test_size = max(7, n - 5)
        if test_size <= 0 or test_size >= n:
            raise ValueError("invalid train/test split size")
            
        train = series.iloc[:-test_size]
        test = series.iloc[-test_size:]
        return train, test
    
    def predict_external_test(
        self,
        model_name: str,
        train_series: pd.Series,
        test_index: pd.DatetimeIndex
    ) -> pd.Series:

        if model_name not in self.models:
            raise ValueError(f"Unknown model {model_name}")

        runner = self.models[model_name]
        dummy_test = pd.Series(index=test_index, dtype=float)
        res = runner(train_series, dummy_test)
        preds = res.predictions_test
        preds = preds.reindex(test_index)

        return preds.clip(lower=0.0)

    def _make_features_robust(self, history_series: pd.Series, target_idx: pd.Index) -> pd.DataFrame:
        full_idx = history_series.index.union(target_idx).sort_values()
        
        temp_df = pd.DataFrame(index=full_idx)
        temp_df = temp_df.join(history_series.rename("y"), how="left")
        temp_df.loc[target_idx, "y"] = np.nan

        lags = [1, 2, 3, 7, 14, 21, 28]
        for lag in lags:
            temp_df[f"lag_{lag}"] = temp_df["y"].shift(lag)
            
        temp_df["roll_mean_7"] = temp_df["y"].shift(1).rolling(7).mean()
        temp_df["roll_std_7"] = temp_df["y"].shift(1).rolling(7).std()

        temp_df["dow"] = temp_df.index.dayofweek
        temp_df["dom"] = temp_df.index.day
        temp_df["month"] = temp_df.index.month
        temp_df["is_month_end"] = temp_df.index.is_month_end.astype(int)
        temp_df["is_month_start"] = temp_df.index.is_month_start.astype(int)

        res = temp_df.loc[target_idx].drop(columns=["y"])
        return res.fillna(method="ffill").fillna(0)

    # Model Runners
    def _run_tbats(self, train, test):
        full_series = train
        estimator = TBATS(use_arma_errors=False, n_jobs=1, seasonal_periods=[7], show_warnings=False)
        model = estimator.fit(full_series.values)
        preds_test = pd.Series(model.y_hat[-len(test):], index=test.index)
        w = wmape(test.values, preds_test.values)

        future_steps = self.horizon
        future_pred = pd.Series(
            model.forecast(steps=future_steps),
            index=self._future_index(train.index.max(), future_steps, train.index)
        )
        return ModelResult("TBATS", w, model, future_pred, preds_test)

    def _run_prophet(self, train, test):
        if Prophet is None:
            raise RuntimeError("Prophet not installed")
        df_train = pd.DataFrame({"ds": train.index, "y": train.values})
        m = Prophet(daily_seasonality=True, weekly_seasonality=True, yearly_seasonality=False)
        m.fit(df_train)
        preds_test = pd.Series(m.predict(pd.DataFrame({"ds": test.index}))["yhat"].values, index=test.index)
        w = wmape(test, preds_test)


        future_steps = self.horizon
        future_idx = self._future_index(train.index.max(), future_steps, train.index)
        future_series = pd.Series(
            m.predict(pd.DataFrame({"ds": future_idx}))["yhat"].values, 
            index=future_idx
        )
        return ModelResult("Prophet", w, m, future_series, preds_test)
    
    QUANTILE_LEVEL = 0.75

    def _run_lightgbm(self, train, test):
        series = train.copy()
        X_train = self._make_features_robust(series, series.index)
        y_train = series.values
        
        model = lgb.LGBMRegressor(
            n_estimators=500,
            learning_rate=0.05,
            num_leaves=31,
            max_depth=10,
            min_child_samples=10,
            objective='quantile',        
            alpha=self.QUANTILE_LEVEL,   
            metric='quantile',           
            random_state=42,
            verbose=-1,
        )
        model.fit(X_train, y_train)

        history_test = series.copy()
        test_preds = []
        for dt in test.index:
            X_next = self._make_features_robust(history_test, pd.DatetimeIndex([dt]))
            y_hat = max(0.0, model.predict(X_next)[0])
            test_preds.append(y_hat)
            history_test.loc[dt] = y_hat

        preds_test = pd.Series(test_preds, index=test.index)
        w = wmape(test, preds_test)

        # Recursive Forecast
        future_steps = self.horizon
        future_idx = self._future_index(train.index.max(), future_steps, train.index)
        history = series.copy()
        future_vals = []
        for dt in future_idx:
            X_next = self._make_features_robust(history, pd.DatetimeIndex([dt]))
            y_hat = max(0.0, model.predict(X_next)[0])
            future_vals.append(y_hat)
            history.loc[dt] = y_hat

        future_preds = pd.Series(future_vals, index=future_idx)
        return ModelResult("LightGBM", w, model, future_preds, preds_test)

    def _run_hist_gb(self, train, test):
        series = train.copy()
        X_train = self._make_features_robust(series, series.index)
        y_train = series.values

        model = HistGradientBoostingRegressor(
            loss='quantile',             
            quantile=self.QUANTILE_LEVEL,
            max_depth=12,
            learning_rate=0.05,
            max_iter=400,
            min_samples_leaf=5,
            random_state=42,
        )
        model.fit(X_train, y_train)

        # Recursive Test
        history_test = series.copy()
        test_preds = []
        for dt in test.index:
            X_next = self._make_features_robust(history_test, pd.DatetimeIndex([dt]))
            y_hat = max(0.0, model.predict(X_next)[0])
            test_preds.append(y_hat)
            history_test.loc[dt] = y_hat

        preds_test = pd.Series(test_preds, index=test.index)
        w = wmape(test, preds_test)

        # Recursive Forecast
        future_steps = self.horizon
        future_idx = self._future_index(train.index.max(), future_steps, train.index)
        history = series.copy()
        future_vals = []
        for dt in future_idx:
            X_next = self._make_features_robust(history, pd.DatetimeIndex([dt]))
            y_hat = max(0.0, model.predict(X_next)[0])
            future_vals.append(y_hat)
            history.loc[dt] = y_hat

        future_preds = pd.Series(future_vals, index=future_idx)
        return ModelResult("HistGB", w, model, future_preds, preds_test)

    def _run_expsmoothing(self, train, test):
        full_series = train
        seasonal = 7 if len(full_series) > 14 else None
        model = ExponentialSmoothing(
            full_series,
            trend="add",
            seasonal="add" if seasonal else None,
            seasonal_periods=seasonal,
        )
        fitted = model.fit(optimized=True)
        preds_test = pd.Series(
            fitted.predict(start=test.index[0], end=test.index[-1]), 
            index=test.index
        )
        w = wmape(test, preds_test)

        future_steps = self.horizon
        future_idx = self._future_index(train.index.max(), future_steps, train.index)
        future_pred = pd.Series(
            fitted.forecast(future_steps), 
            index=future_idx
        )
        return ModelResult("ExpSmoothing", w, fitted, future_pred, preds_test)

    def _run_sarimax(self, train, test):
        order = (1, 1, 1)
        seasonal_period = 7 if self.freq.lower().startswith("d") else 4 if "w" in self.freq else 12
        seasonal_order = (0, 1, 1, seasonal_period)
        full_series = train
        model = SARIMAX(
            full_series, 
            order=order, 
            seasonal_order=seasonal_order, 
            enforce_stationarity=False, 
            enforce_invertibility=False
        )
        fitted = model.fit(disp=False)
        preds_test = pd.Series(
            fitted.get_prediction(
                start=test.index[0], 
                end=test.index[-1], 
                dynamic=False
            ).predicted_mean, 
            index=test.index
        )
        w = wmape(test, preds_test)


        future_steps = self.horizon
        future_idx = self._future_index(train.index.max(), future_steps, train.index)
        future_pred = pd.Series(
            fitted.get_forecast(steps=future_steps).predicted_mean, 
            index=future_idx
        )
        return ModelResult("SARIMAX", w, fitted, future_pred, preds_test)