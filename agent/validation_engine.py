"""
validation_engine.py — Orchestrates all quality checks on a NetCDF pipeline output.

ValidationEngine.validate() runs all applicable checks and returns a dict whose
keys match the 'validation' object in run_manifest_schema.json.

Check result values: "OK" | "FAIL" | "SKIP" | "WARN"

Check implementations live in the validation/ package:
  validation.schema_checks  — variable presence, units, non-NaN coverage
  validation.time_checks    — time coverage, daily axis
  validation.spatial_checks — grid match, spatial bounds, grid consistency
  validation.anomaly_checks — outlier detection, distribution shape
"""

from __future__ import annotations
import logging
from pathlib import Path

import xarray as xr

from agent.policy import checks_to_skip
from validation.schema_checks import (
    check_variable_present,
    check_units,
    check_non_nan_coverage,
)
from validation.time_checks import check_time_coverage, check_daily_axis
from validation.spatial_checks import (
    check_grid_match,
    check_spatial_bounds,
    check_grid_consistency,
)
from validation.anomaly_checks import check_anomaly, check_distribution

logger = logging.getLogger(__name__)

# Re-export check_grid_consistency at module level for callers that imported
# it from here directly (backward-compatibility shim).
__all__ = ["ValidationEngine", "check_grid_consistency"]


class ValidationEngine:
    """
    Runs schema/time/spatial/unit checks on a single NetCDF output file.

    Parameters
    ----------
    fast_mode : skip checks listed in agent_config.yaml validation.fast_mode_skip
    """

    def __init__(self, fast_mode: bool = False):
        self.fast_mode = fast_mode
        self._skip = checks_to_skip(fast_mode)

    def validate(
        self,
        path: Path,
        *,
        variable: str,
        expected_units: str | None,
        period: tuple[int, int],
        target_grid_path: Path | None = None,
        require_daily_axis: bool = False,
        valid_range: tuple[float, float] | None = None,
        is_clipped: bool = False,
    ) -> dict:
        """
        Run all checks on *path* and return a validation result dict.

        Parameters
        ----------
        path             : path to the NetCDF file to validate
        variable         : expected primary data variable name
        expected_units   : units string to compare against, or None to skip
        period           : (year_start, year_end) inclusive
        target_grid_path : reference grid file for grid_match / spatial_bounds checks
        require_daily_axis : whether to enforce a strictly-daily time axis
        valid_range      : (lo, hi) for anomaly detection; None skips the check
        is_clipped       : True for country-masked outputs; non-NaN coverage is then
                           measured relative to land pixels, not the full bounding box
        """
        results: dict[str, str] = {}

        # 1 — existence
        if not path.exists():
            results["existence"] = "FAIL"
            results["notes"] = f"File not found: {path}"
            return results
        results["existence"] = "OK"

        try:
            with xr.open_dataset(path) as ds:
                # 2 — variable present
                results["variable_present"] = check_variable_present(ds, variable)
                if results["variable_present"] == "FAIL":
                    results["notes"] = (
                        f"Variable '{variable}' not found. "
                        f"Available: {list(ds.data_vars)}"
                    )
                    return results

                data = ds[variable]

                # 3 — non-NaN coverage (≥80% of pixels must be finite)
                results["non_nan_coverage"] = check_non_nan_coverage(
                    ds, data, is_clipped
                )

                # 4 — time coverage
                time_dim = next(
                    (n for n in ("time", "valid_time") if n in ds.coords or n in ds.dims),
                    None,
                )
                results["time_coverage"] = (
                    check_time_coverage(ds, time_dim, period) if time_dim else "FAIL"
                )

                # 5 — daily axis (optional, skippable)
                if require_daily_axis and "daily_axis" not in self._skip:
                    results["daily_axis"] = (
                        check_daily_axis(ds, time_dim) if time_dim else "FAIL"
                    )
                else:
                    results["daily_axis"] = "SKIP"

                # 6 — units
                results["units"] = (
                    check_units(data, expected_units) if expected_units else "SKIP"
                )

                # 7 — grid_match (skippable in fast mode)
                if "grid_match" not in self._skip and target_grid_path:
                    results["grid_match"] = check_grid_match(ds, target_grid_path)
                else:
                    results["grid_match"] = "SKIP"

                # 8 — spatial_bounds (skippable in fast mode)
                if "spatial_bounds" not in self._skip and target_grid_path:
                    results["spatial_bounds"] = check_spatial_bounds(
                        ds, target_grid_path
                    )
                else:
                    results["spatial_bounds"] = "SKIP"

                # 9 — anomaly / outlier detection (never aborts the run)
                results["anomaly"] = (
                    check_anomaly(data, valid_range)
                    if valid_range is not None
                    else "SKIP"
                )

                # 10 — distribution check: flat/saturated data (never aborts)
                results["distribution"] = check_distribution(data)

        except Exception as exc:
            logger.warning(f"ValidationEngine error on {path}: {exc}")
            results.setdefault("non_nan_coverage", "FAIL")
            results["notes"] = f"Unexpected validation error: {exc}"

        return results

    # ── Delegating wrappers kept for callers that use the class methods ────────

    def _check_non_nan(self, ds: xr.Dataset, data: xr.DataArray,
                       is_clipped: bool = False) -> str:
        return check_non_nan_coverage(ds, data, is_clipped)

    def _check_units(self, data: xr.DataArray, expected: str) -> str:
        return check_units(data, expected)

    def _check_time_coverage(self, ds: xr.Dataset, time_dim: str,
                              period: tuple[int, int]) -> str:
        return check_time_coverage(ds, time_dim, period)

    def _check_daily_axis(self, ds: xr.Dataset, time_dim: str) -> str:
        return check_daily_axis(ds, time_dim)

    def _check_grid_match(self, ds: xr.Dataset, target_path: Path) -> str:
        return check_grid_match(ds, target_path)

    def _check_spatial_bounds(self, ds: xr.Dataset, target_path: Path) -> str:
        return check_spatial_bounds(ds, target_path)

    def _check_anomaly(self, data: xr.DataArray,
                       valid_range: tuple[float, float]) -> str:
        return check_anomaly(data, valid_range)

    def _check_distribution(self, data: xr.DataArray) -> str:
        return check_distribution(data)

    def check_grid_consistency(
        self,
        paths_and_vars: list[tuple[Path, str]],
    ) -> dict[str, str]:
        return check_grid_consistency(paths_and_vars)
