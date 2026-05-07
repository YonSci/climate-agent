"""
Tests for agent/preflight.py — dependency, boundary, source-dir, and script checks.

Structural / logic tests use mocks so no filesystem or network access is required.
Integration tests (TestCheckScripts, TestRunPreflight) hit the real disk and
are safe because they are read-only.
"""

import pytest
from unittest.mock import patch
from agent.preflight import (
    check_dependencies,
    check_boundaries,
    check_scripts,
    check_source_dirs,
    check_cds_credentials,
    check_reference_grid,
    run_preflight,
    PreflightReport,
)


# ── dependency checks ─────────────────────────────────────────────────────────

class TestCheckDependencies:
    def test_returns_dict_of_packages(self):
        result = check_dependencies()
        assert isinstance(result, dict)
        assert "xarray" in result
        assert "numpy" in result

    def test_core_packages_installed(self):
        result = check_dependencies()
        for pkg in ("xarray", "numpy", "pandas"):
            assert not result[pkg].startswith("MISSING"), \
                f"{pkg} is not installed: {result[pkg]}"

    def test_no_unexpected_keys(self):
        result = check_dependencies()
        for pkg, status in result.items():
            assert isinstance(pkg, str)
            assert isinstance(status, str)


# ── boundary checks ───────────────────────────────────────────────────────────

class TestCheckBoundaries:
    def test_returns_dict_per_country(self):
        result = check_boundaries(["eth", "ken", "som"])
        assert set(result.keys()) == {"eth", "ken", "som"}

    def test_unknown_country_is_error(self):
        result = check_boundaries(["zzz"])
        assert result["zzz"].startswith("ERROR")

    def test_known_countries_status_is_string(self):
        result = check_boundaries(["eth"])
        assert isinstance(result["eth"], str)


# ── workflow script checks ────────────────────────────────────────────────────

class TestCheckScripts:
    def test_returns_dict_for_all_three_workflows(self):
        result = check_scripts()
        assert "run_historical_workflow.py"   in result
        assert "run_projection_workflow.py"   in result
        assert "run_future_vpd_workflow.py"   in result

    def test_scripts_are_present(self):
        result = check_scripts()
        for name, status in result.items():
            assert status == "OK", f"Script {name} is {status}"


# ── source directory checks ───────────────────────────────────────────────────

class TestCheckSourceDirs:
    def test_historical_pr_checks_chirps_dir(self):
        request = {
            "countries": ["eth"],
            "variables": ["pr"],
            "scenario": "historical",
            "period": [2010, 2025],
        }
        result = check_source_dirs(request)
        assert any("chirps" in key for key in result)

    def test_historical_rh_checks_agera5_dir(self):
        request = {
            "countries": ["eth"],
            "variables": ["rh"],
            "scenario": "historical",
            "period": [2010, 2025],
        }
        result = check_source_dirs(request)
        assert any("agera5" in key for key in result)

    def test_projection_checks_isimip_dir(self):
        request = {
            "countries": ["eth"],
            "variables": ["rh"],
            "scenario": "ssp245",
            "period": [2040, 2070],
        }
        result = check_source_dirs(request)
        assert any("isimip" in key for key in result)

    def test_vpd_skipped_in_source_check(self):
        request = {
            "countries": ["eth"],
            "variables": ["vpd"],
            "scenario": "ssp245",
            "period": [2040, 2070],
        }
        result = check_source_dirs(request)
        # VPD is derived — no source dir entry expected
        assert all("vpd" not in key for key in result)


# ── PreflightReport ───────────────────────────────────────────────────────────

class TestPreflightReport:
    def test_no_errors_has_errors_false(self):
        r = PreflightReport()
        assert not r.has_errors

    def test_with_error_has_errors_true(self):
        r = PreflightReport(errors=["something broke"])
        assert r.has_errors

    def test_str_lists_errors_and_warnings(self):
        r = PreflightReport(errors=["e1"], warnings=["w1"])
        s = str(r)
        assert "ERROR" in s
        assert "WARNING" in s

    def test_str_all_clear(self):
        r = PreflightReport()
        assert "passed" in str(r).lower()


# ── run_preflight integration ─────────────────────────────────────────────────

class TestRunPreflight:
    def test_returns_preflight_report(self):
        request = {
            "countries": ["eth"],
            "variables": ["pr"],
            "scenario": "historical",
            "period": [2010, 2025],
        }
        report = run_preflight(request)
        assert isinstance(report, PreflightReport)

    def test_no_dep_errors_for_installed_packages(self):
        from agent.preflight import check_dependencies
        deps = check_dependencies()
        missing = [pkg for pkg, s in deps.items() if s.startswith("MISSING")]
        if missing:
            pytest.skip(
                f"Full requirements not installed in this environment "
                f"(missing: {missing}). Install requirements.txt first."
            )
        request = {
            "countries": ["eth"],
            "variables": ["pr"],
            "scenario": "historical",
            "period": [2010, 2025],
        }
        report = run_preflight(request)
        dep_errors = [e for e in report.errors if "package" in e.lower()]
        assert dep_errors == [], f"Dependency errors: {dep_errors}"


# ── run_preflight escalation logic (mocked) ───────────────────────────────────

_GOOD_REQUEST = {
    "countries": ["eth"],
    "variables": ["pr"],
    "scenario": "historical",
    "period": [2010, 2025],
}


class TestRunPreflightEscalation:
    """Verify that each checker's MISSING result maps to the right severity."""

    def test_missing_package_becomes_error(self):
        bad_deps = {"xarray": "MISSING (not installed)", "numpy": "1.26"}
        with patch("agent.preflight.check_dependencies", return_value=bad_deps), \
             patch("agent.preflight.check_scripts",
                   return_value={"run_historical_workflow.py": "OK",
                                 "run_projection_workflow.py": "OK",
                                 "run_future_vpd_workflow.py": "OK"}), \
             patch("agent.preflight.check_boundaries", return_value={"eth": "OK"}), \
             patch("agent.preflight.check_source_dirs",
                   return_value={"eth/pr/chirps": "OK"}):
            report = run_preflight(_GOOD_REQUEST)
        assert report.has_errors
        assert any("xarray" in e for e in report.errors)

    def test_missing_script_becomes_error(self):
        with patch("agent.preflight.check_dependencies",
                   return_value={"xarray": "2024.1"}), \
             patch("agent.preflight.check_scripts",
                   return_value={"run_historical_workflow.py": "MISSING: /path/to/script",
                                 "run_projection_workflow.py": "OK",
                                 "run_future_vpd_workflow.py": "OK"}), \
             patch("agent.preflight.check_boundaries", return_value={"eth": "OK"}), \
             patch("agent.preflight.check_source_dirs",
                   return_value={"eth/pr/chirps": "OK"}):
            report = run_preflight(_GOOD_REQUEST)
        assert report.has_errors
        assert any("MISSING" in e for e in report.errors)

    def test_missing_boundary_becomes_warning_not_error(self):
        with patch("agent.preflight.check_dependencies",
                   return_value={"xarray": "2024.1"}), \
             patch("agent.preflight.check_scripts",
                   return_value={"run_historical_workflow.py": "OK",
                                 "run_projection_workflow.py": "OK",
                                 "run_future_vpd_workflow.py": "OK"}), \
             patch("agent.preflight.check_cds_credentials", return_value="OK"), \
             patch("agent.preflight.check_reference_grid", return_value="OK"), \
             patch("agent.preflight.check_boundaries",
                   return_value={"eth": "MISSING: /path/eth.shp"}), \
             patch("agent.preflight.check_source_dirs",
                   return_value={"eth/pr/chirps": "OK"}):
            report = run_preflight(_GOOD_REQUEST)
        assert not report.has_errors
        assert any("eth" in w for w in report.warnings)

    def test_missing_source_dir_becomes_error(self):
        with patch("agent.preflight.check_dependencies",
                   return_value={"xarray": "2024.1"}), \
             patch("agent.preflight.check_scripts",
                   return_value={"run_historical_workflow.py": "OK",
                                 "run_projection_workflow.py": "OK",
                                 "run_future_vpd_workflow.py": "OK"}), \
             patch("agent.preflight.check_boundaries", return_value={"eth": "OK"}), \
             patch("agent.preflight.check_source_dirs",
                   return_value={"eth/pr/chirps": "MISSING: /path/chirps"}):
            report = run_preflight(_GOOD_REQUEST)
        assert report.has_errors
        assert any("eth/pr/chirps" in e for e in report.errors)

    def test_all_ok_no_errors_no_warnings(self):
        with patch("agent.preflight.check_dependencies",
                   return_value={"xarray": "2024.1", "numpy": "1.26"}), \
             patch("agent.preflight.check_scripts",
                   return_value={"run_historical_workflow.py": "OK",
                                 "run_projection_workflow.py": "OK",
                                 "run_future_vpd_workflow.py": "OK"}), \
             patch("agent.preflight.check_cds_credentials", return_value="OK"), \
             patch("agent.preflight.check_reference_grid", return_value="OK"), \
             patch("agent.preflight.check_boundaries", return_value={"eth": "OK"}), \
             patch("agent.preflight.check_source_dirs",
                   return_value={"eth/pr/chirps": "OK"}):
            report = run_preflight(_GOOD_REQUEST)
        assert not report.has_errors
        assert report.warnings == []

    def test_dep_error_and_boundary_warning_both_reported(self):
        with patch("agent.preflight.check_dependencies",
                   return_value={"xarray": "MISSING (not installed)"}), \
             patch("agent.preflight.check_scripts",
                   return_value={"run_historical_workflow.py": "OK",
                                 "run_projection_workflow.py": "OK",
                                 "run_future_vpd_workflow.py": "OK"}), \
             patch("agent.preflight.check_boundaries",
                   return_value={"eth": "MISSING: /boundary.shp"}), \
             patch("agent.preflight.check_source_dirs",
                   return_value={"eth/pr/chirps": "OK"}):
            report = run_preflight(_GOOD_REQUEST)
        assert report.has_errors
        assert report.warnings != []


# ── check_source_dirs key/status format ──────────────────────────────────────

class TestCheckSourceDirsStatusFormat:
    def test_existing_dir_status_is_ok(self, tmp_path):
        with patch("agent.connectors.chirps.is_source_available", return_value=True):
            result = check_source_dirs({
                "countries": ["eth"], "variables": ["pr"],
                "scenario": "historical", "period": [2010, 2025],
            })
        assert result.get("eth/pr/chirps") == "OK"

    def test_missing_dir_status_starts_with_missing(self, tmp_path):
        with patch("agent.connectors.chirps.is_source_available", return_value=False), \
             patch("agent.connectors.chirps.source_dir", return_value=tmp_path / "chirps"):
            result = check_source_dirs({
                "countries": ["eth"], "variables": ["pr"],
                "scenario": "historical", "period": [2010, 2025],
            })
        assert result.get("eth/pr/chirps", "").startswith("MISSING")

    def test_projection_rh_isimip_key_format(self, tmp_path):
        with patch("agent.preflight.ROOT", tmp_path):
            result = check_source_dirs({
                "countries": ["eth"], "variables": ["rh"],
                "scenario": "ssp245", "period": [2040, 2070],
            })
        assert "eth/rh/isimip/ssp245" in result

    def test_historical_vpd_checks_agera5_dir(self, tmp_path):
        with patch("agent.preflight.ROOT", tmp_path):
            result = check_source_dirs({
                "countries": ["eth"], "variables": ["vpd"],
                "scenario": "historical", "period": [2010, 2025],
            })
        assert any("agera5" in k for k in result)

    def test_multiple_countries_all_present_in_result(self, tmp_path):
        with patch("agent.preflight.ROOT", tmp_path):
            result = check_source_dirs({
                "countries": ["eth", "ken"], "variables": ["pr"],
                "scenario": "historical", "period": [2010, 2025],
            })
        keys = list(result.keys())
        assert any(k.startswith("eth/") for k in keys)
        assert any(k.startswith("ken/") for k in keys)
