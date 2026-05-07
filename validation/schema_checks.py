"""
schema_checks.py — Variable presence, units, and non-NaN coverage checks.

Functions here are called by ValidationEngine.validate(); they can also
be imported directly for unit testing or one-off inspection.
"""

from __future__ import annotations
import logging

import numpy as np
import xarray as xr

logger = logging.getLogger(__name__)

_TIME_CANDIDATES = ("time", "valid_time")


def _detect_dim(ds: xr.Dataset, candidates: tuple[str, ...]) -> str | None:
    for name in candidates:
        if name in ds.coords or name in ds.dims:
            return name
    return None


def check_variable_present(ds: xr.Dataset, variable: str) -> str:
    """Return 'OK' if *variable* is a data variable in *ds*, else 'FAIL'."""
    return "OK" if variable in ds.data_vars else "FAIL"


def check_units(data: xr.DataArray, expected: str) -> str:
    """Compare the 'units' attribute of *data* against *expected*.

    Returns 'OK' on match, 'WARN' if the attribute is missing, 'FAIL' on mismatch.
    """
    actual = str(data.attrs.get("units", "")).strip()
    if actual == expected:
        return "OK"
    if actual == "":
        return "WARN"
    return "FAIL"


def check_non_nan_coverage(ds: xr.Dataset, data: xr.DataArray,
                            is_clipped: bool = False) -> str:
    """Check that at least 80% of pixels are non-NaN.

    Parameters
    ----------
    is_clipped : True for country-masked outputs.  The denominator is the
                 number of land pixels × time steps rather than the full
                 bounding-box pixel count, since ocean/outside-border cells
                 are structurally NaN and should not penalise coverage.
    """
    if any(size == 0 for size in ds.sizes.values()):
        return "FAIL"
    if data.size == 0:
        return "FAIL"
    finite_count = int(data.count().item())
    if finite_count == 0:
        return "FAIL"

    if is_clipped:
        time_dim = _detect_dim(ds, _TIME_CANDIDATES)
        if time_dim and data.sizes.get(time_dim, 0) > 1:
            land_mask = data.count(dim=time_dim) > 0
            n_land = int(land_mask.sum().item())
            if n_land == 0:
                return "FAIL"
            denominator = n_land * data.sizes[time_dim]
        else:
            land_mask = np.isfinite(data.values)
            denominator = max(int(land_mask.sum()), 1)
        coverage = finite_count / denominator
    else:
        coverage = finite_count / data.size

    if coverage < 0.80:
        logger.warning(
            f"non_nan_coverage: {coverage:.1%} non-NaN "
            f"({'land-relative' if is_clipped else 'total'}) "
            f"— below 80% threshold"
        )
        return "FAIL"
    return "OK"
