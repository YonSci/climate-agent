"""
test_e2e_integration.py — End-to-end integration tests.

These tests exercise the full CLI entry point (run_agent.py) as a subprocess
so that argument parsing, routing, plan building, early-exit modes, and
manifest writing are all tested together — not just in unit isolation.

Conventions
-----------
- All tests that write manifests use a tmp_path-scoped manifests dir passed
  via --manifests-dir so the real runs/ directory is never touched.
- Tests that need a real manifest on disk write one with _write_manifest().
- Pipeline stages themselves are never actually executed (too slow / need real
  data); the orchestrator is verified through dry-run or diagnostics-only paths.
"""

from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


def _run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_ROOT / "run_agent.py")] + args,
        capture_output=True, text=True, cwd=str(_ROOT), **kwargs,
    )


def _write_manifest(mdir: Path, run_id: str, *,
                    scenario: str = "historical",
                    succeeded: int = 2, failed: int = 0,
                    output_files: list[str] | None = None) -> Path:
    mdir.mkdir(parents=True, exist_ok=True)
    m = {
        "run_id": run_id,
        "timestamp": "2026-05-07T10:00:00+00:00",
        "request": {
            "countries": ["eth"], "variables": ["tas"],
            "scenario": scenario, "period": [2010, 2025],
        },
        "environment": {"python_version": "3.11.0"},
        "stages": [],
        "summary": {
            "total_slices": succeeded + failed,
            "succeeded": succeeded, "failed": failed,
            "warnings": 0, "skipped": 0,
            "duration_seconds": 42.0,
            "failed_slices": [
                {"country": "eth", "variable": "tas",
                 "scenario": "historical", "stage": "merge", "reason": "timeout"}
            ] if failed > 0 else [],
            "output_files": output_files or [],
            "diagnostic_files": [],
        },
    }
    path = mdir / f"{run_id}.json"
    path.write_text(json.dumps(m))
    return path


# ═════════════════════════════════════════════════════════════════════════════
# --list-runs with --manifests-dir
# ═════════════════════════════════════════════════════════════════════════════

class TestListRunsIntegration:
    """Full CLI --list-runs path exercised as a subprocess."""

    def test_exits_zero_empty_dir(self, tmp_path):
        mdir = tmp_path / "manifests"
        mdir.mkdir()
        r = _run(["--list-runs", "--manifests-dir", str(mdir)])
        assert r.returncode == 0

    def test_no_manifests_message(self, tmp_path):
        mdir = tmp_path / "manifests"
        mdir.mkdir()
        r = _run(["--list-runs", "--manifests-dir", str(mdir)])
        assert "No run manifests" in r.stdout

    def test_run_id_appears_in_output(self, tmp_path):
        mdir = tmp_path / "manifests"
        _write_manifest(mdir, "run_20260507_090000")
        r = _run(["--list-runs", "--manifests-dir", str(mdir)])
        assert "run_20260507_090000" in r.stdout

    def test_failed_filter_excludes_passing_runs(self, tmp_path):
        mdir = tmp_path / "manifests"
        _write_manifest(mdir, "run_20260507_010000", succeeded=3, failed=0)
        _write_manifest(mdir, "run_20260507_020000", succeeded=0, failed=1)
        r = _run(["--list-runs", "--manifests-dir", str(mdir), "--failed"])
        assert "run_20260507_020000" in r.stdout
        assert "run_20260507_010000" not in r.stdout

    def test_limit_restricts_rows(self, tmp_path):
        mdir = tmp_path / "manifests"
        for i in range(5):
            _write_manifest(mdir, f"run_2026050{i}_000000")
        r = _run(["--list-runs", "--manifests-dir", str(mdir), "--limit", "2"])
        assert "2 run(s) shown" in r.stdout


# ═════════════════════════════════════════════════════════════════════════════
# --export-run / --export-to
# ═════════════════════════════════════════════════════════════════════════════

class TestExportIntegration:
    """Full CLI --export-run path exercised as a subprocess."""

    def test_export_copies_existing_file(self, tmp_path):
        # Write a source NetCDF (fake) and a manifest that references it
        src = tmp_path / "output.nc"
        src.write_bytes(b"fake netcdf")
        mdir = tmp_path / "manifests"
        _write_manifest(mdir, "run_exp_001", output_files=[str(src)])

        export_dir = tmp_path / "delivery"
        r = _run([
            "--export-run", "run_exp_001",
            "--export-to", str(export_dir),
            "--manifests-dir", str(mdir),
        ])
        assert r.returncode == 0
        assert (export_dir / "output.nc").exists()

    def test_export_writes_delivery_manifest(self, tmp_path):
        src = tmp_path / "file.nc"
        src.write_bytes(b"data")
        mdir = tmp_path / "manifests"
        _write_manifest(mdir, "run_exp_002", output_files=[str(src)])

        export_dir = tmp_path / "delivery"
        _run([
            "--export-run", "run_exp_002",
            "--export-to", str(export_dir),
            "--manifests-dir", str(mdir),
        ])
        dm = export_dir / "delivery_manifest.json"
        assert dm.exists()
        payload = json.loads(dm.read_text())
        assert payload["run_id"] == "run_exp_002"
        assert payload["copied"] == 1
        assert len(payload["files"]) == 1

    def test_export_skips_missing_source(self, tmp_path):
        mdir = tmp_path / "manifests"
        _write_manifest(mdir, "run_exp_003",
                        output_files=[str(tmp_path / "ghost.nc")])
        export_dir = tmp_path / "delivery"
        r = _run([
            "--export-run", "run_exp_003",
            "--export-to", str(export_dir),
            "--manifests-dir", str(mdir),
        ])
        dm = json.loads((export_dir / "delivery_manifest.json").read_text())
        assert dm["skipped"] == 1
        assert dm["copied"] == 0

    def test_export_missing_run_id_exits_nonzero(self, tmp_path):
        mdir = tmp_path / "manifests"
        mdir.mkdir()
        r = _run([
            "--export-run", "run_does_not_exist",
            "--export-to", str(tmp_path / "out"),
            "--manifests-dir", str(mdir),
        ])
        assert r.returncode != 0

    def test_export_no_export_to_exits_nonzero(self, tmp_path):
        r = _run(["--export-run", "run_xyz"])
        assert r.returncode != 0

    def test_export_prints_file_count(self, tmp_path):
        src = tmp_path / "data.nc"
        src.write_bytes(b"x")
        mdir = tmp_path / "manifests"
        _write_manifest(mdir, "run_exp_004", output_files=[str(src)])
        export_dir = tmp_path / "out"
        r = _run([
            "--export-run", "run_exp_004",
            "--export-to", str(export_dir),
            "--manifests-dir", str(mdir),
        ])
        assert "1 file" in r.stdout


# ═════════════════════════════════════════════════════════════════════════════
# --resume-latest
# ═════════════════════════════════════════════════════════════════════════════

class TestResumeLatesIntegration:
    """_find_latest_failed_run() picks the right manifest."""

    def test_finds_most_recent_failed_run(self, tmp_path):
        from run_agent import _find_latest_failed_run
        from unittest.mock import patch

        mdir = tmp_path / "manifests"
        _write_manifest(mdir, "run_20260507_010000", succeeded=3, failed=0)
        _write_manifest(mdir, "run_20260507_020000", succeeded=1, failed=2)
        _write_manifest(mdir, "run_20260507_030000", succeeded=3, failed=0)

        with patch("run_agent.MANIFESTS_DIR", mdir):
            result = _find_latest_failed_run()

        assert result == "run_20260507_020000"

    def test_returns_none_when_no_failures(self, tmp_path):
        from run_agent import _find_latest_failed_run
        from unittest.mock import patch

        mdir = tmp_path / "manifests"
        _write_manifest(mdir, "run_20260507_010000", succeeded=5, failed=0)

        with patch("run_agent.MANIFESTS_DIR", mdir):
            result = _find_latest_failed_run()

        assert result is None

    def test_returns_none_when_no_manifests(self, tmp_path):
        from run_agent import _find_latest_failed_run
        from unittest.mock import patch

        mdir = tmp_path / "empty"
        mdir.mkdir()
        with patch("run_agent.MANIFESTS_DIR", mdir):
            result = _find_latest_failed_run()

        assert result is None

    def test_most_recent_failed_preferred_over_older(self, tmp_path):
        from run_agent import _find_latest_failed_run
        from unittest.mock import patch

        mdir = tmp_path / "manifests"
        # Older failure and a newer failure — should pick newest
        _write_manifest(mdir, "run_20260505_000000", succeeded=0, failed=3)
        _write_manifest(mdir, "run_20260507_000000", succeeded=0, failed=1)

        with patch("run_agent.MANIFESTS_DIR", mdir):
            result = _find_latest_failed_run()

        assert result == "run_20260507_000000"


# ═════════════════════════════════════════════════════════════════════════════
# --dry-run: full CLI routing for all scenario types
# ═════════════════════════════════════════════════════════════════════════════

class TestDryRunRouting:
    """
    --dry-run exercises the full parse → validate → route → plan path
    without executing any subprocesses.  Verifies all 4 workflow types
    are reachable from the CLI.
    """

    _BASE = [
        "--countries", "eth",
        "--variables", "tas",
        "--scenario", "historical",
        "--period", "2010", "2025",
        "--dry-run", "--skip-preflight",
    ]

    def test_historical_dry_run_exits_zero(self):
        r = _run(self._BASE)
        assert r.returncode == 0

    def test_historical_dry_run_shows_stage(self):
        r = _run(self._BASE)
        assert "merge" in r.stdout.lower() or "historical" in r.stdout.lower()

    def test_projection_dry_run_exits_zero(self):
        r = _run([
            "--countries", "eth", "--variables", "tas",
            "--scenario", "ssp245", "--period", "2040", "2070",
            "--dry-run", "--skip-preflight",
        ])
        assert r.returncode == 0

    def test_vpd_projection_dry_run_exits_zero(self):
        r = _run([
            "--countries", "eth", "--variables", "vpd",
            "--scenario", "ssp245", "--period", "2040", "2070",
            "--dry-run", "--skip-preflight",
        ])
        assert r.returncode == 0

    def test_diagnostics_only_dry_run_exits_zero(self):
        r = _run([
            "--countries", "eth", "--variables", "tas",
            "--scenario", "historical", "--period", "2010", "2025",
            "--diagnostics-only", "--dry-run", "--skip-preflight",
        ])
        assert r.returncode == 0

    def test_invalid_country_exits_nonzero(self):
        r = _run([
            "--countries", "xyz", "--variables", "tas",
            "--scenario", "historical", "--period", "2010", "2025",
            "--dry-run", "--skip-preflight",
        ])
        assert r.returncode != 0

    def test_invalid_variable_exits_nonzero(self):
        r = _run([
            "--countries", "eth", "--variables", "wind",
            "--scenario", "historical", "--period", "2010", "2025",
            "--dry-run", "--skip-preflight",
        ])
        assert r.returncode != 0

    def test_workers_zero_exits_nonzero(self):
        r = _run([
            "--countries", "eth", "--variables", "tas",
            "--scenario", "historical", "--period", "2010", "2025",
            "--workers", "0", "--dry-run", "--skip-preflight",
        ])
        assert r.returncode != 0

    def test_multi_country_dry_run_exits_zero(self):
        r = _run([
            "--countries", "eth", "ken", "--variables", "tas", "rh",
            "--scenario", "historical", "--period", "2010", "2025",
            "--dry-run", "--skip-preflight",
        ])
        assert r.returncode == 0

    def test_dry_run_shows_period(self):
        r = _run(self._BASE)
        assert "2010" in r.stdout and "2025" in r.stdout


# ═════════════════════════════════════════════════════════════════════════════
# Progress output
# ═════════════════════════════════════════════════════════════════════════════

class TestProgressOutput:
    """_progress() prints timestamped lines; dry-run shows stage progress."""

    def test_progress_function_prints_to_stdout(self, capsys):
        from run_agent import _progress
        _progress("test message")
        out = capsys.readouterr().out
        assert "test message" in out

    def test_progress_includes_timestamp(self, capsys):
        from run_agent import _progress
        _progress("hello")
        out = capsys.readouterr().out
        # HH:MM:SS format
        import re
        assert re.search(r"\d{2}:\d{2}:\d{2}", out)

    def test_dry_run_output_has_stage_info(self):
        r = _run([
            "--countries", "eth", "--variables", "tas",
            "--scenario", "historical", "--period", "2010", "2025",
            "--dry-run", "--skip-preflight",
        ])
        assert r.returncode == 0
        # dry-run prints the plan; stage names should appear
        combined = r.stdout + r.stderr
        assert "Stage" in combined or "stage" in combined or "merge" in combined
