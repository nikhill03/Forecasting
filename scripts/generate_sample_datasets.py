"""
scripts/generate_sample_datasets.py
====================================
Regenerates the onboarding sample datasets in backend/static/samples/.

This script is DEVELOPMENT TOOLING, not runtime code. The CSVs it writes are
committed to git and read directly by backend/services/sample_datasets.py —
nothing imports or invokes this module at request time. It exists so the
committed data has visible provenance and can be reproduced or tweaked
without hand-editing 730 rows of CSV.

Run from the repo root:

    python scripts/generate_sample_datasets.py
    python scripts/generate_sample_datasets.py --check   # verify, write nothing

Design constraints (each one is load-bearing — see the notes inline):

  1. Every series is DAILY and date-continuous. Demand classification runs on
     an imputed series that services/data_handling.py force-reindexes to
     freq="D" regardless of the data's real frequency, so a weekly series
     would be padded with six synthetic days per week and its ADI/CV² would
     describe the imputation rather than the data.

  2. The date column is FIRST, and no numeric column sits in the 1900–2100
     band. utils/forecasting.infer_date_column is parse-based and
     first-match-wins, and it claims any numeric column whose values are
     ≥80% inside [1900, 2100] as a year column.

  3. Seeds are fixed and the draw ORDER matters. Each series' primary draw
     happens first so that adding a covariate column later cannot shift the
     target values — and with them the demand classification.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ── Paths ─────────────────────────────────────────────────────────────
_REPO_ROOT   = Path(__file__).resolve().parent.parent
_SAMPLES_DIR = _REPO_ROOT / "backend" / "static" / "samples"

# ── Series shape ──────────────────────────────────────────────────────
# Two full years of daily observations. Long enough that the seasonal
# models (Prophet, TBATS) have something to fit and that a 60-day horizon
# with a 30-day test window leaves ample training data.
_START   = "2023-01-01"
_PERIODS = 730


def _dates() -> pd.DatetimeIndex:
    return pd.date_range(_START, periods=_PERIODS, freq="D")


# ── retail-daily-smooth ───────────────────────────────────────────────
def build_retail_daily_smooth() -> pd.DataFrame:
    """Steady daily retail demand — never zero, low dispersion.

    Lands at ADI 1.000 / CV² 0.010, comfortably inside the Smooth quadrant
    (both Syntetos-Boylan thresholds are 1.32 and 0.49).

    Carries two covariates so the multivariate path is exercisable from
    this sample alone. Both are kept clear of the 1900–2100 band that
    infer_date_column treats as a year column.
    """
    rng   = np.random.default_rng(42)
    idx   = _dates()
    t     = np.arange(_PERIODS)

    # Annual swing + a weekly retail rhythm around a 500-unit baseline.
    base       = 500 + 60 * np.sin(2 * np.pi * t / 365.25) + 25 * np.sin(2 * np.pi * t / 7)
    units_sold = np.round(base + rng.normal(0, 18, _PERIODS)).clip(min=1)

    # Drawn AFTER units_sold so the target series is unaffected by their
    # presence. Correlated with demand so a multivariate run has real signal.
    marketing_spend = np.round(
        1000 + 0.6 * (units_sold - 500) + rng.normal(0, 25, _PERIODS), 2
    ).clip(min=0)
    avg_temp_c = np.round(
        18 + 12 * np.sin(2 * np.pi * (t - 100) / 365.25) + rng.normal(0, 2, _PERIODS), 1
    )

    return pd.DataFrame(
        {
            "date"            : idx.strftime("%Y-%m-%d"),
            "units_sold"      : units_sold.astype(int),
            "marketing_spend" : marketing_spend,
            "avg_temp_c"      : avg_temp_c,
        }
    )


# ── spare-parts-intermittent ──────────────────────────────────────────
def build_spare_parts_intermittent() -> pd.DataFrame:
    """Sporadic demand, consistent order size when it does occur.

    Lands at ADI 4.056 / CV² 0.022 — high interval, low size variance,
    which is the definition of the Intermittent quadrant. Croston is gated
    on exactly this classification in services/forecasting_engine.py.
    """
    rng   = np.random.default_rng(7)
    idx   = _dates()

    occurs = rng.random(_PERIODS) < 0.25
    size   = rng.normal(20, 3, _PERIODS).clip(min=1).round()
    units  = np.where(occurs, size, 0.0)

    return pd.DataFrame(
        {
            "date"          : idx.strftime("%Y-%m-%d"),
            "units_shipped" : units.astype(int),
        }
    )


# ── spare-parts-lumpy ─────────────────────────────────────────────────
def build_spare_parts_lumpy() -> pd.DataFrame:
    """Sporadic demand AND wildly variable order size — the hard quadrant.

    Lands at ADI 4.220 / CV² 0.862: intermittent on the interval axis and
    erratic on the size axis. The gamma draw is what separates this from
    the intermittent sample; both are ~78% zeros.
    """
    rng   = np.random.default_rng(11)
    idx   = _dates()

    occurs = rng.random(_PERIODS) < 0.22
    size   = rng.gamma(shape=1.1, scale=18, size=_PERIODS).clip(min=1).round()
    units  = np.where(occurs, size, 0.0)

    return pd.DataFrame(
        {
            "date"          : idx.strftime("%Y-%m-%d"),
            "units_shipped" : units.astype(int),
        }
    )


# ── Registry ──────────────────────────────────────────────────────────
# Keys match SAMPLE_CATALOG ids in backend/services/sample_datasets.py.
BUILDERS = {
    "retail-daily-smooth"      : build_retail_daily_smooth,
    "spare-parts-intermittent" : build_spare_parts_intermittent,
    "spare-parts-lumpy"        : build_spare_parts_lumpy,
}


def _classify(df: pd.DataFrame) -> tuple[str, float, float]:
    """Run the real classifier over a built frame's target column.

    Imported lazily so the script's --help works without the repo's ML
    dependency tree importing cleanly.
    """
    sys.path.insert(0, str(_REPO_ROOT))
    from utils.metrics import calculate_adi, calculate_cv2, classify_demand

    target = df.columns[1]                      # date is always column 0
    series = pd.Series(df[target].to_numpy(), dtype=float)
    adi    = calculate_adi(series)
    cv2    = calculate_cv2(series)
    return classify_demand(adi_val=adi, cv2_val=cv2).demand_type, adi, cv2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Report each sample's classification without writing any file.",
    )
    args = parser.parse_args()

    if not args.check:
        _SAMPLES_DIR.mkdir(parents=True, exist_ok=True)

    for sample_id, builder in BUILDERS.items():
        df = builder()
        demand_type, adi, cv2 = _classify(df)

        if not args.check:
            (_SAMPLES_DIR / f"{sample_id}.csv").write_text(df.to_csv(index=False))

        print(
            f"{sample_id:26s} rows={len(df):4d} cols={len(df.columns)} "
            f"ADI={adi:6.3f} CV2={cv2:6.3f} -> {demand_type}"
        )

    print("checked (nothing written)" if args.check else f"written to {_SAMPLES_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
