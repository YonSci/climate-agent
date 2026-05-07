"""
validation_engine.py — Structured validation checks for NetCDF pipeline outputs.

ValidationEngine.validate() runs all applicable checks and returns a dict whose
keys match the 'validation' object in run_manifest_schema.json.

Check result values: "OK" | "FAIL" | "SKIP" | "WARN"
"""

from __future__ import annotations
import logging
from pathlib import Path

import numpy as np
import xarray as xr

from agent.policy import checks_to_skip

logger = logging.getLogger(__name__)

_TIME_CANDIDATES = ("time", "valid_time")
_LAT_CANDIDATES  = ("lat", "latitude")
_LON_CANDIDATES  = ("lon", "longitude")

# Minimum expected spread (p95 − p05) by NetCDF variable name.
# A spread below this threshold suggests a constant or near-constant field,
# which typically indicates a processing error (e.g. a merge that repeated one
# timestep, or a unit conversion that collapsed all values to zero).
_MIN_SPREAD: dict[str, float] = {
    "precip": 0.01,   # mm/day — even on dry days there is spatial variation
    "pr":     0.01,
    "rh":     2.0,    # % — relative humidity always varies by at least 2pp
    "hurs":   2.0,
    "vpd":    0.05,   # hPa
    "tas":    0.5,    # K or degC — temperature always has spatial gradient
    "t2m":    0.5,
}


def _detect(ds: xr.Dataset, candidates: tuple[str, ...]) -> str | None:
    for name in candidates:
        if name in ds.coords or name in ds.dims:
            return name
    return None


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
                if variable not in ds.data_vars:
                    results["variable_present"] = "FAIL"
                    results["notes"] = (
                        f"Variable '{variable}' not found. "
                        f"Available: {list(ds.data_vars)}"
                    )
                    return results
                results["variable_present"] = "OK"

                data = ds[variable]

                # 3 — non-NaN coverage (≥80% of pixels must be finite)
                results["non_nan_coverage"] = self._check_non_nan(ds, data, is_clipped)

                # 4 — time coverage
                time_dim = _detect(ds, _TIME_CANDIDATES)
                results["time_coverage"] = (
                    self._check_time_coverage(ds, time_dim, period)
                    if time_dim else "FAIL"
                )

                # 5 — daily axis (optional, skippable)
                if require_daily_axis and "daily_axis" not in self._skip:
                    results["daily_axis"] = (
                        self._check_daily_axis(ds, time_dim) if time_dim else "FAIL"
                    )
                else:
                    results["daily_axis"] = "SKIP"

                # 6 — units
                results["units"] = (
                    self._check_units(data, expected_units)
                    if expected_units
                    else "SKIP"
                )

                # 7 — grid_match (skippable in fast mode)
                if "grid_match" not in self._skip and target_grid_path:
                    results["grid_match"] = self._check_grid_match(ds, target_grid_path)
                else:
                    results["grid_match"] = "SKIP"

                # 8 — spatial_bounds (skippable in fast mode)
                if "spatial_bounds" not in self._skip and target_grid_path:
                    results["spatial_bounds"] = self._check_spatial_bounds(
                        ds, target_grid_path
                    )
                else:
                    results["spatial_bounds"] = "SKIP"

                # 9 — anomaly / outlier detection (never aborts the run)
                results["anomaly"] = (
                    self._check_anomaly(data, valid_range)
                    if valid_range is not None
                    else "SKIP"
                )

                # 10 — distribution check: flat/saturated data (never aborts)
                results["distribution"] = self._check_distribution(data)

        except Exception as exc:
            logger.warning(f"ValidationEngine error on {path}: {exc}")
            results.setdefault("non_nan_coverage", "FAIL")
            results["notes"] = f"Unexpected validation error: {exc}"

        return results

    # ── Individual checks ─────────────────────────────────────────────────────

    def _check_non_nan(self, ds: xr.Dataset, data: xr.DataArray,
                       is_clipped: bool = False) -> str:
        if any(size == 0 for size in ds.sizes.values()):
            return "FAIL"
        if data.size == 0:
            return "FAIL"
        finite_count = int(data.count().item())
        if finite_count == 0:
            return "FAIL"

        if is_clipped:
            # For country-masked outputs, the bounding box contains ocean / outside-border
            # pixels that are always NaN. Measure coverage relative to land pixels:
            # land pixel = any grid cell that is non-NaN in at least one time step.
            time_dim = _detect(ds, _TIME_CANDIDATES)
            if time_dim and data.sizes.get(time_dim, 0) > 1:
                land_mask = data.count(dim=time_dim) > 0
                n_land = int(land_mask.sum().item())
                if n_land == 0:
                    return "FAIL"
                n_time = data.sizes[time_dim]
                denominator = n_land * n_time
            else:
                # No time dimension or single step — fall back to spatial land pixels
                land_mask = np.isfinite(data.values)
                n_land = int(land_mask.sum())
                denominator = max(n_land, 1)
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

    def _check_time_coverage(self, ds: xr.Dataset, time_dim: str,
                              period: tuple[int, int]) -> str:
        try:
            years = ds[time_dim].dt.year.values
            year_min, year_max = int(years.min()), int(years.max())
            start, end = period
            if year_min < start or year_max > end:
                return "FAIL"
            # Warn if coverage is partial within the requested window
            expected = set(range(start, end + 1))
            found    = set(years.tolist())
            if not expected.issubset(found):
                return "WARN"
            return "OK"
        except Exception:
            return "FAIL"

    def _check_daily_axis(self, ds: xr.Dataset, time_dim: str) -> str:
        try:
            values = ds[time_dim].values
            if values.size < 2:
                return "OK"
            diffs = np.diff(values).astype("timedelta64[D]")
            if np.all(diffs == np.timedelta64(1, "D")):
                return "OK"
            return "FAIL"
        except Exception:
            return "FAIL"

    def _check_units(self, data: xr.DataArray, expected: str) -> str:
        actual = str(data.attrs.get("units", "")).strip()
        if actual == expected:
            return "OK"
        if actual == "":
            return "WARN"
        return "FAIL"

    def _check_grid_match(self, ds: xr.Dataset, target_path: Path) -> str:
        try:
            with xr.open_dataset(target_path) as tgt:
                out_lat = _detect(ds,  _LAT_CANDIDATES)
                out_lon = _detect(ds,  _LON_CANDIDATES)
                tgt_lat = _detect(tgt, _LAT_CANDIDATES)
                tgt_lon = _detect(tgt, _LON_CANDIDATES)
                if not all([out_lat, out_lon, tgt_lat, tgt_lon]):
                    return "FAIL"
                if (ds.sizes[out_lat] != tgt.sizes[tgt_lat] or
                        ds.sizes[out_lon] != tgt.sizes[tgt_lon]):
                    return "FAIL"
                if not np.allclose(ds[out_lat].values, tgt[tgt_lat].values):
                    return "FAIL"
                if not np.allclose(ds[out_lon].values, tgt[tgt_lon].values):
                    return "FAIL"
            return "OK"
        except Exception:
            return "FAIL"

    def _check_anomaly(self, data: xr.DataArray,
                       valid_range: tuple[float, float]) -> str:
        """
        Flag out-of-range pixel counts. Returns WARN (never FAIL) so the run
        is never aborted by anomalies — they are logged for review only.
        """
        lo, hi = valid_range
        try:
            vals = data.values.astype(float)
            finite_mask = np.isfinite(vals)
            finite_vals = vals[finite_mask]
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

    def _check_distribution(self, data: xr.DataArray) -> str:
        """
        Detect pathological value distributions that survive range checks:

        1. Flat field  — p95 − p05 below the variable's minimum expected spread.
           Suggests repeated timesteps, a bad merge, or a zeroed-out processing step.

        2. Saturated field — p05 is at the variable's valid_min OR p95 is at
           valid_max (hard-clipping artifact).  Uses _MIN_SPREAD keys to identify
           the variable; unknown variable names → SKIP.

        Always returns WARN (never FAIL) — never aborts the run.
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
            p05, p95 = float(np.percentile(finite_vals, 5)), float(np.percentile(finite_vals, 95))
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

    def check_grid_consistency(
        self,
        paths_and_vars: list[tuple[Path, str]],
    ) -> dict[str, str]:
        """
        Check that all files in *paths_and_vars* share the same lat/lon grid.

        The first existing file is used as the reference. Each subsequent file
        is compared against it. Missing files are skipped (existence check is
        a separate concern).

        Returns
        -------
        dict mapping filename → "OK" | "FAIL" | "SKIP" | "MISSING"
        A summary key "overall" is also added: "OK" if all present files pass,
        "FAIL" if any fail, "SKIP" if fewer than two files are present.
        """
        results: dict[str, str] = {}
        found_reference = False
        ref_lat_vals = ref_lon_vals = None
        ref_file = None

        present = [(p, v) for p, v in paths_and_vars if p.exists()]
        if len(present) < 2:
            for p, _ in paths_and_vars:
                results[p.name] = "MISSING" if not p.exists() else "SKIP"
            results["overall"] = "SKIP"
            return results

        for path, _var in present:
            try:
                with xr.open_dataset(path) as ds:
                    lat = _detect(ds, _LAT_CANDIDATES)
                    lon = _detect(ds, _LON_CANDIDATES)
                    if not lat or not lon:
                        results[path.name] = "FAIL"
                        continue
                    if not found_reference:
                        ref_lat_vals = ds[lat].values.copy()
                        ref_lon_vals = ds[lon].values.copy()
                        ref_file = path.name
                        found_reference = True
                        results[path.name] = "OK"
                        continue
                    # Compare against reference
                    if (ds.sizes[lat] != len(ref_lat_vals) or
                            ds.sizes[lon] != len(ref_lon_vals)):
                        results[path.name] = "FAIL"
                        logger.warning(
                            f"Grid consistency FAIL: {path.name} grid shape "
                            f"({ds.sizes[lat]}×{ds.sizes[lon]}) differs from "
                            f"reference {ref_file} "
                            f"({len(ref_lat_vals)}×{len(ref_lon_vals)})"
                        )
                    elif (not np.allclose(ds[lat].values, ref_lat_vals) or
                          not np.allclose(ds[lon].values, ref_lon_vals)):
                        results[path.name] = "FAIL"
                        logger.warning(
                            f"Grid consistency FAIL: {path.name} lat/lon values "
                            f"differ from reference {ref_file}"
                        )
                    else:
                        results[path.name] = "OK"
            except Exception as exc:
                logger.warning(f"Grid consistency error on {path.name}: {exc}")
                results[path.name] = "FAIL"

        for path, _ in paths_and_vars:
            if path.name not in results:
                results[path.name] = "MISSING"

        any_fail = any(v == "FAIL" for v in results.values())
        results["overall"] = "FAIL" if any_fail else "OK"
        return results

    def _check_spatial_bounds(self, ds: xr.Dataset, target_path: Path) -> str:
        try:
            with xr.open_dataset(target_path) as tgt:
                out_lat = _detect(ds,  _LAT_CANDIDATES)
                out_lon = _detect(ds,  _LON_CANDIDATES)
                tgt_lat = _detect(tgt, _LAT_CANDIDATES)
                tgt_lon = _detect(tgt, _LON_CANDIDATES)
                if not all([out_lat, out_lon, tgt_lat, tgt_lon]):
                    return "FAIL"
                lat_vals = np.asarray(ds[out_lat].values,  dtype=float)
                lon_vals = np.asarray(ds[out_lon].values,  dtype=float)
                t_lat    = np.asarray(tgt[tgt_lat].values, dtype=float)
                t_lon    = np.asarray(tgt[tgt_lon].values, dtype=float)
                if (ds.sizes[out_lat] > tgt.sizes[tgt_lat] or
                        ds.sizes[out_lon] > tgt.sizes[tgt_lon]):
                    return "FAIL"
                if lat_vals.min() < t_lat.min() or lat_vals.max() > t_lat.max():
                    return "FAIL"
                if lon_vals.min() < t_lon.min() or lon_vals.max() > t_lon.max():
                    return "FAIL"
            return "OK"
        except Exception:
            return "FAIL"
