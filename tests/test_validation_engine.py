"""
Tests for agent/validation_engine.py using real NetCDF files and
synthetic in-memory datasets.

All fixtures that require real data files call pytest.skip() automatically
via conftest.py if the file is not present.
"""

from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
import xarray as xr

from agent.validation_engine import ValidationEngine


# ── Synthetic dataset helpers ─────────────────────────────────────────────────

def _write_synthetic(tmp_path: Path, data: np.ndarray, var: str = "rh",
                     year: int = 2010) -> Path:
    """Write a small NetCDF file with a daily time axis derived from *data* shape."""
    path = tmp_path / f"synthetic_{var}.nc"
    n_time, n_lat, n_lon = data.shape
    times = pd.date_range(f"{year}-01-01", periods=n_time, freq="D")
    da = xr.DataArray(
        data,
        dims=["time", "lat", "lon"],
        coords={
            "time": times,
            "lat":  np.arange(n_lat, dtype=float),
            "lon":  np.arange(n_lon, dtype=float),
        },
        name=var,
    )
    xr.Dataset({var: da}).to_netcdf(path)
    return path


# ── Helpers ───────────────────────────────────────────────────────────────────

def _first_variable(path: Path) -> str:
    with xr.open_dataset(path) as ds:
        return next(iter(ds.data_vars))


def _year_range(path: Path) -> tuple[int, int]:
    with xr.open_dataset(path) as ds:
        for coord in ("time", "valid_time"):
            if coord in ds.coords:
                years = ds[coord].dt.year.values
                return int(years.min()), int(years.max())
    raise ValueError(f"No time coordinate found in {path}")


# ── existence checks ──────────────────────────────────────────────────────────

class TestExistence:
    def test_existing_file_ok(self, chirps_eth_2010):
        ve = ValidationEngine()
        var = _first_variable(chirps_eth_2010)
        result = ve.validate(chirps_eth_2010, variable=var,
                             expected_units=None, period=(2010, 2010))
        assert result["existence"] == "OK"

    def test_missing_file_fails(self, tmp_path):
        ve = ValidationEngine()
        result = ve.validate(tmp_path / "nonexistent.nc",
                             variable="x", expected_units=None, period=(2010, 2010))
        assert result["existence"] == "FAIL"
        assert "existence" in result


# ── variable present check ────────────────────────────────────────────────────

class TestVariablePresent:
    def test_correct_variable_ok(self, chirps_eth_2010):
        var = _first_variable(chirps_eth_2010)
        ve = ValidationEngine()
        result = ve.validate(chirps_eth_2010, variable=var,
                             expected_units=None, period=(2010, 2010))
        assert result["variable_present"] == "OK"

    def test_wrong_variable_fails(self, chirps_eth_2010):
        ve = ValidationEngine()
        result = ve.validate(chirps_eth_2010, variable="nonexistent_var",
                             expected_units=None, period=(2010, 2010))
        assert result["variable_present"] == "FAIL"


# ── non-NaN coverage ──────────────────────────────────────────────────────────

class TestNonNanCoverage:
    def test_chirps_non_nan_check_runs(self, chirps_eth_2010):
        # Global CHIRPS has ~27% non-NaN (ocean masked) — legitimately below 80%.
        # The 80% threshold applies to clipped country outputs, not raw global files.
        # This test verifies the check runs and produces a valid result string.
        var = _first_variable(chirps_eth_2010)
        ve = ValidationEngine()
        result = ve.validate(chirps_eth_2010, variable=var,
                             expected_units=None, period=(2010, 2010))
        assert result["non_nan_coverage"] in ("OK", "FAIL")

    def test_isimip_hurs_has_finite_values(self, isimip_eth_ssp245_hurs):
        ve = ValidationEngine()
        result = ve.validate(isimip_eth_ssp245_hurs, variable="hurs",
                             expected_units=None, period=(2031, 2040))
        assert result["non_nan_coverage"] == "OK"


# ── time coverage ─────────────────────────────────────────────────────────────

class TestTimeCoverage:
    def test_chirps_2010_in_range(self, chirps_eth_2010):
        var = _first_variable(chirps_eth_2010)
        ve = ValidationEngine()
        result = ve.validate(chirps_eth_2010, variable=var,
                             expected_units=None, period=(2010, 2010))
        assert result["time_coverage"] in ("OK", "WARN")

    def test_chirps_wrong_year_fails(self, chirps_eth_2010):
        var = _first_variable(chirps_eth_2010)
        ve = ValidationEngine()
        # File is 2010 but we ask for 2020 only
        result = ve.validate(chirps_eth_2010, variable=var,
                             expected_units=None, period=(2020, 2020))
        assert result["time_coverage"] == "FAIL"

    def test_isimip_period_covered(self, isimip_eth_ssp245_hurs):
        ve = ValidationEngine()
        result = ve.validate(isimip_eth_ssp245_hurs, variable="hurs",
                             expected_units=None, period=(2031, 2040))
        assert result["time_coverage"] in ("OK", "WARN")

    def test_isimip_wider_period_warns_or_fails(self, isimip_eth_ssp245_hurs):
        ve = ValidationEngine()
        # Request 2031-2070 but file only has 2031-2040
        result = ve.validate(isimip_eth_ssp245_hurs, variable="hurs",
                             expected_units=None, period=(2031, 2070))
        assert result["time_coverage"] in ("WARN", "FAIL")


# ── daily axis check ──────────────────────────────────────────────────────────

class TestDailyAxis:
    def test_chirps_is_daily(self, chirps_eth_2010):
        var = _first_variable(chirps_eth_2010)
        ve = ValidationEngine()
        result = ve.validate(chirps_eth_2010, variable=var,
                             expected_units=None, period=(2010, 2010),
                             require_daily_axis=True)
        assert result["daily_axis"] == "OK"

    def test_isimip_ssp245_hurs_is_daily(self, isimip_eth_ssp245_hurs):
        ve = ValidationEngine()
        result = ve.validate(isimip_eth_ssp245_hurs, variable="hurs",
                             expected_units=None, period=(2031, 2040),
                             require_daily_axis=True)
        assert result["daily_axis"] == "OK"

    def test_daily_axis_skipped_when_not_required(self, chirps_eth_2010):
        var = _first_variable(chirps_eth_2010)
        ve = ValidationEngine()
        result = ve.validate(chirps_eth_2010, variable=var,
                             expected_units=None, period=(2010, 2010),
                             require_daily_axis=False)
        assert result["daily_axis"] == "SKIP"


# ── units check ───────────────────────────────────────────────────────────────

class TestUnits:
    def test_units_skipped_when_none(self, chirps_eth_2010):
        var = _first_variable(chirps_eth_2010)
        ve = ValidationEngine()
        result = ve.validate(chirps_eth_2010, variable=var,
                             expected_units=None, period=(2010, 2010))
        assert result["units"] == "SKIP"

    def test_wrong_units_fails(self, chirps_eth_2010):
        var = _first_variable(chirps_eth_2010)
        ve = ValidationEngine()
        result = ve.validate(chirps_eth_2010, variable=var,
                             expected_units="Kelvin", period=(2010, 2010))
        # either FAIL or WARN (if units attr missing)
        assert result["units"] in ("FAIL", "WARN")


# ── grid / spatial checks skipped in fast mode ───────────────────────────────

class TestFastMode:
    def test_grid_match_skipped_in_fast_mode(self, chirps_eth_2010):
        var = _first_variable(chirps_eth_2010)
        ve = ValidationEngine(fast_mode=True)
        result = ve.validate(chirps_eth_2010, variable=var,
                             expected_units=None, period=(2010, 2010),
                             target_grid_path=chirps_eth_2010)
        assert result["grid_match"]     == "SKIP"
        assert result["spatial_bounds"] == "SKIP"

    def test_grid_match_runs_in_strict_mode(self, chirps_eth_2010):
        var = _first_variable(chirps_eth_2010)
        ve = ValidationEngine(fast_mode=False)
        result = ve.validate(chirps_eth_2010, variable=var,
                             expected_units=None, period=(2010, 2010),
                             target_grid_path=chirps_eth_2010)
        # Self-comparison must pass
        assert result["grid_match"]     == "OK"
        assert result["spatial_bounds"] == "OK"

    def test_no_target_grid_skips_both_checks_in_strict_mode(self, tmp_path):
        data = np.ones((365, 4, 4), dtype=float)
        path = _write_synthetic(tmp_path, data)
        ve = ValidationEngine(fast_mode=False)
        result = ve.validate(path, variable="rh", expected_units=None,
                             period=(2010, 2010), target_grid_path=None)
        assert result["grid_match"]     == "SKIP"
        assert result["spatial_bounds"] == "SKIP"


# ── synthetic non-NaN coverage ────────────────────────────────────────────────

class TestNonNanCoverageSynthetic:
    """Verify the 80% threshold logic using in-memory datasets (no real data needed)."""

    def test_above_80_percent_is_ok(self, tmp_path):
        # 10 pixels; 1 NaN → 90% non-NaN
        data = np.ones((1, 2, 5), dtype=float)
        data[0, 0, 0] = np.nan
        path = _write_synthetic(tmp_path, data)
        result = ValidationEngine().validate(
            path, variable="rh", expected_units=None, period=(2010, 2010))
        assert result["non_nan_coverage"] == "OK"

    def test_below_80_percent_is_fail(self, tmp_path):
        # 10 pixels; 3 NaN → 70% non-NaN
        data = np.ones((1, 2, 5), dtype=float)
        data[0, 0, :3] = np.nan
        path = _write_synthetic(tmp_path, data)
        result = ValidationEngine().validate(
            path, variable="rh", expected_units=None, period=(2010, 2010))
        assert result["non_nan_coverage"] == "FAIL"

    def test_exactly_80_percent_is_ok(self, tmp_path):
        # 10 pixels; 2 NaN → exactly 80% (coverage NOT < 0.80 → OK)
        data = np.ones((1, 2, 5), dtype=float)
        data[0, 0, :2] = np.nan
        path = _write_synthetic(tmp_path, data)
        result = ValidationEngine().validate(
            path, variable="rh", expected_units=None, period=(2010, 2010))
        assert result["non_nan_coverage"] == "OK"

    def test_all_nan_is_fail(self, tmp_path):
        data = np.full((1, 2, 5), np.nan)
        path = _write_synthetic(tmp_path, data)
        result = ValidationEngine().validate(
            path, variable="rh", expected_units=None, period=(2010, 2010))
        assert result["non_nan_coverage"] == "FAIL"

    def test_all_finite_is_ok(self, tmp_path):
        data = np.ones((365, 4, 4), dtype=float)
        path = _write_synthetic(tmp_path, data)
        result = ValidationEngine().validate(
            path, variable="rh", expected_units=None, period=(2010, 2010))
        assert result["non_nan_coverage"] == "OK"


# ── anomaly / valid_range check ───────────────────────────────────────────────

class TestAnomalyCheck:
    """Verify _check_anomaly via the valid_range parameter of validate()."""

    def _nc(self, tmp_path: Path, values: list) -> Path:
        data = np.array(values, dtype=float).reshape(1, 1, len(values))
        return _write_synthetic(tmp_path, data)

    def test_skip_when_valid_range_is_none(self, tmp_path):
        path = self._nc(tmp_path, [50.0, 60.0])
        result = ValidationEngine().validate(
            path, variable="rh", expected_units=None,
            period=(2010, 2010), valid_range=None)
        assert result["anomaly"] == "SKIP"

    def test_ok_when_all_in_range(self, tmp_path):
        path = self._nc(tmp_path, [20.0, 50.0, 80.0])
        result = ValidationEngine().validate(
            path, variable="rh", expected_units=None,
            period=(2010, 2010), valid_range=(0.0, 100.0))
        assert result["anomaly"] == "OK"

    def test_warn_when_values_out_of_range(self, tmp_path):
        path = self._nc(tmp_path, [50.0, 150.0])  # 150 > 100
        result = ValidationEngine().validate(
            path, variable="rh", expected_units=None,
            period=(2010, 2010), valid_range=(0.0, 100.0))
        assert result["anomaly"] == "WARN"

    def test_anomaly_never_returns_fail(self, tmp_path):
        path = self._nc(tmp_path, [-9999.0, 99999.0])
        result = ValidationEngine().validate(
            path, variable="rh", expected_units=None,
            period=(2010, 2010), valid_range=(0.0, 100.0))
        assert result["anomaly"] != "FAIL"

    def test_nan_pixels_ignored(self, tmp_path):
        # NaN should be filtered out; the only finite value (50) is in range
        path = self._nc(tmp_path, [np.nan, 50.0])
        result = ValidationEngine().validate(
            path, variable="rh", expected_units=None,
            period=(2010, 2010), valid_range=(0.0, 100.0))
        assert result["anomaly"] == "OK"

    def test_all_nan_gives_skip(self, tmp_path):
        path = self._nc(tmp_path, [np.nan, np.nan])
        result = ValidationEngine().validate(
            path, variable="rh", expected_units=None,
            period=(2010, 2010), valid_range=(0.0, 100.0))
        assert result["anomaly"] == "SKIP"

    def test_anomaly_key_present_with_valid_range(self, tmp_path):
        path = self._nc(tmp_path, [50.0])
        result = ValidationEngine().validate(
            path, variable="rh", expected_units=None,
            period=(2010, 2010), valid_range=(0.0, 100.0))
        assert "anomaly" in result

    def test_anomaly_key_present_without_valid_range(self, tmp_path):
        path = self._nc(tmp_path, [50.0])
        result = ValidationEngine().validate(
            path, variable="rh", expected_units=None,
            period=(2010, 2010), valid_range=None)
        assert "anomaly" in result


# ── distribution check ────────────────────────────────────────────────────────

class TestDistributionCheck:
    """_check_distribution — flat-field and saturation detection."""

    def _nc(self, tmp_path: Path, values: list, var: str = "rh") -> Path:
        data = np.array(values, dtype=float).reshape(1, 1, len(values))
        return _write_synthetic(tmp_path, data, var=var)

    def test_skip_for_unknown_variable(self, tmp_path):
        # Variable name not in _MIN_SPREAD → SKIP
        path = _write_synthetic(tmp_path, np.ones((1, 2, 5)), var="unknown_var")
        result = ValidationEngine().validate(
            path, variable="unknown_var", expected_units=None, period=(2010, 2010))
        assert result["distribution"] == "SKIP"

    def test_ok_for_well_spread_rh(self, tmp_path):
        # rh values spanning 0–100 → well above 2% minimum spread
        values = list(range(0, 101, 1))  # 101 values 0..100
        path = self._nc(tmp_path, values)
        result = ValidationEngine().validate(
            path, variable="rh", expected_units=None, period=(2010, 2010))
        assert result["distribution"] == "OK"

    def test_warn_for_flat_rh_field(self, tmp_path):
        # All values identical → p95 - p05 = 0 (below 2% minimum for rh)
        path = self._nc(tmp_path, [50.0] * 50)
        result = ValidationEngine().validate(
            path, variable="rh", expected_units=None, period=(2010, 2010))
        assert result["distribution"] == "WARN"

    def test_distribution_key_always_present(self, tmp_path):
        path = _write_synthetic(tmp_path, np.ones((1, 2, 5)), var="rh")
        result = ValidationEngine().validate(
            path, variable="rh", expected_units=None, period=(2010, 2010))
        assert "distribution" in result

    def test_distribution_never_returns_fail(self, tmp_path):
        # Even with a perfectly flat field distribution must not return FAIL
        path = self._nc(tmp_path, [0.0] * 20)
        result = ValidationEngine().validate(
            path, variable="rh", expected_units=None, period=(2010, 2010))
        assert result["distribution"] != "FAIL"

    def test_skip_when_too_few_finite_values(self, tmp_path):
        # Only 5 finite pixels — below the 10-pixel minimum for the check
        values = [50.0] * 5
        path = self._nc(tmp_path, values)
        result = ValidationEngine().validate(
            path, variable="rh", expected_units=None, period=(2010, 2010))
        assert result["distribution"] in ("OK", "SKIP", "WARN")  # no crash


# ── check_grid_consistency ────────────────────────────────────────────────────

class TestCheckGridConsistency:
    """ValidationEngine.check_grid_consistency — cross-file lat/lon matching."""

    def _make_nc(self, tmp_path: Path, name: str,
                 n_lat: int = 4, n_lon: int = 4,
                 lat_offset: float = 0.0) -> Path:
        data = np.ones((2, n_lat, n_lon), dtype=float)
        path = tmp_path / name
        times = pd.date_range("2010-01-01", periods=2, freq="D")
        da = xr.DataArray(
            data,
            dims=["time", "lat", "lon"],
            coords={
                "time": times,
                "lat":  np.arange(n_lat, dtype=float) + lat_offset,
                "lon":  np.arange(n_lon, dtype=float),
            },
            name="rh",
        )
        xr.Dataset({"rh": da}).to_netcdf(path)
        return path

    def test_skip_for_fewer_than_two_files(self, tmp_path):
        path = self._make_nc(tmp_path, "only.nc")
        ve = ValidationEngine()
        result = ve.check_grid_consistency([(path, "rh")])
        assert result["overall"] == "SKIP"

    def test_skip_when_no_files_exist(self, tmp_path):
        ve = ValidationEngine()
        result = ve.check_grid_consistency([
            (tmp_path / "missing_a.nc", "rh"),
            (tmp_path / "missing_b.nc", "rh"),
        ])
        assert result["overall"] == "SKIP"

    def test_ok_for_identical_grids(self, tmp_path):
        a = self._make_nc(tmp_path, "a.nc")
        b = self._make_nc(tmp_path, "b.nc")
        ve = ValidationEngine()
        result = ve.check_grid_consistency([(a, "rh"), (b, "rh")])
        assert result["overall"] == "OK"
        assert result["a.nc"] == "OK"
        assert result["b.nc"] == "OK"

    def test_fail_for_different_grid_shape(self, tmp_path):
        a = self._make_nc(tmp_path, "a.nc", n_lat=4, n_lon=4)
        b = self._make_nc(tmp_path, "b.nc", n_lat=6, n_lon=4)  # different lat size
        ve = ValidationEngine()
        result = ve.check_grid_consistency([(a, "rh"), (b, "rh")])
        assert result["overall"] == "FAIL"
        assert result["b.nc"] == "FAIL"

    def test_fail_for_different_lat_values(self, tmp_path):
        a = self._make_nc(tmp_path, "a.nc", lat_offset=0.0)
        b = self._make_nc(tmp_path, "b.nc", lat_offset=10.0)  # shifted lat
        ve = ValidationEngine()
        result = ve.check_grid_consistency([(a, "rh"), (b, "rh")])
        assert result["overall"] == "FAIL"

    def test_missing_file_marked_missing(self, tmp_path):
        a = self._make_nc(tmp_path, "a.nc")
        missing = tmp_path / "missing.nc"
        ve = ValidationEngine()
        result = ve.check_grid_consistency([(a, "rh"), (missing, "rh")])
        assert result["missing.nc"] == "MISSING"

    def test_overall_key_always_present(self, tmp_path):
        a = self._make_nc(tmp_path, "a.nc")
        b = self._make_nc(tmp_path, "b.nc")
        result = ValidationEngine().check_grid_consistency([(a, "rh"), (b, "rh")])
        assert "overall" in result

    def test_three_files_all_matching(self, tmp_path):
        paths = [self._make_nc(tmp_path, f"{c}.nc") for c in ("a", "b", "c")]
        result = ValidationEngine().check_grid_consistency(
            [(p, "rh") for p in paths]
        )
        assert result["overall"] == "OK"
        assert all(result[p.name] == "OK" for p in paths)


# ── is_clipped non-NaN coverage ───────────────────────────────────────────────

class TestNonNanCoverageClipped:
    """
    When is_clipped=True, non-NaN coverage is measured relative to land pixels
    (pixels that are non-NaN in at least one time step), not the full bounding box.
    """

    def _clipped_nc(self, tmp_path: Path, land_fraction: float,
                    n_time: int = 10, n_lat: int = 1, n_lon: int = 20) -> Path:
        """
        Build a file where (1 - land_fraction) of spatial pixels are always NaN
        (ocean masking) and all land pixels are fully finite.

        Uses flat indexing so n_ocean never exceeds n_lon.
        """
        n_spatial = n_lat * n_lon
        n_ocean = int(n_spatial * (1 - land_fraction))
        data = np.ones((n_time, n_lat, n_lon), dtype=float)
        flat = data.reshape(n_time, n_spatial)
        flat[:, :n_ocean] = np.nan
        return _write_synthetic(tmp_path, flat.reshape(n_time, n_lat, n_lon))

    def test_clipped_55pct_bbox_passes_when_is_clipped(self, tmp_path):
        # Mirrors Ethiopia RH: ~55% of bbox is land, all land pixels fully non-NaN.
        # Without is_clipped this FAIL (55% < 80%); with it, land coverage = 100% → OK.
        path = self._clipped_nc(tmp_path, land_fraction=0.55)
        result = ValidationEngine().validate(
            path, variable="rh", expected_units=None,
            period=(2010, 2010), is_clipped=True)
        assert result["non_nan_coverage"] == "OK"

    def test_clipped_55pct_bbox_fails_when_not_clipped(self, tmp_path):
        # Same file, is_clipped=False → measured vs full bbox → FAIL (55% < 80%)
        path = self._clipped_nc(tmp_path, land_fraction=0.55)
        result = ValidationEngine().validate(
            path, variable="rh", expected_units=None,
            period=(2010, 2010), is_clipped=False)
        assert result["non_nan_coverage"] == "FAIL"

    def test_clipped_land_pixels_with_partial_time_missing_fails(self, tmp_path):
        # Land pixels exist but last 5 of 10 time steps have 60% NaN on land → FAIL.
        # n_lat=1, n_lon=20: 9 ocean (always NaN), 11 land pixels.
        # First 5 time steps: all 11 land pixels non-NaN (55 finite).
        # Last  5 time steps: only 4 of 11 land pixels non-NaN (20 finite).
        # Total finite = 75; denominator = 11 * 10 = 110; coverage = 68% → FAIL.
        n_time, n_lat, n_lon = 10, 1, 20
        data = np.ones((n_time, n_lat, n_lon), dtype=float)
        flat = data.reshape(n_time, n_lat * n_lon)
        flat[:, :9] = np.nan          # 9 ocean pixels (always NaN)
        flat[5:, 9:16] = np.nan       # last 5 steps: 7 of 11 land pixels NaN
        data = flat.reshape(n_time, n_lat, n_lon)
        path = _write_synthetic(tmp_path, data)
        result = ValidationEngine().validate(
            path, variable="rh", expected_units=None,
            period=(2010, 2010), is_clipped=True)
        assert result["non_nan_coverage"] == "FAIL"

    def test_clipped_all_nan_fails(self, tmp_path):
        # All pixels NaN → FAIL regardless of is_clipped
        data = np.full((5, 3, 3), np.nan)
        path = _write_synthetic(tmp_path, data)
        result = ValidationEngine().validate(
            path, variable="rh", expected_units=None,
            period=(2010, 2010), is_clipped=True)
        assert result["non_nan_coverage"] == "FAIL"

    def test_clipped_default_is_false(self, tmp_path):
        # is_clipped defaults to False — existing 80%-of-bbox behaviour unchanged
        data = np.ones((1, 2, 5), dtype=float)
        data[0, 0, 0] = np.nan  # 90% non-NaN → OK with default threshold
        path = _write_synthetic(tmp_path, data)
        result = ValidationEngine().validate(
            path, variable="rh", expected_units=None, period=(2010, 2010))
        assert result["non_nan_coverage"] == "OK"
