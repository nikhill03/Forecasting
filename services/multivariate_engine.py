import pandas as pd
import numpy as np
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
from utils.metrics import wmape, mae, mape, forecast_accuracy
from services.tuning_engine import TuningEngine 
from utils.holiday_utils import get_region_holidays
from statsmodels.tsa.stattools import acf 
import logging
import os

logger = logging.getLogger("services.multivariate_engine")

class MultivariateEngine:
    def __init__(self, selected_regions: list = None):
        self.selected_regions = selected_regions or ['US', 'IN']
        self.tuner = TuningEngine(n_iter=10, cv_splits=3) 

    def _get_combined_holidays(self, dates):
        if len(dates) == 0: return holidays.HolidayBase()
        return get_region_holidays(dates, self.selected_regions)

    def _add_cyclical_features(self, df):
        df["month_sin"] = np.sin(2 * np.pi * df["month_of_year"] / 12)
        df["month_cos"] = np.cos(2 * np.pi * df["month_of_year"] / 12)
        df["quarter_sin"] = np.sin(2 * np.pi * df["quarter_of_year"] / 4)
        df["quarter_cos"] = np.cos(2 * np.pi * df["quarter_of_year"] / 4)
        df["week_sin"] = np.sin(2 * np.pi * df["week_of_year"] / 52) 
        df["week_cos"] = np.cos(2 * np.pi * df["week_of_year"] / 52)
        return df

    def _detect_significant_lags(self, series, max_lags=40):
        try:
            series = series.dropna()
            n_lags = min(max_lags, len(series) // 2 - 1)
            if n_lags < 1: return [1, 7] 
            acf_vals = acf(series, nlags=n_lags, fft=True)
            limit = 1.96 / np.sqrt(len(series))
            significant_lags = [i for i, v in enumerate(acf_vals) if abs(v) > limit and i > 0]
            if 1 not in significant_lags: significant_lags.insert(0, 1)
            return significant_lags[:10] 
        except Exception:
            return [1, 7]

    def _add_features(self, df, lags_list=None):
        if lags_list is None: lags_list = [1, 7]
        df = df.copy()
        
        # Calendar features
        df["day_of_week"] = df.index.dayofweek
        df["week_of_year"] = df.index.isocalendar().week.astype(int)
        df["month_of_year"] = df.index.month
        df["quarter_of_year"] = df.index.quarter 
        df["is_month_end"] = df.index.is_month_end.astype(int)
        df["is_month_start"] = df.index.is_month_start.astype(int)
        df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)
        df["is_monday"] = (df["day_of_week"] == 0).astype(int)

        # Cyclical features
        df = self._add_cyclical_features(df)

        # Holidays features
        holiday_obj = self._get_combined_holidays(df.index)
        df["is_holiday"] = df.index.isin(holiday_obj).astype(int)
        df["before_holiday_1"] = (df.index + pd.Timedelta(days=1)).isin(holiday_obj).astype(int)
        df["after_holiday_1"] = (df.index - pd.Timedelta(days=1)).isin(holiday_obj).astype(int)
        df["after_holiday_2"] = (df.index - pd.Timedelta(days=2)).isin(holiday_obj).astype(int)

        # Lags features
        target = df["y"]
        for lag in lags_list:
            df[f"lag_{lag}"] = target.shift(lag)
            
        lag_1 = target.shift(1)
        lag_3 = target.shift(3) 
        df["smart_momentum"] = np.where(df.index.dayofweek == 0, lag_3, lag_1)

        # Rolling features
        df["roll_max_3"] = target.shift(1).rolling(3).max().fillna(0)
        df["roll_mean_7"] = target.shift(1).rolling(7).mean()
        df["roll_max_7"] = target.shift(1).rolling(7).max()
        df["roll_max_14"] = target.shift(1).rolling(14).max() 
        df["roll_max_28"] = target.shift(1).rolling(28).max() 
        df["roll_std_7"] = target.shift(1).rolling(7).std().fillna(0)
        df["roll_mean_28"] = target.shift(1).rolling(28).mean()

        # Ratios features
        trend_lag = 7 if 7 in lags_list else 1
        df["trend_strength"] = df.get(f"lag_{trend_lag}", lag_1) / (df["roll_mean_7"] + 1e-6)
        df["volatility_ratio"] = df["roll_std_7"] / (target.shift(1).rolling(28).std() + 1e-6)
        df["spike_ratio"] = lag_1 / (df["roll_max_28"] + 1e-6)

        return df

    def _generate_future_row(self, date, history_df, lags_list, x_future_row=None): 
        row = pd.DataFrame(index=[date])
       
        row["day_of_week"] = date.dayofweek
        row["week_of_year"] = date.isocalendar()[1]
        row["month_of_year"] = date.month
        row["quarter_of_year"] = date.quarter 
        row["is_month_end"] = int(date.is_month_end)
        row["is_month_start"] = int(date.is_month_start)
        row["is_weekend"] = int(date.dayofweek >= 5)
        row["is_monday"] = (row["day_of_week"] == 0).astype(int)

        
        row["month_sin"] = np.sin(2 * np.pi * row["month_of_year"] / 12)
        row["month_cos"] = np.cos(2 * np.pi * row["month_of_year"] / 12)
        row["quarter_sin"] = np.sin(2 * np.pi * row["quarter_of_year"] / 4)
        row["quarter_cos"] = np.cos(2 * np.pi * row["quarter_of_year"] / 4)
        row["week_sin"] = np.sin(2 * np.pi * row["week_of_year"] / 52)
        row["week_cos"] = np.cos(2 * np.pi * row["week_of_year"] / 52)

        
        check_dates = [date, date+pd.Timedelta(days=1), date-pd.Timedelta(days=1), date-pd.Timedelta(days=2)]
        holiday_obj = self._get_combined_holidays(pd.Index(check_dates))
        row["is_holiday"] = int(date in holiday_obj)
        row["before_holiday_1"] = int((date + pd.Timedelta(days=1)) in holiday_obj)
        row["after_holiday_1"] = int((date - pd.Timedelta(days=1)) in holiday_obj)
        row["after_holiday_2"] = int((date - pd.Timedelta(days=2)) in holiday_obj)

        def get_lag(days_back):
            target_date = date - pd.Timedelta(days=days_back)
            if target_date in history_df.index: return float(history_df.loc[target_date, "y"])
            return 0.0

        for lag in lags_list:
            row[f"lag_{lag}"] = get_lag(lag)

        if date.weekday() == 0: row["smart_momentum"] = get_lag(3)
        else: row["smart_momentum"] = get_lag(1)

        window_end = date - pd.Timedelta(days=1)
        window_start = date - pd.Timedelta(days=28)
        recent = history_df.loc[window_start:window_end, "y"]
        
        row["roll_max_3"] = recent.iloc[-3:].max() if len(recent) >= 1 else 0
        row["roll_mean_7"] = recent.iloc[-7:].mean() if len(recent) >= 1 else 0
        row["roll_max_7"] = recent.iloc[-7:].max() if len(recent) >= 1 else 0
        row["roll_max_14"] = recent.iloc[-14:].max() if len(recent) >= 1 else 0
        row["roll_max_28"] = recent.max() if len(recent) >= 1 else 0

        std_7 = recent.iloc[-7:].std() if len(recent) >= 2 else 0
        row["roll_std_7"] = std_7
        row["roll_mean_28"] = recent.mean() if len(recent) >= 1 else 0
        std_28 = recent.std() if len(recent) >= 2 else 0

        trend_lag = 7 if 7 in lags_list else 1
        lag_val_for_trend = get_lag(trend_lag)
        row["trend_strength"] = lag_val_for_trend / (row["roll_mean_7"] + 1e-6)
        row["volatility_ratio"] = std_7 / (std_28 + 1e-6)
        row["spike_ratio"] = get_lag(1) / (row["roll_max_28"] + 1e-6)

        if x_future_row is not None and not x_future_row.empty:
            for col in x_future_row.columns:
                row[col] = x_future_row[col].values[0]

        return row

    def _select_features(self, X, y, debug=False):
        X_clean = X.fillna(0)
        rf = ExtraTreesRegressor(n_estimators=100, random_state=42, n_jobs=-1)
        rf.fit(X_clean, y)
        imp = pd.Series(rf.feature_importances_, index=X.columns).sort_values(ascending=False)
        
        cumsum = imp.cumsum()
        cutoff = cumsum[cumsum < 0.95].index.tolist()
        top_n = imp.index[:15].tolist()
        
        forced_features = [
            c for c in X.columns 
            if "sin" in c or "cos" in c or "month" in c or "quarter" in c
        ]
        
        final_feats = list(set(cutoff) | set(top_n) | set(forced_features))
        
        if debug: print(f"Features Selected: {len(final_feats)}")
        return final_feats

    # Run Multivariate
    def run_multivariate(self, train_series, test_series_clean, test_series_raw=None, 
                        X_external_train=None, X_external_test=None,
                        debug=False, logger_func=None, horizon=60, test_size=30):
        """
        Unified Multivariate Runner: Synchronized with dynamic test window.
        Ensures internal feature engineering and slicing matches the Univariate split.
        """
        # Data prep.
        full_series_clean = pd.concat([train_series, test_series_clean]).sort_index()
        skewness = full_series_clean.apply(lambda x: max(0, x)).skew()
        should_log_linear = abs(skewness) > 2.0 

        significant_lags = self._detect_significant_lags(train_series)

        df_full = pd.DataFrame({"y": full_series_clean.apply(lambda x: max(0, x))})
        df_full = self._add_features(df_full, lags_list=significant_lags)

        # Merge External X
        X_full_ext = None
        if X_external_train is not None and not X_external_train.empty:
            X_full_ext = pd.concat([X_external_train, X_external_test]).sort_index()
            # Left join 
            df_full = df_full.join(X_full_ext, how="left")
            
            df_full[X_full_ext.columns] = df_full[X_full_ext.columns].fillna(method='ffill').fillna(0)

        df_full = df_full.dropna()

        n = len(df_full)
        actual_test_size = min(test_size, int(round(n * 0.2))) 
        actual_test_size = max(7, actual_test_size)

        train_df = df_full.iloc[:-actual_test_size]
        test_df = df_full.iloc[-actual_test_size:]

        X_train = train_df.drop(columns=["y"])
        y_train_raw = train_df["y"]
        X_test = test_df.drop(columns=["y"])
        
        # Feature Selection
        y_for_selection = np.log1p(y_train_raw) if should_log_linear else y_train_raw
        top_feats = self._select_features(X_train, y_for_selection, debug=debug)
        
        X_train = X_train[top_feats]
        X_test = X_test[top_feats]

        QUANTILE_LEVEL = 0.75
        
        def get_base_model(name):
            if name == "LightGBM": return lgb.LGBMRegressor(objective='quantile', alpha=QUANTILE_LEVEL, metric='quantile', verbose=-1)
            if name == "XGBoost": return XGBRegressor(objective='reg:quantileerror', quantile_alpha=QUANTILE_LEVEL, n_jobs=-1, verbosity=0)
            if name == "HistGB": return HistGradientBoostingRegressor(loss='quantile', quantile=QUANTILE_LEVEL)
            if name == "ExtraTrees": return ExtraTreesRegressor(n_jobs=-1, random_state=42)
            if name == "Ridge": return Ridge() 
            if name == "Huber": return HuberRegressor(max_iter=2000)
            return None

        defaults = {
            "LightGBM": {"n_estimators": 300, "learning_rate": 0.05, "num_leaves": 20, "alpha": QUANTILE_LEVEL},
            "XGBoost": {"n_estimators": 300, "learning_rate": 0.05, "max_depth": 6, "quantile_alpha": QUANTILE_LEVEL},
            "HistGB": {"max_iter": 300, "max_depth": 8, "quantile": QUANTILE_LEVEL},
            "ExtraTrees": {"n_estimators": 200, "max_depth": 15},
            "Ridge": {"alpha": 1.0},
            "Huber": {"epsilon": 1.35}
        }
        
        model_names = ["LightGBM", "XGBoost", "HistGB", "ExtraTrees", "Ridge", "Huber"]
        results = {}

        for name in model_names:
            try:
                is_booster = name in ["LightGBM", "XGBoost", "HistGB"]
                y_train_curr = y_train_raw if is_booster else (np.log1p(y_train_raw) if should_log_linear else y_train_raw)
                base_est = get_base_model(name)
                best_params = defaults.get(name, {})
                
                if name == "Ridge": 
                    final_model = make_pipeline(StandardScaler(), Ridge(**best_params))
                elif name == "Huber": 
                    hub_params = best_params.copy()
                    hub_params["max_iter"] = 2000
                    final_model = make_pipeline(StandardScaler(), HuberRegressor(**hub_params))
                else: 
                    final_model = base_est
                    final_model.set_params(**best_params)

                final_model.fit(X_train, y_train_curr)
                
                if len(X_test) > 0:
                    pred_raw = final_model.predict(X_test)
                    pred_final = pred_raw if is_booster else (np.expm1(pred_raw) if should_log_linear else pred_raw)
                    pred_final = np.maximum(pred_final, 0)
                    pred_series = pd.Series(pred_final, index=X_test.index)
                    
                    if test_series_raw is not None:
                        truth = test_series_raw.reindex(pred_series.index)
                        valid_mask = ~truth.isna() & (truth >= 0)
                        y_true_score = truth[valid_mask]
                        y_pred_score = pred_series[valid_mask]
                    else:
                        y_true_score = test_series_clean.loc[X_test.index]
                        y_pred_score = pred_series
                    
                    if len(y_true_score) > 0:
                        w_score = wmape(y_true_score, y_pred_score)
                        m_score = mae(y_true_score, y_pred_score)
                        mp_score = mape(y_true_score, y_pred_score)
                        acc_score = forecast_accuracy(y_true_score, y_pred_score)
                    else:
                        w_score = float('inf')
                        m_score, mp_score, acc_score = 0.0, 0.0, 0.0

                    print(f"      >> [MV] Candidate: {name:<10} | WMAPE: {w_score:.4f}")
                    if logger_func: logger_func(name, w_score, m_score, mp_score, acc_score)
                    results[name] = {"model": final_model, "wmape": w_score, "test_pred": pred_series, "is_booster": is_booster}
            except Exception:
                continue

        if not results: raise RuntimeError("All multivariate models failed.")
        best_name = min(results.keys(), key=lambda k: results[k]["wmape"])
        best_info = results[best_name]
        best_model = best_info["model"]
        is_booster = best_info["is_booster"]

        # Refit & Forecast
        X_full_final = df_full.drop(columns=["y"])[top_feats]
        y_full_final = df_full["y"] if is_booster else (np.log1p(df_full["y"]) if should_log_linear else df_full["y"])
        best_model.fit(X_full_final, y_full_final)

        last_date = full_series_clean.index.max()
        history_df = df_full[["y"]].copy() 
        future_preds = []
        future_dates = pd.date_range(start=last_date + pd.Timedelta(days=1), periods=horizon, freq="D")

        X_latest_vals = None
        if X_full_ext is not None:
             X_latest_vals = X_full_ext.iloc[-1:].copy()

        for date in future_dates:
            x_future_row = None
            if X_latest_vals is not None:
                x_future_row = X_latest_vals.copy()
                x_future_row.index = [date]
            
            feat_row = self._generate_future_row(date, history_df, lags_list=significant_lags, x_future_row=x_future_row) 
            
            for col in top_feats: 
                if col not in feat_row.columns: feat_row[col] = 0
            
            pred = best_model.predict(feat_row[top_feats])[0]
            pred = pred if is_booster else (np.expm1(pred) if should_log_linear else pred)
            pred = max(0, pred)
            future_preds.append(pred)
            history_df = pd.concat([history_df, pd.DataFrame({"y": [pred]}, index=[date])])

        forecast_series = pd.Series(future_preds, index=future_dates)

        return {
            "train": train_series,
            "test": test_series_raw if test_series_raw is not None else test_series_clean,
            "test_pred": best_info["test_pred"],
            "forecast": forecast_series.clip(lower=0),
            "best_model": best_name,
            "best_model_object": best_model,
            "wmape": best_info["wmape"],
            "accuracy": round((1 - best_info["wmape"]) * 100, 2),
            "top_features": top_feats,
        }