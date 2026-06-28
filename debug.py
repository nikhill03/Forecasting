import pandas as pd
import numpy as np
import holidays
from datetime import datetime
from services.data_handling import DataHandling

class FeatureEngineering:
    def __init__(self):
        self.country_holidays = [holidays.US, holidays.India]

    def _get_combined_holidays(self, dates):
        if len(dates) == 0:
            return holidays.HolidayBase()
        unique_years = dates.year.unique().tolist()
        extended_years = set(unique_years)
        for y in unique_years:
            extended_years.add(y - 1)
            extended_years.add(y + 1)
        combined = holidays.HolidayBase()
        for country_class in self.country_holidays:
            combined += country_class(years=extended_years)
        return combined

    def _add_cyclical_features(self, df):
        df["month_sin"] = np.sin(2 * np.pi * df["month_of_year"] / 12)
        df["month_cos"] = np.cos(2 * np.pi * df["month_of_year"] / 12)
        df["quarter_sin"] = np.sin(2 * np.pi * df["quarter_of_year"] / 4)
        df["quarter_cos"] = np.cos(2 * np.pi * df["quarter_of_year"] / 4)
        df["week_sin"] = np.sin(2 * np.pi * df["week_of_year"] / 52)
        df["week_cos"] = np.cos(2 * np.pi * df["week_of_year"] / 52)
        return df

    def create_features(self, df):
        df = df.copy()
        df["day_of_week"] = df.index.dayofweek
        df["week_of_year"] = df.index.isocalendar().week.astype(int)
        df["month_of_year"] = df.index.month
        df["quarter_of_year"] = df.index.quarter
        df["is_month_end"] = df.index.is_month_end.astype(int)
        df["is_month_start"] = df.index.is_month_start.astype(int)
        df["is_weekend"] = (df["day_of_week"] >= 5).astype(int)
        df["is_monday"] = (df["day_of_week"] == 0).astype(int)

        df = self._add_cyclical_features(df)

        holiday_obj = self._get_combined_holidays(df.index)
        df["is_holiday"] = df.index.astype('datetime64[ns]').isin(holiday_obj).astype(int)
        df["before_holiday_1"] = (df.index + pd.Timedelta(days=1)).astype('datetime64[ns]').isin(holiday_obj).astype(int)
        df["after_holiday_1"] = (df.index - pd.Timedelta(days=1)).astype('datetime64[ns]').isin(holiday_obj).astype(int)
        df["after_holiday_2"] = (df.index - pd.Timedelta(days=2)).astype('datetime64[ns]').isin(holiday_obj).astype(int)

        if 'Value' in df.columns:
            target = df["Value"]
            df["lag_1"] = target.shift(1)
            df["lag_7"] = target.shift(7)
            lag_1 = target.shift(1)
            lag_3 = target.shift(3)
            df["smart_momentum"] = np.where(df.index.dayofweek == 0, lag_3, lag_1)

            df["roll_max_3"] = target.shift(1).rolling(3).max().fillna(0)
            df["roll_mean_7"] = target.shift(1).rolling(7).mean()
            df["roll_max_7"] = target.shift(1).rolling(7).max()
            df["roll_max_14"] = target.shift(1).rolling(14).max()
            df["roll_max_28"] = target.shift(1).rolling(28).max()

            df["roll_std_7"] = target.shift(1).rolling(7).std().fillna(0)
            df["roll_mean_28"] = target.shift(1).rolling(28).mean()

            df["trend_strength"] = df["lag_7"] / (df["roll_mean_7"] + 1e-6)
            df["volatility_ratio"] = df["roll_std_7"] / (target.shift(1).rolling(28).std() + 1e-6)

            df["spike_ratio"] = df["lag_1"] / (df["roll_max_28"] + 1e-6)

        return df

class DebugPipeline:
    def __init__(self, excel_file: str, sheet_name: str, date_column: str, metric_column: str):
        self.excel_file = excel_file
        self.sheet_name = sheet_name
        self.date_column = date_column
        self.metric_column = metric_column
        self.data_handler = DataHandling()
        self.feature_engineering = FeatureEngineering()

    def load_data(self):
        df = pd.read_excel(self.excel_file, sheet_name=self.sheet_name)
        return df

    def process_data(self, df: pd.DataFrame):
        series, logs = self.data_handler.sanitize(df, self.date_column, self.metric_column)
        if series is None:
            print("Data sanitization failed. Logs:", logs)
            return None

        imputed_series = self.data_handler.impute_train(series)
        df_cleaned = pd.DataFrame(imputed_series)
        df_cleaned['date'] = df_cleaned.index

        return df_cleaned

    def engineer_features(self, df: pd.DataFrame):
        df_with_features = self.feature_engineering.create_features(df)
        return df_with_features

    def save_debug_csv(self, df: pd.DataFrame):
        debug_file = f"debug_data_{self.metric_column}.csv"
        df.to_csv(debug_file, index=False)
        print(f"Debug file saved as {debug_file}")

    def run(self):
        df = self.load_data()

        df_cleaned = self.process_data(df)
        if df_cleaned is None:
            return

        df_with_features = self.engineer_features(df_cleaned)

        self.save_debug_csv(df_with_features)

debug_pipeline = DebugPipeline(excel_file="sept_dataset_2025.xlsx", sheet_name="Gasoline", date_column="Date", metric_column="Closed Complted")
debug_pipeline.run()
