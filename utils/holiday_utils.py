"""
holiday_utils.py — Regional Holiday Calendar
=============================================
Version : 2.0.0
Changes vs v1.0
---------------
TD-016 FIXED : Expanded from US+IN only to 8 regions: US, IN, GB, DE, FR, AU, CA, JP
NEW   : Returns a set for O(1) membership testing (v1.0 returned pd.DatetimeIndex
        which has O(n) `in` checks — causing subtle perf issues in multivariate
        feature engineering when holiday_obj was used in large date ranges)
NEW   : _REGION_FACTORY map for clean extensibility — adding new countries
        requires only one line instead of a new if-block
NEW   : graceful fallback if an unsupported region is requested
"""

from __future__ import annotations

import logging
from typing import Optional

import holidays
import pandas as pd

logger = logging.getLogger("utils.holiday_utils")

# ── Registry: ISO code → holidays factory ────────────────────────────
# To add a new country: add one entry here. No other changes needed.
_REGION_FACTORY: dict = {
    "US": lambda years: holidays.US(years=years),
    "IN": lambda years: holidays.India(years=years),
    "GB": lambda years: holidays.UnitedKingdom(years=years),
    "DE": lambda years: holidays.Germany(years=years),
    "FR": lambda years: holidays.France(years=years),
    "AU": lambda years: holidays.Australia(years=years),
    "CA": lambda years: holidays.Canada(years=years),
    "JP": lambda years: holidays.Japan(years=years),
}

SUPPORTED_REGIONS = sorted(_REGION_FACTORY.keys())


def get_region_holidays(
    dates  : pd.Index | pd.Series,
    regions: Optional[list] = None,
) -> set:
    """
    Returns a set of holiday dates for the given regions.

    Parameters
    ----------
    dates   : DatetimeIndex or Series of dates — used to determine
              the year range to cover (with ±1 year buffer).
    regions : List of ISO country codes. Unsupported codes are logged
              and skipped gracefully.

    Returns
    -------
    set of datetime.date objects — O(1) membership testing
    (v1.0 returned pd.DatetimeIndex which has O(n) `in` checks)

    Usage
    -----
    hols = get_region_holidays(df.index, regions=["US", "IN"])
    df["is_holiday"] = df.index.map(lambda d: d.date() in hols).astype(int)
    """
    if not regions:
        return set()

    # Determine year range with ±1 buffer
    if isinstance(dates, pd.Series):
        dt_index = pd.DatetimeIndex(dates)
    else:
        dt_index = pd.DatetimeIndex(dates)

    if len(dt_index) == 0:
        return set()

    unique_years = set(dt_index.year.tolist())
    extended_years = set()
    for y in unique_years:
        extended_years |= {y - 1, y, y + 1}

    # Build combined holiday set
    combined: set = set()
    for region in regions:
        region_upper = region.upper().strip()
        factory = _REGION_FACTORY.get(region_upper)
        if factory is None:
            logger.warning(
                f"Unsupported holiday region '{region}'. "
                f"Supported: {SUPPORTED_REGIONS}"
            )
            continue
        try:
            h = factory(extended_years)
            # holidays library returns date keys — convert to date objects
            combined.update(h.keys())
        except Exception as e:
            logger.warning(f"Failed to load holidays for '{region_upper}': {e}")

    return combined


def is_holiday(date: pd.Timestamp, holiday_set: set) -> bool:
    """
    Convenience function for single-date lookup.

    Parameters
    ----------
    date        : pd.Timestamp
    holiday_set : set returned by get_region_holidays()
    """
    return date.date() in holiday_set


def get_holiday_features(
    index  : pd.DatetimeIndex,
    regions: Optional[list] = None,
) -> pd.DataFrame:
    """
    Generates holiday-related features for a DatetimeIndex.

    Returns a DataFrame with columns:
      is_holiday, before_holiday_1, after_holiday_1, after_holiday_2

    This is the preferred way to add holiday features in the
    preprocessing pipeline — avoids repeated holiday set construction.
    """
    hols = get_region_holidays(index, regions)

    dates = pd.DatetimeIndex(index)

    is_hol     = [d.date() in hols for d in dates]
    before_1   = [(d + pd.Timedelta(days=1)).date() in hols for d in dates]
    after_1    = [(d - pd.Timedelta(days=1)).date() in hols for d in dates]
    after_2    = [(d - pd.Timedelta(days=2)).date() in hols for d in dates]

    return pd.DataFrame(
        {
            "is_holiday"      : pd.array(is_hol,   dtype="boolean").astype(int),
            "before_holiday_1": pd.array(before_1, dtype="boolean").astype(int),
            "after_holiday_1" : pd.array(after_1,  dtype="boolean").astype(int),
            "after_holiday_2" : pd.array(after_2,  dtype="boolean").astype(int),
        },
        index=index,
    )