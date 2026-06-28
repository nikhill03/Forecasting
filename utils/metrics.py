from typing import Union
import pandas as pd
import numpy as np

def forecast_accuracy(y_true: pd.Series, y_pred: pd.Series) -> float:

    y_true, y_pred = y_true.align(y_pred, join="inner")

    mask = ~y_true.isna()
    y_true = y_true[mask]
    y_pred = y_pred[mask]

    total_abs_error = (y_true - y_pred).abs().sum()
    total_abs_true = y_true.abs().sum()

    if total_abs_true == 0:
        if total_abs_error == 0:
            return 100.0
        else:
            return 0.0

    acc = 1.0 - (total_abs_error / total_abs_true)
    return round(acc * 100, 2)

def wmape(y_true, y_pred) -> float:

    y_true = pd.Series(y_true).astype(float)
    y_pred = pd.Series(y_pred).astype(float)

    y_true, y_pred = y_true.align(y_pred, join="inner")

    mask = ~y_true.isna()
    y_true = y_true[mask]
    y_pred = y_pred[mask]

    denom = y_true.abs().sum()
    denom = max(denom, 5.0)

    return float((y_true.sub(y_pred).abs().sum() / denom))

def mae(y_true, y_pred) -> float:
    y_true = pd.Series(y_true).astype(float)
    y_pred = pd.Series(y_pred).astype(float)
    y_true, y_pred = y_true.align(y_pred, join="inner")
    
    mask = ~y_true.isna()
    return float((y_true[mask] - y_pred[mask]).abs().mean())

def mape(y_true, y_pred) -> float:
    y_true = pd.Series(y_true).astype(float)
    y_pred = pd.Series(y_pred).astype(float)
    y_true, y_pred = y_true.align(y_pred, join="inner")
    
    mask = ~y_true.isna() & (y_true != 0)
    if mask.sum() == 0: return 0.0
    
    return float((y_true[mask] - y_pred[mask]).abs().div(y_true[mask].abs()).mean())

def calculate_adi(series: pd.Series) -> float:

    y = series.fillna(0)
    total_periods = len(y)
    non_zero_periods = (y > 0).sum()
    
    if non_zero_periods == 0:
        return float(total_periods)
        
    return round(float(total_periods / non_zero_periods), 2)

def calculate_cv2(series: pd.Series) -> float:

    y = series.fillna(0)
    non_zero_values = y[y > 0]
    
    if len(non_zero_values) < 2:
        return 0.0
        
    mean_nz = non_zero_values.mean()
    std_nz = non_zero_values.std()
    
    if mean_nz == 0:
        return 0.0
        
    return round(float((std_nz / mean_nz) ** 2), 2)

def classify_demand(adi: float, cv2: float) -> str:
    if adi is None or cv2 is None:
        return "Unknown"
        
    if adi < 1.32 and cv2 < 0.49:
        return "Smooth Demand"
    elif adi < 1.32 and cv2 >= 0.49:
        return "Erratic Demand"
    elif adi >= 1.32 and cv2 < 0.49:
        return "Intermittent Demand"
    else:
        return "Lumpy Demand"

def trend_error(train_series: pd.Series, forecast_series: pd.Series) -> float:

    if forecast_series is None or forecast_series.empty:
        return 1.0

    recent = train_series.tail(min(21, len(train_series)))
    if len(recent) < 7:
        return 0.0

    x = np.arange(len(recent))
    y = recent.values.astype(float)

    try:
        actual_slope = np.polyfit(x, y, 1)[0]
    except Exception:
        actual_slope = 0.0

    fx = np.arange(len(forecast_series))
    fy = forecast_series.values.astype(float)

    try:
        forecast_slope = np.polyfit(fx, fy, 1)[0]
    except Exception:
        forecast_slope = 0.0

    denom = abs(actual_slope) + 1e-6
    return abs(actual_slope - forecast_slope) / denom

def variance_penalty(train_series: pd.Series, forecast_series: pd.Series) -> float:

    if forecast_series is None or forecast_series.empty:
        return 1.0

    train_std = float(train_series.tail(30).std())
    forecast_std = float(forecast_series.std())

    if train_std <= 1e-6:
        return 0.0

    ratio = forecast_std / train_std
    return abs(1.0 - ratio)

def calculate_performance_metrics(y_true, y_pred) -> dict:
    
    return {
        "wmape": wmape(y_true, y_pred),
        "mae": mae(y_true, y_pred),
        "mape": mape(y_true, y_pred),
        "accuracy": forecast_accuracy(y_true, y_pred)
    }