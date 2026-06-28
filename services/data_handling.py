import pandas as pd
from typing import Optional, Tuple, Dict, Any, List
import holidays
from datetime import timedelta

class DataHandling:
    def __init__(self, min_points: int = 30, allow_negative: bool = False, lookback_days: int = 90):
        self.min_points = min_points
        self.allow_negative = allow_negative
        self.lookback_days = lookback_days

        # Holiday calendars 
        self.us_holidays = holidays.US()
        self.india_holidays = holidays.India()

    def sanitize(self, df: pd.DataFrame, date_col: str, metric_col: str) -> Tuple[Optional[pd.Series], list]:
        """
        Strictly parses dates, drops duplicates, sorts, and returns the raw series.
        NO imputation or outlier clipping happens here.
        """
        logs = []

        if date_col not in df.columns:
            logs.append(f"ERROR: Date column '{date_col}' missing")
            return None, logs

        if metric_col not in df.columns:
            logs.append(f"ERROR: Metric '{metric_col}' missing")
            return None, logs

        out = df[[date_col, metric_col]].copy()
        out[date_col] = pd.to_datetime(out[date_col], errors="coerce")
        out[metric_col] = pd.to_numeric(out[metric_col], errors="coerce")
        out = out.dropna(subset=[date_col])

        # Deduplicate & sort
        out = out.drop_duplicates(subset=[date_col], keep="last")
        out = out.sort_values(date_col)
        out = out.set_index(date_col)

        series = out[metric_col]

        if series.notna().sum() < self.min_points:
            logs.append(
                f"SKIP: Only {series.notna().sum()} non-null points "
                f"(min required = {self.min_points})"
            )
            return None, logs

        return series, logs
    
    def _apply_treatment(self, series: pd.Series, config: dict) -> pd.Series:
        if series is None or series.empty: return series
        
        s = series.copy()
        
        # Enforcing Daily Index 
        if config.get("enforce_daily_index", True):
            full_idx = pd.date_range(start=s.index.min(), end=s.index.max(), freq="D")
            s = s.reindex(full_idx)

        # Last Quarter Median
        def get_quarter_median(ts, s_ref):
            start = ts - pd.Timedelta(days=90)
            end = ts - pd.Timedelta(days=1)
            
            if start < s_ref.index.min():
                start = s_ref.index.min()
                
            if start > end:
                return s_ref.head(30).median()
                
            try:
                window = s_ref.loc[start:end].dropna()
                if window.empty:
                    return s_ref.head(30).median()
                
                same_dow = window[window.index.weekday == ts.weekday()]
                return same_dow.median() if not same_dow.empty else window.median()
            except Exception:
                return s_ref.median()

        # Last Year Median (Fallback to Quarter)
        def get_yearly_median(ts, s_ref):
            start = ts - pd.Timedelta(days=372)
            end = ts - pd.Timedelta(days=358)
            
            if start < s_ref.index.min():
                return get_quarter_median(ts, s_ref)
                
            try:
                window = s_ref.loc[start:end].dropna()
                return window.median() if not window.empty else get_quarter_median(ts, s_ref)
            except Exception:
                return get_quarter_median(ts, s_ref)

        # Weekday/Weekend Missing Value Imputation
        missing_idx = s[s.isna()].index
        
        if config.get("weekday_treatment") == "ffill":
            s = s.ffill()
            missing_idx = s[s.isna()].index 

        for ts in missing_idx:
            is_weekend = ts.weekday() >= 5
            strat = config.get("weekend_treatment", "median") if is_weekend else config.get("weekday_treatment", "median")
            
            if strat == "zero":
                val = 0.0
            elif strat == "yearly_seasonal_median":
                val = get_yearly_median(ts, s)
            elif strat == "recent_seasonal_median":
                val = get_quarter_median(ts, s)
            elif strat == "ffill":
                val = s.dropna().median() 
            else: 
                val = s.dropna().median()
                
            if pd.isna(val): val = 0.0
            s.loc[ts] = val

        # Outlier Treatment
        if config.get("outlier_treatment") == "clip":
            q1 = s.quantile(0.25)
            q3 = s.quantile(0.75)
            iqr = q3 - q1
            if iqr > 0:
                upper = q3 + 3.0 * iqr 
                s = s.clip(upper=upper)
            
        if not getattr(self, "allow_negative", False):
            s = s.clip(lower=0)
            
        return s

    def impute_train(self, series: pd.Series, config: dict = None) -> pd.Series:
        """Updated to accept dynamic configuration dict."""
        if config is None:
            config = {"enforce_daily_index": True, "weekend_treatment": "median", "weekday_treatment": "median", "outlier_treatment": "none"}
        return self._apply_treatment(series, config)
    
    def apply_business_rules(self, series: pd.Series) -> pd.Series:
        return series
    
    def check_health(self, df: pd.DataFrame, cols: list) -> Dict[str, Any]:
        """Returns stats for the 'Know Your Data' tab."""
        stats = {}
        for c in cols:
            if c not in df.columns: continue
            
            s = pd.to_numeric(df[c], errors='coerce')
            
            total = len(s)
            missing = s.isna().sum()
            zeros = (s == 0).sum()
            negatives = (s < 0).sum()
            
            clean_s = s.dropna()
            if clean_s.empty:
                stats[c] = {"status": "Empty", "missing_pct": 100}
                continue

            mean_val = clean_s.mean()
            std_val = clean_s.std()
            skew_val = clean_s.skew()
            
            stats[c] = {
                "total": int(total),
                "missing": int(missing),
                "missing_pct": round((missing / total) * 100, 1),
                "zeros": int(zeros),
                "negatives": int(negatives),
                "mean": round(mean_val, 2),
                "std": round(std_val, 2),
                "skew": round(skew_val, 2),
                "min": round(clean_s.min(), 2),
                "max": round(clean_s.max(), 2),
            }
        return stats

    def impute_exogenous(self, df_x: pd.DataFrame, x_cols: list, treatment_configs: dict) -> pd.DataFrame:
        """Updated to apply feature-specific configs generated by the analyzer."""
        df_clean = df_x.copy()
        for col in x_cols:
            config = treatment_configs.get(col, {})
            df_clean[col] = self._apply_treatment(df_clean[col], config)
        return df_clean