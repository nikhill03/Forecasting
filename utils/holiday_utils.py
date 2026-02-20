import holidays
import pandas as pd

def get_region_holidays(dates, regions: list = None):
    """
    Dynamically returns a holiday object based on selected regions.
    Handles both DatetimeIndex and Series inputs.
    """
    if not regions:
        regions = ['US', 'IN']
        
    combined = holidays.HolidayBase()
    
    # FIX: Robustly extract unique years regardless of input type
    if isinstance(dates, pd.Series):
        unique_years = dates.dt.year.unique().tolist()
    else:
        unique_years = pd.DatetimeIndex(dates).year.unique().tolist()
        
    extended_years = set(unique_years)
    for y in unique_years:
        extended_years.add(y - 1)
        extended_years.add(y + 1)

    if 'US' in regions:
        combined += holidays.US(years=extended_years)
    if 'IN' in regions:
        combined += holidays.India(years=extended_years)
        
    return combined