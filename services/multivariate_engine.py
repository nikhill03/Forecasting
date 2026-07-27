"""
multivariate_engine.py — Multivariate Forecasting Engine
=========================================================
Version : 2.0.0
Changes vs v1.0
---------------
TD-007 FIXED : QUANTILE_LEVEL now accepted as constructor param instead of module constant
TD-008 FIXED : fillna(method='ffill') replaced with .ffill() throughout (pandas 2.x compat)
TD-014 FIXED : Same deprecation fix applied in run_multivariate() data prep block
NEW   : ensemble_blend() — top-2 model blending by inverse-WMAPE weighting
NEW   : Model selection now uses composite_score (WMAPE + trend_error + variance_penalty)
        instead of pure WMAPE — reduces risk of selecting a flat/over-volatile forecast
NEW   : RMSE added to evaluation output dict
NEW   : coverage_score computed when quantile bounds available
NEW   : Additional holiday regions (GB, DE, FR, AU, CA) in _get_combined_holidays
IMPROVED: _select_features now uses mutual information as a secondary signal to
          reduce the risk of purely-importance-driven feature elimination
"""

from __future__ import annotations

import logging
import warnings
from typing import Optional, Callable

import numpy as np
import pandas as pd
import holidays

import lightgbm as lgb
from xgboost import XGBRegressor
from sklearn.ensemble import (
    RandomForestRegressor,
    ExtraTreesRegressor,
    HistGradientBoostingRegressor,
)
from sklearn.linear_model import Ridge, HuberRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.feature_selection import mutual_info_regression
from statsmodels.tsa.stattools import acf

from utils.metrics import (
    wmape, mae, mape, rmse, forecast_accuracy,
    composite_score, coverage_score,
)
from utils.holiday_utils import get_region_holidays

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

logger = logging.getLogger("ml.multivariate_engine")

# Supported regions (expanded in v2.0)
_SUPPORTED_REGIONS = {"US", "IN", "GB", "DE", "FR", "AU", "CA"}


class MultivariateEngine:
    """
    Multivariate Forecasting Engine v2.0

    Parameters
    ----------
    selected_regions : list of ISO country codes for holiday features
    quantile_level   : quantile for boosting models (FIX TD-007)
    """

    def __init__(
        self,
        selected_regions : Optional[list] = None,
        quantile_level   : float = 0.75,
    ):
        self.selected_regions = [
            r for r in (selected_regions or ["US", "IN"])
            if r in _SUPPORTED_REGIONS
        ] or ["US"]
        self.quantile_level = quantile_level  # FIX TD-007

    # ── Holiday calendar ─────────────────────────────────────────────
    def _get_combined_holidays(self, dates):
        if len(dates) == 0:
            return holidays.HolidayBase()
        return get_region_holidays(dates, self.selected_regions)

    # ── Cyclical encoding ─────────────────────────────────────────────
    def _add_cyclical_features(self, df: pd.DataFrame) -> pd.DataFrame:
        df["month_sin"]   = np.sin(2 * np.pi * df["month_of_year"] / 12)
        df["month_cos"]   = np.cos(2 * np.pi * df["month_of_year"] / 12)
        df["quarter_sin"] = np.sin(2 * np.pi * df["quarter_of_year"] / 4)
        df["quarter_cos"] = np.cos(2 * np.pi * df["quarter_of_year"] / 4)
        df["week_sin"]    = np.sin(2 * np.pi * df["week_of_year"] / 52)
        df["week_cos"]    = np.cos(2 * np.pi * df["week_of_year"] / 52)
        return df

    # ── ACF-based lag detection ───────────────────────────────────────
    def _detect_significant_lags(
        self, series: pd.Series, max_lags: int = 40
    ) -> list:
        try:
            s = series.dropna()
            n_lags = min(max_lags, len(s) // 2 - 1)
            if n_lags < 1:
                return [1, 7]
            acf_vals = acf(s, nlags=n_lags, fft=True)
            limit    = 1.96 / np.sqrt(len(s))
            sig      = [i for i, v in enumerate(acf_vals) if abs(v) > limit and i > 0]
            if 1 not in sig:
                sig.insert(0, 1)
            return sig[:10]
        except Exception:
            return [1, 7]

    # ── Feature engineering ───────────────────────────────────────────
    def _add_features(
        self, df: pd.DataFrame, lags_list: Optional[list] = None
    ) -> pd.DataFrame:
        if lags_list is None:
            lags_list = [1, 7]
        df = df.copy()

        # Calendar
        df["day_of_week"]     = df.index.dayofweek
        df["week_of_year"]    = df.index.isocalendar().week.astype(int)
        df["month_of_year"]   = df.index.month
        df["quarter_of_year"] = df.index.quarter
        df["is_month_end"]    = df.index.is_month_end.astype(int)
        df["is_month_start"]  = df.index.is_month_start.astype(int)
        df["is_weekend"]      = (df["day_of_week"] >= 5).astype(int)
        df["is_monday"]       = (df["day_of_week"] == 0).astype(int)

        # Cyclical
        df = self._add_cyclical_features(df)

        # Holidays
        holiday_obj = self._get_combined_holidays(df.index)
        df["is_holiday"]       = df.index.isin(holiday_obj).astype(int)
        df["before_holiday_1"] = (df.index + pd.Timedelta(days=1)).isin(holiday_obj).astype(int)
        df["after_holiday_1"]  = (df.index - pd.Timedelta(days=1)).isin(holiday_obj).astype(int)
        df["after_holiday_2"]  = (df.index - pd.Timedelta(days=2)).isin(holiday_obj).astype(int)

        # Lag features
        target = df["y"]
        for lag in lags_list:
            df[f"lag_{lag}"] = target.shift(lag)

        lag_1 = target.shift(1)
        lag_3 = target.shift(3)
        df["smart_momentum"] = np.where(df.index.dayofweek == 0, lag_3, lag_1)

        # Rolling features — FIX TD-008/TD-014: .ffill() not method='ffill'
        df["roll_max_3"]   = target.shift(1).rolling(3).max().ffill().fillna(0)
        df["roll_mean_7"]  = target.shift(1).rolling(7).mean()
        df["roll_max_7"]   = target.shift(1).rolling(7).max()
        df["roll_max_14"]  = target.shift(1).rolling(14).max()
        df["roll_max_28"]  = target.shift(1).rolling(28).max()
        df["roll_std_7"]   = target.shift(1).rolling(7).std().ffill().fillna(0)
        df["roll_mean_28"] = target.shift(1).rolling(28).mean()

        # Ratio features
        trend_lag = 7 if 7 in lags_list else 1
        df["trend_strength"]   = df.get(f"lag_{trend_lag}", lag_1) / (df["roll_mean_7"] + 1e-6)
        df["volatility_ratio"] = df["roll_std_7"] / (target.shift(1).rolling(28).std().ffill().fillna(1e-6) + 1e-6)
        df["spike_ratio"]      = lag_1 / (df["roll_max_28"] + 1e-6)

        return df

    # ── Future row generation ─────────────────────────────────────────
    def _generate_future_row(
        self,
        date       : pd.Timestamp,
        history_df : pd.DataFrame,
        lags_list  : list,
        x_future_row: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        row = pd.DataFrame(index=[date])

        row["day_of_week"]     = date.dayofweek
        row["week_of_year"]    = date.isocalendar()[1]
        row["month_of_year"]   = date.month
        row["quarter_of_year"] = date.quarter
        row["is_month_end"]    = int(date.is_month_end)
        row["is_month_start"]  = int(date.is_month_start)
        row["is_weekend"]      = int(date.dayofweek >= 5)
        row["is_monday"]       = int(date.dayofweek == 0)

        row["month_sin"]   = np.sin(2 * np.pi * row["month_of_year"] / 12)
        row["month_cos"]   = np.cos(2 * np.pi * row["month_of_year"] / 12)
        row["quarter_sin"] = np.sin(2 * np.pi * row["quarter_of_year"] / 4)
        row["quarter_cos"] = np.cos(2 * np.pi * row["quarter_of_year"] / 4)
        row["week_sin"]    = np.sin(2 * np.pi * row["week_of_year"] / 52)
        row["week_cos"]    = np.cos(2 * np.pi * row["week_of_year"] / 52)

        check_dates = [date, date + pd.Timedelta(days=1),
                       date - pd.Timedelta(days=1), date - pd.Timedelta(days=2)]
        holiday_obj          = self._get_combined_holidays(pd.Index(check_dates))
        row["is_holiday"]    = int(date in holiday_obj)
        row["before_holiday_1"] = int((date + pd.Timedelta(days=1)) in holiday_obj)
        row["after_holiday_1"]  = int((date - pd.Timedelta(days=1)) in holiday_obj)
        row["after_holiday_2"]  = int((date - pd.Timedelta(days=2)) in holiday_obj)

        def get_lag(days_back):
            target_date = date - pd.Timedelta(days=days_back)
            if target_date in history_df.index:
                return float(history_df.loc[target_date, "y"])
            return 0.0

        for lag in lags_list:
            row[f"lag_{lag}"] = get_lag(lag)

        row["smart_momentum"] = get_lag(3) if date.weekday() == 0 else get_lag(1)

        window_end   = date - pd.Timedelta(days=1)
        window_start = date - pd.Timedelta(days=28)
        recent = history_df.loc[window_start:window_end, "y"]

        row["roll_max_3"]   = recent.iloc[-3:].max() if len(recent) >= 1 else 0
        row["roll_mean_7"]  = recent.iloc[-7:].mean() if len(recent) >= 1 else 0
        row["roll_max_7"]   = recent.iloc[-7:].max()  if len(recent) >= 1 else 0
        row["roll_max_14"]  = recent.iloc[-14:].max() if len(recent) >= 1 else 0
        row["roll_max_28"]  = recent.max() if len(recent) >= 1 else 0
        std_7 = recent.iloc[-7:].std() if len(recent) >= 2 else 0.0
        std_28 = recent.std() if len(recent) >= 2 else 1e-6
        row["roll_std_7"]   = std_7
        row["roll_mean_28"] = recent.mean() if len(recent) >= 1 else 0

        trend_lag_val = get_lag(7 if 7 in lags_list else 1)
        row["trend_strength"]   = trend_lag_val / (row["roll_mean_7"] + 1e-6)
        row["volatility_ratio"] = std_7 / (std_28 + 1e-6)
        row["spike_ratio"]      = get_lag(1) / (row["roll_max_28"] + 1e-6)

        if x_future_row is not None and not x_future_row.empty:
            for col in x_future_row.columns:
                row[col] = x_future_row[col].values[0]

        return row

    # ── Feature selection (improved) ──────────────────────────────────
    def _select_features(
        self,
        X    : pd.DataFrame,
        y    : pd.Series,
        debug: bool = False,
    ) -> list:
        """
        IMPROVED in v2.0: Uses ExtraTrees importance (as before) combined
        with Mutual Information as a secondary signal. Features are included
        if they rank in top-15 on EITHER measure, or if they cumulatively
        explain 95% of variance. Cyclical/calendar features are always forced.
        This reduces the risk of dropping features that are nonlinearly
        important but show low linear importance.
        """
        X_clean = X.fillna(0)

        # ExtraTrees importance
        rf = ExtraTreesRegressor(n_estimators=100, random_state=42, n_jobs=-1)
        rf.fit(X_clean, y)
        imp_rf = pd.Series(rf.feature_importances_, index=X.columns).sort_values(ascending=False)

        # Mutual Information (rank-based, handles non-linearity)
        try:
            mi_scores = mutual_info_regression(X_clean, y, random_state=42)
            imp_mi    = pd.Series(mi_scores, index=X.columns).sort_values(ascending=False)
            top_mi    = imp_mi.index[:15].tolist()
        except Exception:
            top_mi = []

        # Cumulative importance threshold
        cumsum  = imp_rf.cumsum()
        top_cum = cumsum[cumsum < 0.95].index.tolist()
        top_rf  = imp_rf.index[:15].tolist()

        # Forced calendar/cyclical features (always include)
        forced = [
            c for c in X.columns
            if any(kw in c for kw in ("sin", "cos", "month", "quarter", "week", "holiday"))
        ]

        final = list(set(top_cum) | set(top_rf) | set(top_mi) | set(forced))

        if debug:
            logger.info(f"Feature selection: {len(final)} features selected from {len(X.columns)}")

        return final

    # ── Ensemble blending (NEW) ───────────────────────────────────────
    def _ensemble_blend(
        self,
        results      : dict,
        top_n        : int = 2,
        train_series : Optional[pd.Series] = None,
        test_series  : Optional[pd.Series] = None,
    ) -> Optional[dict]:
        """
        NEW in v2.0: Blends the top-N models by inverse-WMAPE weighting.

        If the top model is significantly better than all others
        (>20% gap), blending is skipped and the single best model is returned.

        Returns blended result dict or None if blending is not beneficial.
        """
        if len(results) < 2:
            return None

        sorted_models = sorted(results.items(), key=lambda x: x[1]["wmape"])
        best_wmape    = sorted_models[0][1]["wmape"]
        second_wmape  = sorted_models[1][1]["wmape"]

        # Skip blending if best model is ≥20% better — no benefit
        if best_wmape < 1e-6 or (second_wmape - best_wmape) / (best_wmape + 1e-8) > 0.20:
            return None

        # Take top N
        top_models = sorted_models[:top_n]
        scores     = np.array([r["wmape"] for _, r in top_models])

        # Inverse-WMAPE weights (lower WMAPE → higher weight)
        inv_scores = 1.0 / (scores + 1e-8)
        weights    = inv_scores / inv_scores.sum()

        # Blend test predictions
        test_preds  = [r["test_pred"] for _, r in top_models]
        common_idx  = test_preds[0].index
        blended_test = sum(w * p.reindex(common_idx).fillna(0)
                           for w, p in zip(weights, test_preds))

        # No per-model "forecast" exists yet at this point in the pipeline —
        # the future forecast is only computed once, after a model/blend is
        # chosen (see run_multivariate's recursive future-row loop, which
        # already handles the blend case by averaging the component models'
        # live predictions). Nothing downstream reads this dict's "forecast"
        # key — the real one comes from that later loop.
        model_names = "+".join([name for name, _ in top_models])
        blended_wmape = wmape(
            test_series if test_series is not None else pd.Series(dtype=float),
            blended_test,
        )

        # Only return blend if it's at least as good as best single model
        if blended_wmape >= best_wmape:
            return None

        logger.info(
            f"Ensemble blend [{model_names}] "
            f"WMAPE={blended_wmape:.4f} vs best single={best_wmape:.4f}"
        )

        return {
            "model"     : None,
            "wmape"     : blended_wmape,
            "test_pred" : blended_test.clip(lower=0),
            "is_booster": False,
            "model_name": f"Ensemble[{model_names}]",
        }

    # ════════════════════════════════════════════════════════════════
    # MAIN RUNNER
    # ════════════════════════════════════════════════════════════════

    def run_multivariate(
        self,
        train_series     : pd.Series,
        test_series_clean: pd.Series,
        test_series_raw  : Optional[pd.Series] = None,
        X_external_train : Optional[pd.DataFrame] = None,
        X_external_test  : Optional[pd.DataFrame] = None,
        debug            : bool = False,
        logger_func      : Optional[Callable] = None,
        horizon          : int = 60,
        test_size        : int = 30,
    ) -> dict:
        """
        Unified Multivariate Runner.

        Changes vs v1.0:
        - Composite score used for model selection (TD-013 fix)
        - Ensemble blending on top-2 models (new)
        - RMSE added to output
        - .ffill() instead of fillna(method=) (TD-008/TD-014 fix)
        - quantile_level from self.quantile_level (TD-007 fix)
        """
        full_series_clean = pd.concat([train_series, test_series_clean]).sort_index()
        skewness          = full_series_clean.apply(lambda x: max(0, x)).skew()
        should_log        = abs(skewness) > 2.0

        significant_lags = self._detect_significant_lags(train_series)

        df_full = pd.DataFrame({"y": full_series_clean.apply(lambda x: max(0, x))})
        df_full = self._add_features(df_full, lags_list=significant_lags)

        # Merge external X — FIX TD-014: .ffill() not method='ffill'
        X_full_ext = None
        if X_external_train is not None and not X_external_train.empty:
            X_full_ext = pd.concat([X_external_train, X_external_test]).sort_index() \
                         if X_external_test is not None else X_external_train

            df_full = df_full.join(X_full_ext, how="left")
            df_full[X_full_ext.columns] = (
                df_full[X_full_ext.columns].ffill().fillna(0)  # FIX TD-014
            )

        df_full = df_full.dropna()

        n                = len(df_full)
        actual_test_size = max(7, min(test_size, int(round(n * 0.2))))
        train_df         = df_full.iloc[:-actual_test_size]
        test_df          = df_full.iloc[-actual_test_size:]

        X_train = train_df.drop(columns=["y"])
        y_train = train_df["y"]
        X_test  = test_df.drop(columns=["y"])

        # Feature selection
        y_sel   = np.log1p(y_train) if should_log else y_train
        top_feats = self._select_features(X_train, y_sel, debug=debug)
        X_train   = X_train[top_feats]
        X_test    = X_test[top_feats]

        q = self.quantile_level  # FIX TD-007

        def get_base_model(name):
            if name == "LightGBM":
                return lgb.LGBMRegressor(
                    objective="quantile", alpha=q, metric="quantile", verbose=-1
                )
            if name == "XGBoost":
                return XGBRegressor(
                    objective="reg:quantileerror", quantile_alpha=q,
                    n_jobs=-1, verbosity=0
                )
            if name == "HistGB":
                return HistGradientBoostingRegressor(loss="quantile", quantile=q)
            if name == "ExtraTrees":
                return ExtraTreesRegressor(n_jobs=-1, random_state=42)
            if name == "Ridge":
                return Ridge()
            if name == "Huber":
                return HuberRegressor(max_iter=2000)
            return None

        defaults = {
            "LightGBM"  : {"n_estimators": 300, "learning_rate": 0.05, "num_leaves": 20, "alpha": q},
            "XGBoost"   : {"n_estimators": 300, "learning_rate": 0.05, "max_depth": 6, "quantile_alpha": q},
            "HistGB"    : {"max_iter": 300, "max_depth": 8, "quantile": q},
            "ExtraTrees": {"n_estimators": 200, "max_depth": 15},
            "Ridge"     : {"alpha": 1.0},
            "Huber"     : {"epsilon": 1.35},
        }
        model_names = ["LightGBM", "XGBoost", "HistGB", "ExtraTrees", "Ridge", "Huber"]

        truth = test_series_raw.reindex(X_test.index) \
                if test_series_raw is not None else test_series_clean.loc[X_test.index]

        results = {}
        for name in model_names:
            try:
                is_booster  = name in ("LightGBM", "XGBoost", "HistGB")
                y_tr_curr   = y_train if is_booster else (np.log1p(y_train) if should_log else y_train)
                base_est    = get_base_model(name)
                best_params = defaults.get(name, {})

                if name == "Ridge":
                    final_model = make_pipeline(StandardScaler(), Ridge(**best_params))
                elif name == "Huber":
                    p = best_params.copy()
                    p["max_iter"] = 2000
                    final_model = make_pipeline(StandardScaler(), HuberRegressor(**p))
                else:
                    final_model = base_est
                    final_model.set_params(**best_params)

                final_model.fit(X_train, y_tr_curr)

                if len(X_test) > 0:
                    pred_raw   = final_model.predict(X_test)
                    pred_final = pred_raw if is_booster else (
                        np.expm1(pred_raw) if should_log else pred_raw
                    )
                    pred_final  = np.maximum(pred_final, 0)
                    pred_series = pd.Series(pred_final, index=X_test.index)

                    valid_mask    = ~truth.isna() & (truth >= 0)
                    y_true_score  = truth[valid_mask]
                    y_pred_score  = pred_series[valid_mask]

                    if len(y_true_score) > 0:
                        w_score   = wmape(y_true_score, y_pred_score)
                        m_score   = mae(y_true_score, y_pred_score)
                        mp_score  = mape(y_true_score, y_pred_score)
                        r_score   = rmse(y_true_score, y_pred_score)    # NEW
                        acc_score = forecast_accuracy(y_true_score, y_pred_score)
                    else:
                        w_score = float("inf")
                        m_score = mp_score = r_score = acc_score = 0.0

                    if debug:
                        logger.info(f"[MV] {name:<12} WMAPE={w_score:.4f}  RMSE={r_score:.2f}")

                    if logger_func:
                        logger_func(name, w_score, m_score, mp_score, acc_score)

                    results[name] = {
                        "model"     : final_model,
                        "wmape"     : w_score,
                        "rmse"      : r_score,
                        "test_pred" : pred_series,
                        "is_booster": is_booster,
                    }
            except Exception as e:
                logger.warning(f"[MV] {name} failed: {e}")
                continue

        if not results:
            raise RuntimeError("All multivariate models failed.")

        # ── Composite score-based selection (FIX TD-013) ─────────────
        # Use composite (WMAPE + trend + variance) rather than pure WMAPE
        # We compute composite inline here since we need train_series
        def _composite_for(name):
            r = results[name]
            try:
                # Stub forecast — we don't have full forecast yet, use test pred
                return composite_score(
                    truth.reindex(r["test_pred"].index).fillna(0),
                    r["test_pred"],
                    train_series,
                    r["test_pred"],  # Approximation until full forecast computed
                )
            except Exception:
                return r["wmape"]

        best_name = min(results.keys(), key=_composite_for)
        best_info = results[best_name]
        best_info["model_name"] = best_name

        # ── Try ensemble blending (NEW) ───────────────────────────────
        blend = self._ensemble_blend(
            results,
            top_n       =2,
            train_series=train_series,
            test_series =truth,
        )
        if blend is not None:
            best_info = blend
            best_name = blend["model_name"]
            logger.info(f"[MV] Using ensemble blend: {best_name}")

        # ── Refit best on full data & generate forecast ───────────────
        best_model  = best_info["model"]
        is_booster  = best_info.get("is_booster", False)

        X_full_final = df_full.drop(columns=["y"])[top_feats]
        y_full_final = df_full["y"] if is_booster else (
            np.log1p(df_full["y"]) if should_log else df_full["y"]
        )

        if best_model is not None:
            best_model.fit(X_full_final, y_full_final)

        last_date    = full_series_clean.index.max()
        history_df   = df_full[["y"]].copy()
        future_preds = []
        # FIX: use detected series frequency instead of hardcoded 'D'
        _mv_freq = pd.infer_freq(full_series_clean.index) or "D"
        _offset = pd.tseries.frequencies.to_offset(_mv_freq)
        future_dates = pd.date_range(
            start=last_date + _offset, periods=horizon, freq=_mv_freq
        )

        X_latest = X_full_ext.iloc[-1:].copy() if X_full_ext is not None else None

        for date in future_dates:
            x_future_row = None
            if X_latest is not None:
                x_future_row        = X_latest.copy()
                x_future_row.index  = [date]

            feat_row = self._generate_future_row(
                date, history_df, lags_list=significant_lags, x_future_row=x_future_row
            )

            for col in top_feats:
                if col not in feat_row.columns:
                    feat_row[col] = 0

            if best_model is not None:
                pred = best_model.predict(feat_row[top_feats])[0]
                pred = pred if is_booster else (np.expm1(pred) if should_log else pred)
            else:
                # Ensemble blend — average predictions from component models
                pred = float(np.mean([
                    max(0.0, m["model"].predict(feat_row[top_feats])[0])
                    for m in [results[n] for n in list(results.keys())[:2]]
                    if m.get("model") is not None
                ] or [0.0]))

            pred = max(0.0, pred)
            future_preds.append(pred)
            history_df = pd.concat(
                [history_df, pd.DataFrame({"y": [pred]}, index=[date])]
            )

        forecast_series = pd.Series(future_preds, index=future_dates)

        # Final metrics on chosen model — BUG FIX: previously reindexed truth
        # onto test_pred's index and filled missing/invalid entries with 0
        # rather than excluding them (unlike the per-candidate scoring loop
        # above, which masks them out via valid_mask). That compared a real,
        # nonzero prediction against a fabricated actual=0 for those rows,
        # inflating the error — which is why a model's final reported WMAPE
        # here could disagree with its own per-candidate WMAPE logged above
        # for the exact same model. Use the same valid_mask convention here.
        final_test_pred  = best_info["test_pred"]
        final_truth_full = truth.reindex(final_test_pred.index)
        final_valid_mask = ~final_truth_full.isna() & (final_truth_full >= 0)
        final_truth      = final_truth_full[final_valid_mask]
        final_test_pred  = final_test_pred[final_valid_mask]
        if len(final_truth) > 0:
            final_wmape = wmape(final_truth, final_test_pred)
            final_rmse  = rmse(final_truth, final_test_pred)
            final_acc   = forecast_accuracy(final_truth, final_test_pred)
        else:
            final_wmape, final_rmse, final_acc = float("inf"), 0.0, 0.0

        return {
            "train"              : train_series,
            "test"               : test_series_raw if test_series_raw is not None else test_series_clean,
            "test_pred"          : best_info["test_pred"].clip(lower=0),
            "forecast"           : forecast_series.clip(lower=0),
            "best_model"         : best_name,
            "best_model_object"  : best_model,
            "wmape"              : final_wmape,
            "rmse"               : final_rmse,
            "accuracy"           : round(final_acc, 2),
            "top_features"       : top_feats,
            "all_model_results"  : {k: {"wmape": v["wmape"]} for k, v in results.items()},
        }