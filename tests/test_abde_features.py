"""
test_abde_features.py — Tests for features A, B, D, and E:

  A+G: --list-runs command (history view)
  B:   cleanup_intermediates() respects agent_config.yaml flag
  D:   merge_netcdf_somalia_vapour_pressure_deficit.py exists and runs
  E:   download status report accumulated on Orchestrator and saved to manifest
"""

from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_ROOT = Path(__file__).resolve().parents[1]


def _run_agent(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_ROOT / "run_agent.py")] + args,
        capture_output=True, text=True, cwd=str(_ROOT),
    )


# ═════════════════════════════════════════════════════════════════════════════
# A+G — --list-runs command
# ═════════════════════════════════════════════════════════════════════════════

class TestListRuns:
    """--list-runs reads runs/manifests/ and prints a summary table."""

    def _write_manifest(self, mdir: Path, run_id: str, *,
                        scenario: str = "historical",
                        countries: list | None = None,
                        variables: list | None = None,
                        succeeded: int = 2, failed: int = 0) -> None:
        mdir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "run_id": run_id,
            "timestamp": "2026-05-07T10:00:00+00:00",
            "request": {
                "countries": countries or ["eth"],
                "variables": variables or ["tas"],
                "scenario": scenario,
                "period": [2010, 2025],
            },
            "environment": {"python_version": "3.11.0"},
            "stages": [],
            "summary": {
                "total_slices": succeeded + failed,
                "succeeded": succeeded,
                "failed": failed,
                "warnings": 0,
                "skipped": 0,
                "duration_seconds": 42.0,
                "failed_slices": [],
                "output_files": [],
                "diagnostic_files": [],
            },
        }
        (mdir / f"{run_id}.json").write_text(json.dumps(manifest))

    def test_list_runs_exits_zero_with_manifests(self, tmp_path):
        mdir = tmp_path / "manifests"
        self._write_manifest(mdir, "run_20260507_100000")
        r = _run_agent(["--list-runs", "--manifests-dir", str(mdir)])
        assert r.returncode == 0

    def test_list_runs_shows_run_id(self, tmp_path):
        mdir = tmp_path / "manifests"
        self._write_manifest(mdir, "run_20260507_100000")
        r = _run_agent(["--list-runs", "--manifests-dir", str(mdir)])
        assert "run_20260507_100000" in r.stdout

    def test_list_runs_shows_scenario(self, tmp_path):
        mdir = tmp_path / "manifests"
        self._write_manifest(mdir, "run_20260507_110000", scenario="ssp245")
        r = _run_agent(["--list-runs", "--manifests-dir", str(mdir)])
        assert "ssp245" in r.stdout

    def test_list_runs_no_manifests_exits_zero(self, tmp_path):
        mdir = tmp_path / "empty_manifests"
        mdir.mkdir()
        r = _run_agent(["--list-runs", "--manifests-dir", str(mdir)])
        assert r.returncode == 0
        assert "No run manifests" in r.stdout

    def test_list_runs_failed_filter(self, tmp_path):
        mdir = tmp_path / "manifests"
        self._write_manifest(mdir, "run_20260507_120000", succeeded=2, failed=0)
        self._write_manifest(mdir, "run_20260507_130000", succeeded=0, failed=1)
        r = _run_agent(["--list-runs", "--manifests-dir", str(mdir), "--failed"])
        assert r.returncode == 0
        # Only the failed run should appear
        assert "run_20260507_130000" in r.stdout
        assert "run_20260507_120000" not in r.stdout

    def test_list_runs_real_manifests_dir_exits_zero(self):
        """With the real manifests dir (may be empty), --list-runs exits 0."""
        r = _run_agent(["--list-runs"])
        assert r.returncode == 0

    def test_list_runs_limit_respected(self, tmp_path):
        mdir = tmp_path / "manifests"
        for i in range(5):
            self._write_manifest(mdir, f"run_2026050{i}_100000")
        r = _run_agent(["--list-runs", "--manifests-dir", str(mdir), "--limit", "2"])
        assert r.returncode == 0
        assert "2 run(s) shown" in r.stdout


# ═════════════════════════════════════════════════════════════════════════════
# B — cleanup_intermediates()
# ═════════════════════════════════════════════════════════════════════════════

class TestCleanupIntermediates:
    """cleanup_intermediates() deletes files when config flag is true."""

    def test_no_deletion_when_flag_false(self, tmp_path):
        from agent.artifact_manager import cleanup_intermediates

        inter = tmp_path / "intermediate" / "eth" / "tas"
        inter.mkdir(parents=True)
        nc = inter / "tas_eth_agera5_merged_2010-2025.nc"
        nc.write_bytes(b"fake")

        with patch("agent.artifact_manager._cfg",
                   {"cleanup": {"delete_intermediates_on_success": False}}), \
             patch("agent.artifact_manager.INTER_DIR", tmp_path / "intermediate"):
            deleted = cleanup_intermediates(["eth"], ["tas"])

        assert deleted == []
        assert nc.exists()

    def test_deletes_nc_files_when_flag_true(self, tmp_path):
        from agent.artifact_manager import cleanup_intermediates

        inter = tmp_path / "intermediate" / "eth" / "tas"
        inter.mkdir(parents=True)
        nc = inter / "tas_eth_agera5_merged_2010-2025.nc"
        nc.write_bytes(b"fake")

        with patch("agent.artifact_manager._cfg",
                   {"cleanup": {"delete_intermediates_on_success": True}}), \
             patch("agent.artifact_manager.INTER_DIR", tmp_path / "intermediate"):
            deleted = cleanup_intermediates(["eth"], ["tas"])

        assert len(deleted) == 1
        assert not nc.exists()

    def test_returns_list_of_deleted_paths(self, tmp_path):
        from agent.artifact_manager import cleanup_intermediates

        inter = tmp_path / "intermediate" / "ken" / "rh"
        inter.mkdir(parents=True)
        for name in ("a.nc", "b.nc"):
            (inter / name).write_bytes(b"x")

        with patch("agent.artifact_manager._cfg",
                   {"cleanup": {"delete_intermediates_on_success": True}}), \
             patch("agent.artifact_manager.INTER_DIR", tmp_path / "intermediate"):
            deleted = cleanup_intermediates(["ken"], ["rh"])

        assert len(deleted) == 2

    def test_missing_dir_is_silent(self, tmp_path):
        from agent.artifact_manager import cleanup_intermediates

        with patch("agent.artifact_manager._cfg",
                   {"cleanup": {"delete_intermediates_on_success": True}}), \
             patch("agent.artifact_manager.INTER_DIR", tmp_path / "nonexistent"):
            deleted = cleanup_intermediates(["eth"], ["pr"])

        assert deleted == []

    def test_non_nc_files_not_deleted(self, tmp_path):
        from agent.artifact_manager import cleanup_intermediates

        inter = tmp_path / "intermediate" / "eth" / "tas"
        inter.mkdir(parents=True)
        txt = inter / "notes.txt"
        txt.write_text("keep me")

        with patch("agent.artifact_manager._cfg",
                   {"cleanup": {"delete_intermediates_on_success": True}}), \
             patch("agent.artifact_manager.INTER_DIR", tmp_path / "intermediate"):
            deleted = cleanup_intermediates(["eth"], ["tas"])

        assert deleted == []
        assert txt.exists()


# ═════════════════════════════════════════════════════════════════════════════
# D — Somalia VPD merge script
# ═════════════════════════════════════════════════════════════════════════════

class TestSomaliaVpdMergeScript:
    """merge_netcdf_somalia_vapour_pressure_deficit.py exists and behaves correctly."""

    _SCRIPT = _ROOT / "scripts" / "merge_netcdf_somalia_vapour_pressure_deficit.py"

    def test_script_exists(self):
        assert self._SCRIPT.exists(), f"Missing: {self._SCRIPT}"

    def test_script_is_importable(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("som_vpd_merge", self._SCRIPT)
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, "main")
        assert hasattr(mod, "drop_duplicate_time")

    def test_default_input_dir_is_somalia_vpd(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("som_vpd_merge", self._SCRIPT)
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        ns = mod.parse_args.__wrapped__ if hasattr(mod.parse_args, "__wrapped__") else None
        # Parse with no args to get defaults
        import sys as _sys
        old_argv, _sys.argv = _sys.argv[:], [str(self._SCRIPT)]
        try:
            args = mod.parse_args()
        finally:
            _sys.argv = old_argv
        assert "somalia_vapour_pressure_deficit" in args.input_dir
        assert "somalia_vapour_pressure_deficit" in args.output

    def test_script_merges_synthetic_files(self, tmp_path, synthetic_vpd):
        """Script merges a single VPD file successfully (trivial concat)."""
        import shutil
        in_dir = tmp_path / "netcdf"
        in_dir.mkdir()
        shutil.copy(synthetic_vpd, in_dir / "vpd_2010.nc")
        out_file = tmp_path / "merged.nc"

        r = subprocess.run(
            [sys.executable, str(self._SCRIPT),
             "--input-dir", str(in_dir),
             "--output", str(out_file)],
            capture_output=True, text=True, cwd=str(_ROOT),
        )
        assert r.returncode == 0, r.stderr
        assert out_file.exists()

    def test_script_in_merge_script_dict(self):
        """run_historical_workflow.py maps ('somalia', 'vpd') to the new script."""
        import importlib.util
        scripts_dir = str(_ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        hist_path = _ROOT / "scripts" / "run_historical_workflow.py"
        spec = importlib.util.spec_from_file_location("hist_wf", hist_path)
        mod  = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert ("somalia", "vpd") in mod.MERGE_SCRIPT
        assert "somalia_vapour_pressure_deficit" in mod.MERGE_SCRIPT[("somalia", "vpd")]


# ═════════════════════════════════════════════════════════════════════════════
# E — Download status report
# ═════════════════════════════════════════════════════════════════════════════

class TestDownloadReport:
    """Orchestrator accumulates download results; close_run() embeds them in summary."""

    def _make_store(self, tmp_path: Path, run_id: str = "run_dl_test"):
        from agent.state_store import StateStore
        with patch("agent.state_store.manifest_path",
                   return_value=tmp_path / "manifests" / f"{run_id}.json"), \
             patch("agent.state_store.log_path",
                   return_value=tmp_path / "logs" / f"{run_id}.log"):
            return StateStore(run_id, {"countries": ["eth"], "variables": ["tas"],
                                       "scenario": "historical", "period": [2010, 2025]})

    def test_download_report_starts_empty(self, tmp_path):
        from agent.orchestrator import Orchestrator
        store = self._make_store(tmp_path)
        orch  = Orchestrator(store=store)
        assert orch.download_report == []

    def test_download_report_saved_in_manifest_summary(self, tmp_path):
        from agent.state_store import StateStore

        run_id = "run_dl_manifest"
        store  = self._make_store(tmp_path, run_id)

        dl_report = [
            {"label": "AgERA5/tas/2010", "path": "/data/raw/agera5/tas/2010.nc",
             "size_bytes": 1024 * 1024 * 5, "ok": True, "error": ""},
            {"label": "CHIRPS/2010",      "path": "/data/raw/chirps/2010.nc",
             "size_bytes": 0,             "ok": False, "error": "timeout"},
        ]

        store.close_run(output_files=[], diagnostic_files=[],
                        download_report=dl_report)

        manifest_file = tmp_path / "manifests" / f"{run_id}.json"
        manifest = json.loads(manifest_file.read_text())
        dl = manifest["summary"].get("downloads")
        assert dl is not None
        assert dl["total"] == 2
        assert dl["succeeded"] == 1
        assert dl["failed"] == 1
        assert dl["total_mb"] == pytest.approx(5.0, rel=0.01)

    def test_no_downloads_omits_section(self, tmp_path):
        from agent.state_store import StateStore

        run_id = "run_nodl"
        store  = self._make_store(tmp_path, run_id)
        store.close_run(output_files=[], diagnostic_files=[],
                        download_report=None)

        manifest_file = tmp_path / "manifests" / f"{run_id}.json"
        manifest = json.loads(manifest_file.read_text())
        assert "downloads" not in manifest["summary"]

    def test_download_report_files_list_present(self, tmp_path):
        from agent.state_store import StateStore

        run_id = "run_dl_files"
        store  = self._make_store(tmp_path, run_id)

        dl_report = [
            {"label": "AgERA5/rh/2011", "path": "/fake.nc",
             "size_bytes": 2048, "ok": True, "error": ""},
        ]
        store.close_run(output_files=[], diagnostic_files=[],
                        download_report=dl_report)

        manifest_file = tmp_path / "manifests" / f"{run_id}.json"
        manifest = json.loads(manifest_file.read_text())
        files = manifest["summary"]["downloads"]["files"]
        assert len(files) == 1
        assert files[0]["label"] == "AgERA5/rh/2011"
