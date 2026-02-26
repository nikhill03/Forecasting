import holidays
import pandas as pd

def get_region_holidays(dates, regions: list = None):
    """
    Ironclad regional holiday logic. 
    Only includes countries explicitly selected by the user.
    """
    # 1. Start with an empty holiday object
    combined = holidays.HolidayBase()
    
    # 2. Return empty if no regions are selected
    if not regions:
        return combined
        
    # 3. Robustly extract unique years
    if isinstance(dates, pd.Series):
        unique_years = dates.dt.year.unique().tolist()
    else:
        unique_years = pd.DatetimeIndex(dates).year.unique().tolist()
        
    extended_years = set(unique_years)
    for y in unique_years:
        extended_years.add(y - 1)
        extended_years.add(y + 1)

    # 4. Strictly Additive
    if 'US' in regions:
        combined += holidays.US(years=extended_years)
    if 'IN' in regions:
        combined += holidays.India(years=extended_years)
        
    return pd.to_datetime(list(combined.keys()))