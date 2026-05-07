"""
Tests for connectors/ — command builders and path resolvers.

All tests are purely structural: no subprocess is launched and no real
data files are required.
"""

from __future__ import annotations
import sys
from pathlib import Path

import pytest

from connectors.agera5_connector import (
    build_cmd as agera5_cmd,
    expected_path as agera5_path,
    year_range_cmds as agera5_range,
    SUPPORTED_VARIABLES,
)
from connectors.chirps_connector import (
    build_cmd as chirps_cmd,
    expected_path as chirps_path,
    year_range_cmds as chirps_range,
)
from connectors.isimip_connector import (
    source_dir,
    list_available_files,
    check_availability,
    AGENT_TO_ISIMIP,
    ISIMIP_TO_AGENT,
)


# ── agera5_connector ──────────────────────────────────────────────────────────

class TestAgera5Connector:
    def test_build_cmd_starts_with_python(self):
        assert agera5_cmd("rh", 2015)[0] == sys.executable

    def test_build_cmd_calls_agera5_download_script(self):
        assert "agera5_download.py" in agera5_cmd("rh", 2015)[1]

    def test_build_cmd_contains_variable_flag(self):
        cmd = agera5_cmd("tas", 2015)
        idx = cmd.index("--variable")
        assert cmd[idx + 1] == "tas"

    def test_build_cmd_contains_year_flag(self):
        cmd = agera5_cmd("rh", 2019)
        idx = cmd.index("--year")
        assert cmd[idx + 1] == "2019"

    def test_build_cmd_contains_outdir_flag(self):
        assert "--outdir" in agera5_cmd("rh", 2015)

    def test_expected_path_contains_variable(self):
        assert "rh" in str(agera5_path("rh", 2015))

    def test_expected_path_contains_year(self):
        assert "2015" in agera5_path("rh", 2015).name

    def test_expected_path_is_nc_file(self):
        assert agera5_path("tas", 2020).suffix == ".nc"

    def test_expected_path_is_absolute(self):
        assert agera5_path("rh", 2015).is_absolute()

    def test_unsupported_variable_raises_value_error(self):
        with pytest.raises(ValueError, match="unsupported variable"):
            agera5_cmd("pr", 2015)

    def test_vpd_is_supported(self):
        assert "vpd" in SUPPORTED_VARIABLES

    def test_year_range_cmds_count(self):
        assert len(agera5_range("rh", 2010, 2013)) == 4

    def test_year_range_cmds_years_in_order(self):
        cmds = agera5_range("rh", 2010, 2012)
        years = [c[c.index("--year") + 1] for c in cmds]
        assert years == ["2010", "2011", "2012"]

    def test_year_range_single_year_returns_one_cmd(self):
        assert len(agera5_range("tas", 2020, 2020)) == 1

    def test_outdir_is_parent_of_expected_path(self):
        cmd = agera5_cmd("rh", 2015)
        outdir = Path(cmd[cmd.index("--outdir") + 1])
        assert outdir == agera5_path("rh", 2015).parent


# ── chirps_connector ──────────────────────────────────────────────────────────

class TestChirpsConnector:
    def test_build_cmd_starts_with_python(self):
        assert chirps_cmd(2012)[0] == sys.executable

    def test_build_cmd_calls_download_chirps_script(self):
        assert "download_chirps.py" in chirps_cmd(2012)[1]

    def test_build_cmd_contains_year_flag(self):
        cmd = chirps_cmd(2012)
        idx = cmd.index("--year")
        assert cmd[idx + 1] == "2012"

    def test_build_cmd_contains_outdir_flag(self):
        assert "--outdir" in chirps_cmd(2012)

    def test_expected_path_contains_year(self):
        assert "2012" in chirps_path(2012).name

    def test_expected_path_is_nc_file(self):
        assert chirps_path(2012).suffix == ".nc"

    def test_expected_path_is_absolute(self):
        assert chirps_path(2012).is_absolute()

    def test_expected_path_contains_chirps(self):
        assert "chirps" in str(chirps_path(2012)).lower()

    def test_year_range_cmds_count(self):
        assert len(chirps_range(2010, 2014)) == 5

    def test_year_range_cmds_years_in_order(self):
        cmds = chirps_range(2010, 2011)
        years = [c[c.index("--year") + 1] for c in cmds]
        assert years == ["2010", "2011"]

    def test_outdir_is_parent_of_expected_path(self):
        cmd = chirps_cmd(2012)
        outdir = Path(cmd[cmd.index("--outdir") + 1])
        assert outdir == chirps_path(2012).parent


# ── isimip_connector ──────────────────────────────────────────────────────────

class TestIsimipConnector:
    def test_rh_maps_to_hurs(self):
        assert AGENT_TO_ISIMIP["rh"] == "hurs"

    def test_tas_maps_to_tas(self):
        assert AGENT_TO_ISIMIP["tas"] == "tas"

    def test_pr_maps_to_pr(self):
        assert AGENT_TO_ISIMIP["pr"] == "pr"

    def test_isimip_to_agent_hurs_maps_back_to_rh(self):
        assert ISIMIP_TO_AGENT["hurs"] == "rh"

    def test_source_dir_contains_country_long_name(self):
        assert "ethiopia" in str(source_dir("eth", "ssp245", "rh")).lower()

    def test_source_dir_contains_scenario(self):
        assert "ssp" in str(source_dir("eth", "ssp245", "rh")).lower()

    def test_source_dir_contains_isimip_source_var(self):
        # rh → hurs directory
        assert "hurs" in str(source_dir("eth", "ssp245", "rh"))

    def test_source_dir_pr_uses_pr(self):
        assert "pr" in str(source_dir("eth", "ssp245", "pr"))

    def test_source_dir_is_absolute(self):
        assert source_dir("eth", "ssp245", "tas").is_absolute()

    def test_source_dir_ken_contains_kenya(self):
        assert "kenya" in str(source_dir("ken", "ssp245", "rh")).lower()

    def test_source_dir_som_contains_somalia(self):
        assert "somalia" in str(source_dir("som", "ssp585", "tas")).lower()

    def test_list_available_files_returns_list(self):
        # Missing dir → empty list (never raises)
        result = list_available_files("eth", "ssp245", "rh")
        assert isinstance(result, list)

    def test_check_availability_key_format(self):
        result = check_availability(["eth"], ["ssp245"], ["rh"])
        assert "eth/ssp245/rh" in result

    def test_check_availability_missing_dir_prefix(self):
        result = check_availability(["eth"], ["ssp245"], ["rh"])
        val = result["eth/ssp245/rh"]
        assert val.startswith("OK") or val.startswith("MISSING")

    def test_check_availability_unsupported_variable_is_error(self):
        result = check_availability(["eth"], ["ssp245"], ["vpd"])
        assert result["eth/ssp245/vpd"].startswith("ERROR")

    def test_check_availability_all_three_countries(self):
        result = check_availability(["eth", "ken", "som"], ["ssp245"], ["rh"])
        assert len(result) == 3

    def test_check_availability_multiple_scenarios(self):
        result = check_availability(["eth"], ["ssp245", "ssp585"], ["rh"])
        assert "eth/ssp245/rh" in result
        assert "eth/ssp585/rh" in result
