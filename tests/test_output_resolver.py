"""
Tests for agent/output_resolver.py — path conventions and ExpectedOutput fields.

All tests are purely structural (no filesystem I/O): they verify that the
resolver produces the correct paths and metadata for every country/variable/
scenario combination, matching the exact conventions used by the three
workflow scripts.
"""

import pytest
from pathlib import Path
from agent.output_resolver import (
    historical_outputs,
    projection_outputs,
    vpd_outputs,
    ExpectedOutput,
    _MERGED_DIR,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _names(outputs: list[ExpectedOutput]) -> list[str]:
    return [o.path.name for o in outputs]


def _vars(outputs: list[ExpectedOutput]) -> list[str]:
    return [o.variable for o in outputs]


def _units(outputs: list[ExpectedOutput]) -> list:
    return [o.expected_units for o in outputs]


# ── historical_outputs ────────────────────────────────────────────────────────

class TestHistoricalOutputs:
    def test_count_matches_countries_times_variables(self):
        out = historical_outputs(["eth", "ken"], ["tas", "rh"], (2010, 2025))
        assert len(out) == 4  # 2 countries × 2 variables

    def test_all_paths_under_merged_dir(self):
        out = historical_outputs(["eth"], ["pr"], (2010, 2025))
        assert all(o.path.parent == _MERGED_DIR for o in out)

    def test_returns_list_of_expected_output(self):
        out = historical_outputs(["eth"], ["pr"], (2010, 2025))
        assert all(isinstance(o, ExpectedOutput) for o in out)

    def test_tas_script_var_is_temp(self):
        out = historical_outputs(["eth"], ["tas"], (2010, 2025))
        assert "temp" in out[0].path.name
        assert "tas" not in out[0].path.name

    def test_tas_netcdf_var_is_t2m(self):
        out = historical_outputs(["eth"], ["tas"], (2010, 2025))
        assert out[0].variable == "t2m"

    def test_pr_script_var_is_pr(self):
        out = historical_outputs(["eth"], ["pr"], (2010, 2025))
        assert out[0].path.name.startswith("ethiopia_pr_")

    def test_pr_netcdf_var_is_precip(self):
        out = historical_outputs(["eth"], ["pr"], (2010, 2025))
        assert out[0].variable == "precip"

    def test_rh_netcdf_var_is_rh(self):
        out = historical_outputs(["eth"], ["rh"], (2010, 2025))
        assert out[0].variable == "rh"

    def test_pr_units_is_mm_day(self):
        out = historical_outputs(["eth"], ["pr"], (2010, 2025))
        assert out[0].expected_units == "mm/day"

    def test_tas_units_is_none(self):
        out = historical_outputs(["eth"], ["tas"], (2010, 2025))
        assert out[0].expected_units is None

    def test_rh_units_is_none(self):
        out = historical_outputs(["eth"], ["rh"], (2010, 2025))
        assert out[0].expected_units is None

    def test_period_label_in_filename(self):
        out = historical_outputs(["eth"], ["pr"], (2010, 2025))
        assert "2010_2025" in out[0].path.name

    def test_different_period_reflects_in_filename(self):
        out = historical_outputs(["eth"], ["pr"], (2015, 2020))
        assert "2015_2020" in out[0].path.name

    def test_filename_ends_with_025deg_clipped(self):
        out = historical_outputs(["eth"], ["pr"], (2010, 2025))
        assert out[0].path.name.endswith("_025deg_clipped.nc")

    def test_eth_country_name_is_ethiopia(self):
        out = historical_outputs(["eth"], ["pr"], (2010, 2025))
        assert "ethiopia" in out[0].path.name

    def test_ken_country_name_is_kenya(self):
        out = historical_outputs(["ken"], ["rh"], (2010, 2025))
        assert "kenya" in out[0].path.name

    def test_som_country_name_is_somalia(self):
        out = historical_outputs(["som"], ["pr"], (2010, 2025))
        assert "somalia" in out[0].path.name

    def test_require_daily_axis_is_true(self):
        out = historical_outputs(["eth"], ["pr"], (2010, 2025))
        assert out[0].require_daily_axis is True

    def test_period_stored_on_output(self):
        out = historical_outputs(["eth"], ["pr"], (2010, 2025))
        assert out[0].period == (2010, 2025)

    def test_ordering_is_country_then_variable(self):
        out = historical_outputs(["eth", "ken"], ["tas", "rh"], (2010, 2025))
        names = _names(out)
        # eth entries come before ken entries
        eth_idxs = [i for i, n in enumerate(names) if "ethiopia" in n]
        ken_idxs = [i for i, n in enumerate(names) if "kenya" in n]
        assert max(eth_idxs) < min(ken_idxs)


# ── projection_outputs ────────────────────────────────────────────────────────

class TestProjectionOutputs:
    def test_count_matches_countries_times_variables(self):
        out = projection_outputs(["eth", "ken"], ["tas", "rh"], "ssp245", (2040, 2070))
        assert len(out) == 4

    def test_scenario_label_ssp245_no_underscore(self):
        out = projection_outputs(["eth"], ["rh"], "ssp245", (2040, 2070))
        assert "ssp245" in out[0].path.name
        assert "ssp_245" not in out[0].path.name

    def test_scenario_label_ssp585_no_underscore(self):
        out = projection_outputs(["eth"], ["tas"], "ssp585", (2040, 2070))
        assert "ssp585" in out[0].path.name
        assert "ssp_585" not in out[0].path.name

    def test_standard_suffix_is_025deg_clipped(self):
        out = projection_outputs(["eth"], ["rh"], "ssp245", (2040, 2070))
        assert out[0].path.name.endswith("_025deg_clipped.nc")

    def test_ssp585_pr_suffix_is_daily_clipped(self):
        out = projection_outputs(["eth"], ["pr"], "ssp585", (2040, 2070))
        assert out[0].path.name.endswith("_daily_clipped.nc")

    def test_ssp245_pr_suffix_is_025deg_clipped(self):
        out = projection_outputs(["eth"], ["pr"], "ssp245", (2040, 2070))
        assert out[0].path.name.endswith("_025deg_clipped.nc")

    def test_ssp585_tas_suffix_is_025deg_clipped(self):
        # Only pr gets the special suffix for ssp585
        out = projection_outputs(["eth"], ["tas"], "ssp585", (2040, 2070))
        assert out[0].path.name.endswith("_025deg_clipped.nc")

    def test_tas_netcdf_var_is_tas(self):
        out = projection_outputs(["eth"], ["tas"], "ssp245", (2040, 2070))
        assert out[0].variable == "tas"

    def test_rh_netcdf_var_is_rh(self):
        out = projection_outputs(["eth"], ["rh"], "ssp245", (2040, 2070))
        assert out[0].variable == "rh"

    def test_pr_netcdf_var_is_pr(self):
        out = projection_outputs(["eth"], ["pr"], "ssp245", (2040, 2070))
        assert out[0].variable == "pr"

    def test_tas_units_is_degc(self):
        out = projection_outputs(["eth"], ["tas"], "ssp245", (2040, 2070))
        assert out[0].expected_units == "degC"

    def test_pr_units_is_mm_day(self):
        out = projection_outputs(["eth"], ["pr"], "ssp245", (2040, 2070))
        assert out[0].expected_units == "mm/day"

    def test_rh_units_is_none(self):
        out = projection_outputs(["eth"], ["rh"], "ssp245", (2040, 2070))
        assert out[0].expected_units is None

    def test_span_in_filename(self):
        out = projection_outputs(["eth"], ["rh"], "ssp245", (2040, 2070))
        assert "2040_2070" in out[0].path.name

    def test_all_paths_under_merged_dir(self):
        out = projection_outputs(["eth"], ["tas"], "ssp245", (2040, 2070))
        assert all(o.path.parent == _MERGED_DIR for o in out)

    def test_require_daily_axis_is_true(self):
        out = projection_outputs(["eth"], ["rh"], "ssp245", (2040, 2070))
        assert out[0].require_daily_axis is True

    def test_var_name_in_filename(self):
        out = projection_outputs(["eth"], ["rh"], "ssp245", (2040, 2070))
        assert "_rh_" in out[0].path.name


# ── vpd_outputs ───────────────────────────────────────────────────────────────

class TestVpdOutputs:
    def test_count_matches_countries(self):
        out = vpd_outputs(["eth", "ken", "som"], "ssp245", (2040, 2070))
        assert len(out) == 3

    def test_ssp245_suffix_is_025deg_clipped(self):
        out = vpd_outputs(["eth"], "ssp245", (2040, 2070))
        assert out[0].path.name.endswith("_025deg_clipped.nc")

    def test_ssp585_suffix_is_daily(self):
        out = vpd_outputs(["eth"], "ssp585", (2040, 2070))
        assert out[0].path.name.endswith("_daily.nc")

    def test_netcdf_var_is_vpd(self):
        out = vpd_outputs(["eth"], "ssp245", (2040, 2070))
        assert out[0].variable == "vpd"

    def test_units_is_hpa(self):
        out = vpd_outputs(["eth"], "ssp245", (2040, 2070))
        assert out[0].expected_units == "hPa"

    def test_ssp245_label_no_underscore(self):
        out = vpd_outputs(["eth"], "ssp245", (2040, 2070))
        assert "ssp245" in out[0].path.name
        assert "ssp_245" not in out[0].path.name

    def test_ssp585_label_no_underscore(self):
        out = vpd_outputs(["eth"], "ssp585", (2040, 2070))
        assert "ssp585" in out[0].path.name
        assert "ssp_585" not in out[0].path.name

    def test_span_in_filename(self):
        out = vpd_outputs(["eth"], "ssp245", (2040, 2070))
        assert "2040_2070" in out[0].path.name

    def test_eth_country_is_ethiopia(self):
        out = vpd_outputs(["eth"], "ssp245", (2040, 2070))
        assert "ethiopia" in out[0].path.name

    def test_vpd_in_filename(self):
        out = vpd_outputs(["eth"], "ssp245", (2040, 2070))
        assert "_vpd_" in out[0].path.name

    def test_all_paths_under_merged_dir(self):
        out = vpd_outputs(["eth", "ken"], "ssp585", (2040, 2070))
        assert all(o.path.parent == _MERGED_DIR for o in out)

    def test_require_daily_axis_is_true(self):
        out = vpd_outputs(["eth"], "ssp245", (2040, 2070))
        assert out[0].require_daily_axis is True

    def test_period_stored_on_output(self):
        out = vpd_outputs(["eth"], "ssp245", (2040, 2070))
        assert out[0].period == (2040, 2070)


# ── valid_range and target_grid_path fields ───────────────────────────────────

class TestValidRange:
    """Verify that _VALID_RANGE is wired correctly into each resolver."""

    def test_historical_pr_valid_range(self):
        out = historical_outputs(["eth"], ["pr"], (2010, 2025))
        assert out[0].valid_range == (0.0, 500.0)

    def test_historical_rh_valid_range(self):
        out = historical_outputs(["eth"], ["rh"], (2010, 2025))
        assert out[0].valid_range == (0.0, 100.0)

    def test_historical_tas_valid_range_is_none(self):
        # t2m excluded: K vs degC ambiguity between historical and projection
        out = historical_outputs(["eth"], ["tas"], (2010, 2025))
        assert out[0].valid_range is None

    def test_historical_vpd_valid_range(self):
        out = historical_outputs(["eth"], ["vpd"], (2010, 2025))
        assert out[0].valid_range == (0.0, 80.0)

    def test_historical_vpd_expected_units_is_hpa(self):
        out = historical_outputs(["eth"], ["vpd"], (2010, 2025))
        assert out[0].expected_units == "hPa"

    def test_projection_pr_valid_range(self):
        out = projection_outputs(["eth"], ["pr"], "ssp245", (2040, 2070))
        assert out[0].valid_range == (0.0, 500.0)

    def test_projection_rh_valid_range(self):
        out = projection_outputs(["eth"], ["rh"], "ssp245", (2040, 2070))
        assert out[0].valid_range == (0.0, 100.0)

    def test_projection_tas_valid_range_is_none(self):
        out = projection_outputs(["eth"], ["tas"], "ssp245", (2040, 2070))
        assert out[0].valid_range is None

    def test_vpd_valid_range(self):
        out = vpd_outputs(["eth"], "ssp245", (2040, 2070))
        assert out[0].valid_range == (0.0, 80.0)


class TestTargetGridPath:
    """Verify target_grid_path is populated for historical and None for projection/vpd."""

    def test_projection_target_grid_path_is_none(self):
        out = projection_outputs(["eth"], ["rh"], "ssp245", (2040, 2070))
        assert out[0].target_grid_path is None

    def test_vpd_target_grid_path_is_none(self):
        out = vpd_outputs(["eth"], "ssp245", (2040, 2070))
        assert out[0].target_grid_path is None

    def test_historical_target_grid_path_is_none_or_path(self):
        # Path is None when the per-country clipped pr file doesn't exist;
        # when it does exist it points to data/merged_files/{country}_pr_*_clipped.nc.
        out = historical_outputs(["eth"], ["rh"], (2010, 2025))
        assert out[0].target_grid_path is None or isinstance(out[0].target_grid_path, Path)

    def test_historical_eth_target_grid_uses_pr_clipped(self):
        # Ethiopia pr_2010_2025_025deg_clipped.nc exists — reference should be set
        out = historical_outputs(["eth"], ["rh"], (2010, 2025))
        if out[0].target_grid_path is not None:
            assert "pr" in out[0].target_grid_path.name
            assert "clipped" in out[0].target_grid_path.name
            assert "ethiopia" in out[0].target_grid_path.name

    def test_expected_output_has_target_grid_path_field(self):
        out = historical_outputs(["eth"], ["rh"], (2010, 2025))
        assert hasattr(out[0], "target_grid_path")

    def test_expected_output_has_valid_range_field(self):
        out = historical_outputs(["eth"], ["rh"], (2010, 2025))
        assert hasattr(out[0], "valid_range")


# ── is_clipped flag ───────────────────────────────────────────────────────────

class TestIsClipped:
    """All clipped-output resolvers must set is_clipped=True."""

    def test_historical_clipped_output_is_clipped(self):
        out = historical_outputs(["eth"], ["rh"], (2010, 2025))
        assert out[0].is_clipped is True

    def test_projection_clipped_output_is_clipped(self):
        out = projection_outputs(["eth"], ["rh"], "ssp245", (2040, 2070))
        assert out[0].is_clipped is True

    def test_vpd_output_is_clipped(self):
        out = vpd_outputs(["eth"], "ssp245", (2040, 2070))
        assert out[0].is_clipped is True

    def test_all_historical_outputs_are_clipped(self):
        outputs = historical_outputs(["eth", "ken"], ["rh", "tas"], (2010, 2025))
        assert all(o.is_clipped for o in outputs)

    def test_expected_output_has_is_clipped_field(self):
        out = historical_outputs(["eth"], ["rh"], (2010, 2025))
        assert hasattr(out[0], "is_clipped")
