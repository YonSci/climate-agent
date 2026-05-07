"""
End-to-end dry-run tests for run_agent.py.

These tests invoke run_agent.py as a subprocess with --dry-run so they exercise
the full CLI path (arg parsing, validation, preflight skip, routing, plan printing)
without executing any real scripts or writing to runs/.
"""

from __future__ import annotations
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_ROOT / "run_agent.py")] + args,
        capture_output=True,
        text=True,
        cwd=str(_ROOT),
    )


class TestDryRunHistorical:
    def test_exits_zero(self):
        r = _run(["--countries", "eth", "--variables", "tas",
                  "--scenario", "historical", "--period", "2010", "2020",
                  "--skip-preflight", "--dry-run"])
        assert r.returncode == 0, r.stderr

    def test_prints_dry_run_header(self):
        r = _run(["--countries", "eth", "--variables", "pr",
                  "--scenario", "historical", "--period", "2010", "2020",
                  "--skip-preflight", "--dry-run"])
        assert "DRY RUN" in r.stdout

    def test_prints_run_type_historical(self):
        r = _run(["--countries", "eth", "--variables", "rh",
                  "--scenario", "historical", "--period", "2010", "2020",
                  "--skip-preflight", "--dry-run"])
        assert "historical" in r.stdout.lower()

    def test_prints_merge_stage(self):
        r = _run(["--countries", "eth", "--variables", "tas",
                  "--scenario", "historical", "--period", "2010", "2020",
                  "--skip-preflight", "--dry-run"])
        assert "merge" in r.stdout

    def test_prints_historical_workflow_script(self):
        r = _run(["--countries", "eth", "--variables", "tas",
                  "--scenario", "historical", "--period", "2010", "2020",
                  "--skip-preflight", "--dry-run"])
        assert "run_historical_workflow.py" in r.stdout

    def test_countries_appear_in_output(self):
        r = _run(["--countries", "eth", "ken", "--variables", "pr",
                  "--scenario", "historical", "--period", "2010", "2020",
                  "--skip-preflight", "--dry-run"])
        assert "eth" in r.stdout or "ethiopia" in r.stdout
        assert "ken" in r.stdout or "kenya" in r.stdout

    def test_period_appears_in_output(self):
        r = _run(["--countries", "eth", "--variables", "tas",
                  "--scenario", "historical", "--period", "2015", "2022",
                  "--skip-preflight", "--dry-run"])
        assert "2015" in r.stdout
        assert "2022" in r.stdout


class TestDryRunProjection:
    def test_projection_exits_zero(self):
        r = _run(["--countries", "eth", "--variables", "rh",
                  "--scenario", "ssp245", "--period", "2040", "2070",
                  "--skip-preflight", "--dry-run"])
        assert r.returncode == 0, r.stderr

    def test_projection_prints_regrid_stage(self):
        r = _run(["--countries", "eth", "--variables", "tas",
                  "--scenario", "ssp585", "--period", "2040", "2070",
                  "--skip-preflight", "--dry-run"])
        assert "regrid" in r.stdout

    def test_projection_workflow_script_named(self):
        r = _run(["--countries", "eth", "--variables", "pr",
                  "--scenario", "ssp245", "--period", "2040", "2070",
                  "--skip-preflight", "--dry-run"])
        assert "run_projection_workflow.py" in r.stdout


class TestDryRunVPD:
    def test_vpd_only_exits_zero(self):
        r = _run(["--countries", "eth", "--variables", "vpd",
                  "--scenario", "ssp245", "--period", "2040", "2070",
                  "--skip-preflight", "--dry-run"])
        assert r.returncode == 0, r.stderr

    def test_vpd_only_has_vpd_compute_stage(self):
        r = _run(["--countries", "eth", "--variables", "vpd",
                  "--scenario", "ssp245", "--period", "2040", "2070",
                  "--skip-preflight", "--dry-run"])
        assert "vpd_compute" in r.stdout

    def test_projection_plus_vpd_has_two_stages(self):
        r = _run(["--countries", "eth", "--variables", "rh", "vpd",
                  "--scenario", "ssp245", "--period", "2040", "2070",
                  "--skip-preflight", "--dry-run"])
        assert "Stage 1" in r.stdout
        assert "Stage 2" in r.stdout


class TestDryRunValidation:
    def test_unknown_country_exits_nonzero(self):
        r = _run(["--countries", "zzz", "--variables", "tas",
                  "--scenario", "historical", "--period", "2010", "2020",
                  "--skip-preflight", "--dry-run"])
        assert r.returncode != 0

    def test_inverted_period_exits_nonzero(self):
        r = _run(["--countries", "eth", "--variables", "tas",
                  "--scenario", "historical", "--period", "2025", "2010",
                  "--skip-preflight", "--dry-run"])
        assert r.returncode != 0

    def test_workers_flag_accepted(self):
        r = _run(["--countries", "eth", "--variables", "pr",
                  "--scenario", "historical", "--period", "2010", "2020",
                  "--workers", "4", "--skip-preflight", "--dry-run"])
        assert r.returncode == 0, r.stderr

    def test_fast_mode_accepted(self):
        r = _run(["--countries", "eth", "--variables", "pr",
                  "--scenario", "historical", "--period", "2010", "2020",
                  "--mode", "fast", "--skip-preflight", "--dry-run"])
        assert r.returncode == 0, r.stderr
