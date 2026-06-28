import holidays
import pandas as pd

def get_region_holidays(dates, regions: list = None):
    """
    Ironclad regional holiday logic. 
    Only includes countries explicitly selected by the user.
    """
    combined = holidays.HolidayBase()
    
    if not regions:
        return combined
        
    if isinstance(dates, pd.Series):
        unique_years = dates.dt.year.unique().tolist()
    else:
        unique_years = pd.DatetimeIndex(dates).year.unique().tolist()
        
    extended_years = set(unique_years)
    for y in unique_years:
        extended_years.add(y - 1)
        extended_years.add(y + 1)

    if 'US' in regions:
        combined.update(holidays.US(years=extended_years))
    if 'IN' in regions:
        combined.update(holidays.India(years=extended_years))
        
    return pd.to_datetime(list(combined.keys()))