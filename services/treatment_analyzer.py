import pandas as pd
import numpy as np

class TreatmentAnalyzer:
    """
    Diagnostic Engine to automatically determine the best data cleaning and 
    imputation strategies for Target (Y) and Features (X).
    """

    @staticmethod
    def analyze_series(series: pd.Series, is_target: bool = False) -> dict:
        config = {
            "enforce_daily_index": True,
            "weekend_treatment": "median",  # Default fallback
            "weekday_treatment": "median",  # Default fallback
            "outlier_treatment": "none",
            "intermittent_smoothing": False
        }
        
        if series.empty:
            return config

        clean_series = series.dropna()
        if clean_series.empty:
            return config

        n_points = len(clean_series)
        
        # 1. Weekend Logic (> 60% zeros on weekends)
        # 0=Mon, 4=Fri, 5=Sat, 6=Sun
        is_weekend = clean_series.index.weekday >= 5
        weekend_data = clean_series[is_weekend]
        
        if not weekend_data.empty:
            zero_ratio_weekend = (weekend_data == 0).sum() / len(weekend_data)
            if zero_ratio_weekend >= 0.60:
                config["weekend_treatment"] = "zero"
        
        # 2. Weekday / Smoothing / Seasonality Logic
        days_history = (clean_series.index.max() - clean_series.index.min()).days
        
        autocorr = 0
        if n_points > 14:
            autocorr = clean_series.autocorr(lag=1)
            
        # Smooth datasets get Forward-Fill (ffill)
        if autocorr > 0.8:
            config["weekday_treatment"] = "ffill"
        else:
            # Enough datapoints: Last year same time frame median
            if days_history > 365:
                config["weekday_treatment"] = "yearly_seasonal_median"
            # Medium history: Last quarter same day median
            elif days_history > 90:
                config["weekday_treatment"] = "recent_seasonal_median"
                
        # 3. Intermittency Logic
        zero_ratio_total = (clean_series == 0).sum() / n_points
        if zero_ratio_total > 0.3:
            config["intermittent_smoothing"] = True
            config["weekend_treatment"] = "zero" # Intermittent usually implies zero-heavy
            
        # 4. Outlier Logic
        skewness = clean_series.skew()
        if abs(skewness) > 2.0:
            config["outlier_treatment"] = "clip"
            
        return config

    @classmethod
    def analyze_dataframe(cls, df: pd.DataFrame) -> dict:
        """Analyzes all numeric columns in a DataFrame and returns a dict of configs."""
        configs = {}
        for col in df.columns:
            if pd.api.types.is_numeric_dtype(df[col]):
                configs[col] = cls.analyze_series(df[col], is_target=False)
        return configs