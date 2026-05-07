"""
time_checks.py — Time coverage and daily axis checks.
"""

from __future__ import annotations

import numpy as np
import xarray as xr


def check_time_coverage(ds: xr.Dataset, time_dim: str,
                         period: tuple[int, int]) -> str:
    """Verify that *ds[time_dim]* covers *period* (start, end) inclusive.

    Returns 'OK' on full coverage, 'WARN' on partial, 'FAIL' on out-of-range
    or parse error.
    """
    try:
        years = ds[time_dim].dt.year.values
        year_min, year_max = int(years.min()), int(years.max())
        start, end = period
        if year_min < start or year_max > end:
            return "FAIL"
        expected = set(range(start, end + 1))
        found = set(years.tolist())
        if not expected.issubset(found):
            return "WARN"
        return "OK"
    except Exception:
        return "FAIL"


def check_daily_axis(ds: xr.Dataset, time_dim: str) -> str:
    """Return 'OK' if consecutive time steps are exactly 1 day apart."""
    try:
        values = ds[time_dim].values
        if values.size < 2:
            return "OK"
        diffs = np.diff(values).astype("timedelta64[D]")
        return "OK" if np.all(diffs == np.timedelta64(1, "D")) else "FAIL"
    except Exception:
        return "FAIL"
