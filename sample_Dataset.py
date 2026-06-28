import pandas as pd
import numpy as np
from datetime import timedelta, date

# 1. Configuration
start_date = date(2023, 1, 1)
end_date = date(2025, 1, 1) # 2 Years of data
date_range = pd.date_range(start=start_date, end=end_date, freq='D')
n_days = len(date_range)

np.random.seed(42)

# 2. Generate Features (X)
# - Marketing Spend: Weekly cycle + Random noise
marketing = 1000 + 500 * np.sin(2 * np.pi * date_range.dayofyear / 365) + np.random.normal(0, 100, n_days)
marketing = np.maximum(marketing, 0) # No negative spend

# - Temperature: Seasonal pattern
temp = 20 + 15 * np.sin(2 * np.pi * (date_range.dayofyear - 100) / 365) + np.random.normal(0, 3, n_days)

# - Holiday Flag: Randomly assign holidays (approx 10 days/year)
is_holiday = np.random.choice([0, 1], size=n_days, p=[0.97, 0.03])

# - Competitor Price: Random walk
comp_price = 50 + np.cumsum(np.random.normal(0, 0.2, n_days))

df_x = pd.DataFrame({
    'Date': date_range,
    'Marketing_Spend': np.round(marketing, 2),
    'Temperature_C': np.round(temp, 1),
    'Is_Holiday': is_holiday,
    'Competitor_Price': np.round(comp_price, 2)
})

# 3. Generate Target (Y) - Sales
# Sales depends on Marketing, Temp, Holidays, Price + Trend + Seasonality + Noise
trend = np.linspace(500, 1000, n_days)
seasonality = 200 * np.sin(2 * np.pi * date_range.dayofyear / 365)
weekend_boost = (date_range.weekday >= 5) * 300 # Weekend bump

sales = (
    trend + 
    seasonality + 
    weekend_boost +
    (0.5 * marketing) +       # Marketing impact
    (500 * is_holiday) -      # Holiday spike
    (10 * comp_price) +       # Price sensitivity
    np.random.normal(0, 50, n_days) # Noise
)
sales = np.maximum(sales, 0)

df_y = pd.DataFrame({
    'Date': date_range,
    'Daily_Sales': np.round(sales, 2)
})

# 4. Save to CSV
df_x.to_csv("features_x.csv", index=False)
df_y.to_csv("target_y.csv", index=False)

print(f"Generated 'features_x.csv' and 'target_y.csv' with {n_days} rows each.")
print("X Columns:", df_x.columns.tolist())
print("Y Columns:", df_y.columns.tolist())