"""
anomaly_checks.py — Outlier detection and distribution shape checks.

Both checks return WARN (never FAIL) so they never abort a run.
"""

from __future__ import annotations
import logging

import numpy as np
import xarray as xr

logger = logging.getLogger(__name__)

# Minimum expected spread (p95 − p05) by NetCDF variable name.
_MIN_SPREAD: dict[str, float] = {
    "precip": 0.01,
    "pr":     0.01,
    "rh":     2.0,
    "hurs":   2.0,
    "vpd":    0.05,
    "tas":    0.5,
    "t2m":    0.5,
}


def check_anomaly(data: xr.DataArray,
                  valid_range: tuple[float, float]) -> str:
    """Flag pixels outside *valid_range*. Returns 'WARN' (never 'FAIL')."""
    lo, hi = valid_range
    try:
        vals = data.values.astype(float)
        finite_vals = vals[np.isfinite(vals)]
        if finite_vals.size == 0:
            return "SKIP"
        out_of_range = int(np.sum((finite_vals < lo) | (finite_vals > hi)))
        if out_of_range == 0:
            return "OK"
        pct = 100.0 * out_of_range / finite_vals.size
        logger.warning(
            f"Anomaly: {out_of_range}/{finite_vals.size} finite pixels "
            f"({pct:.2f}%) outside valid range [{lo}, {hi}] "
            f"for variable '{data.name}'"
        )
        return "WARN"
    except Exception as exc:
        logger.warning(f"Anomaly check error: {exc}")
        return "WARN"


def check_distribution(data: xr.DataArray) -> str:
    """Detect flat or saturated fields using percentile spread.

    Returns 'OK', 'WARN' (spread too low), or 'SKIP' (unknown variable
    or insufficient data). Never returns 'FAIL'.
    """
    var_name = str(data.name) if data.name else ""
    min_spread = _MIN_SPREAD.get(var_name)
    if min_spread is None:
        return "SKIP"
    try:
        vals = data.values.astype(float)
        finite_vals = vals[np.isfinite(vals)]
        if finite_vals.size < 10:
            return "SKIP"
        p05 = float(np.percentile(finite_vals, 5))
        p95 = float(np.percentile(finite_vals, 95))
        spread = p95 - p05
        if spread < min_spread:
            logger.warning(
                f"Distribution WARN [{var_name}]: p95-p05 spread={spread:.4f} "
                f"below minimum {min_spread} — possible flat/constant field"
            )
            return "WARN"
        return "OK"
    except Exception as exc:
        logger.warning(f"Distribution check error: {exc}")
        return "WARN"
