"""
test_new_features.py — Tests for fixes 11–14:

  - Orchestrator integration test (real subprocess, synthetic fixture)
  - --resume logic (StateStore.resume + Orchestrator skip)
  - Preflight CDS credentials check
  - Parallel worker execution via --workers flag
"""

from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_FIXTURES = _ROOT / "tests" / "fixtures"


# ─────────────────────────────────────────────────────────────────────────────
# Helper: run run_agent.py as a subprocess
# ─────────────────────────────────────────────────────────────────────────────

def _run_agent(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_ROOT / "run_agent.py")] + args,
        capture_output=True, text=True, cwd=str(_ROOT),
    )


# ═════════════════════════════════════════════════════════════════════════════
# 11 — Orchestrator integration test with a real subprocess
# ═════════════════════════════════════════════════════════════════════════════

class TestOrchestratorIntegration:
    """
    Run a real (lightweight) Python script via Orchestrator.run_stage() and
    verify the manifest records the correct exit code and status.
    """

    def _make_store(self, tmp_path: Path, run_id: str = "run_integ_test"):
        from agent.state_store import StateStore
        with patch("agent.state_store.manifest_path",
                   return_value=tmp_path / "manifests" / f"{run_id}.json"), \
             patch("agent.state_store.log_path",
                   return_value=tmp_path / "logs" / f"{run_id}.log"):
            return StateStore(run_id, {"countries": ["eth"], "variables": ["pr"],
                                       "scenario": "historical", "period": [2010, 2025]})

    def test_run_stage_succeeds_for_echo_script(self, tmp_path):
        """Orchestrator.run_stage() returns True when subprocess exits 0."""
        from agent.orchestrator import Orchestrator

        store = self._make_store(tmp_path)
        orch = Orchestrator(store=store, fast_mode=True)

        ok = orch.run_stage(
            stage="validate",
            country="eth",
            variable="pr",
            cmd=[sys.executable, "-c", "import sys; sys.exit(0)"],
        )
        assert ok is True

    def test_run_stage_fails_for_nonzero_exit(self, tmp_path):
        """Orchestrator.run_stage() returns False when subprocess exits non-zero."""
        from agent.orchestrator import Orchestrator

        store = self._make_store(tmp_path)
        orch = Orchestrator(store=store, fast_mode=True)

        ok = orch.run_stage(
            stage="validate",
            country="eth",
            variable="pr",
            cmd=[sys.executable, "-c", "import sys; sys.exit(1)"],
        )
        assert ok is False

    def test_manifest_records_stage_on_success(self, tmp_path):
        """Completed stage is written to manifest with status SUCCESS."""
        from agent.orchestrator import Orchestrator

        run_id = "run_manifest_integ"
        store = self._make_store(tmp_path, run_id)
        orch = Orchestrator(store=store, fast_mode=True)

        orch.run_stage(
            stage="validate",
            country="eth",
            variable="tas",
            cmd=[sys.executable, "-c", "print('ok')"],
        )
        manifest_file = tmp_path / "manifests" / f"{run_id}.json"
        manifest = json.loads(manifest_file.read_text())
        statuses = [s["status"] for s in manifest["stages"]]
        assert "SUCCESS" in statuses

    def test_run_stage_with_synthetic_fixture(self, tmp_path, synthetic_tas):
        """
        Orchestrator.run_stage() succeeds running a real Python command that
        reads the synthetic tas fixture and exits 0.
        """
        from agent.orchestrator import Orchestrator

        store = self._make_store(tmp_path)
        orch = Orchestrator(store=store, fast_mode=True)

        cmd = [
            sys.executable, "-c",
            f"import xarray as xr; ds = xr.open_dataset(r'{synthetic_tas}'); print(list(ds.data_vars))"
        ]
        ok = orch.run_stage(
            stage="validate",
            country="eth",
            variable="tas",
            cmd=cmd,
        )
        assert ok is True

    def test_run_stage_skips_completed(self, tmp_path):
        """A stage that is already SUCCESS in the manifest is skipped (returns True)."""
        from agent.orchestrator import Orchestrator
        from agent.state_store import StateStore

        store = self._make_store(tmp_path)
        # Manually mark the stage as complete
        store.record_stage(
            stage="merge", country="eth", variable="pr",
            command="dummy", status="SUCCESS",
        )
        orch = Orchestrator(store=store, fast_mode=True)

        # This command would fail — but it should be skipped
        ok = orch.run_stage(
            stage="merge",
            country="eth",
            variable="pr",
            cmd=[sys.executable, "-c", "import sys; sys.exit(1)"],
        )
        assert ok is True


# ═════════════════════════════════════════════════════════════════════════════
# 12 — --resume logic
# ═════════════════════════════════════════════════════════════════════════════

class TestResumeLogic:
    """StateStore.resume() carries completed stages; is_complete() returns True for them."""

    def _write_manifest(self, path: Path, run_id: str, stages: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "run_id": run_id,
            "timestamp": "2026-01-01T00:00:00+00:00",
            "request": {"countries": ["eth"], "variables": ["tas"],
                        "scenario": "historical", "period": [2010, 2025]},
            "environment": {"python_version": "3.11.0"},
            "stages": stages,
            "summary": {},
        }))

    def test_resume_carries_success_stages(self, tmp_path):
        """StateStore.resume() populates is_complete() for SUCCESS stages."""
        from agent.state_store import StateStore

        prior_id = "run_prior"
        new_id = "run_resumed"
        prior_path = tmp_path / "manifests" / f"{prior_id}.json"
        self._write_manifest(prior_path, prior_id, [
            {"stage": "merge", "country": "eth", "variable": "tas",
             "scenario": "historical", "status": "SUCCESS",
             "command": "dummy", "exit_code": 0},
        ])

        with patch("agent.state_store.manifest_path",
                   side_effect=lambda rid: tmp_path / "manifests" / f"{rid}.json"), \
             patch("agent.state_store.log_path",
                   return_value=tmp_path / "logs" / f"{new_id}.log"):
            store = StateStore.resume(prior_id, new_id,
                                      {"countries": ["eth"], "variables": ["tas"],
                                       "scenario": "historical", "period": [2010, 2025]})

        assert store.is_complete("merge", "eth", "tas", "historical")

    def test_resume_does_not_carry_failed_stages(self, tmp_path):
        """StateStore.resume() does NOT mark FAILED stages as complete."""
        from agent.state_store import StateStore

        prior_id = "run_prior_f"
        new_id = "run_resumed_f"
        prior_path = tmp_path / "manifests" / f"{prior_id}.json"
        self._write_manifest(prior_path, prior_id, [
            {"stage": "merge", "country": "eth", "variable": "tas",
             "scenario": "historical", "status": "FAILED",
             "command": "dummy", "exit_code": 1},
        ])

        with patch("agent.state_store.manifest_path",
                   side_effect=lambda rid: tmp_path / "manifests" / f"{rid}.json"), \
             patch("agent.state_store.log_path",
                   return_value=tmp_path / "logs" / f"{new_id}.log"):
            store = StateStore.resume(prior_id, new_id,
                                      {"countries": ["eth"], "variables": ["tas"],
                                       "scenario": "historical", "period": [2010, 2025]})

        assert not store.is_complete("merge", "eth", "tas", "historical")

    def test_resume_missing_prior_raises(self, tmp_path):
        """StateStore.resume() raises FileNotFoundError for a non-existent prior run."""
        from agent.state_store import StateStore

        with patch("agent.state_store.manifest_path",
                   side_effect=lambda rid: tmp_path / "manifests" / f"{rid}.json"), \
             patch("agent.state_store.log_path",
                   return_value=tmp_path / "logs" / "run_x.log"):
            with pytest.raises(FileNotFoundError, match="Prior run manifest not found"):
                StateStore.resume("nonexistent_run", "run_new",
                                  {"countries": ["eth"], "variables": ["tas"],
                                   "scenario": "historical", "period": [2010, 2025]})

    def test_resume_orchestrator_skips_complete_stage(self, tmp_path):
        """
        After resume, Orchestrator.run_stage() skips a stage that was SUCCESS
        in the prior run — the failing command is never executed.
        """
        from agent.state_store import StateStore
        from agent.orchestrator import Orchestrator

        prior_id = "run_orch_prior"
        new_id = "run_orch_resumed"
        prior_path = tmp_path / "manifests" / f"{prior_id}.json"
        self._write_manifest(prior_path, prior_id, [
            {"stage": "merge", "country": "eth", "variable": "rh",
             "scenario": "historical", "status": "SUCCESS",
             "command": "dummy", "exit_code": 0},
        ])

        with patch("agent.state_store.manifest_path",
                   side_effect=lambda rid: tmp_path / "manifests" / f"{rid}.json"), \
             patch("agent.state_store.log_path",
                   return_value=tmp_path / "logs" / f"{new_id}.log"):
            store = StateStore.resume(prior_id, new_id,
                                      {"countries": ["eth"], "variables": ["rh"],
                                       "scenario": "historical", "period": [2010, 2025]})

        orch = Orchestrator(store=store, fast_mode=True)
        ok = orch.run_stage(
            stage="merge", country="eth", variable="rh",
            scenario="historical",
            cmd=[sys.executable, "-c", "import sys; sys.exit(99)"],  # would fail
        )
        assert ok is True  # skipped, not executed

    def test_dry_run_resume_flag_accepted(self):
        """run_agent.py --resume <id> --dry-run exits 0 for a valid resume flag."""
        r = _run_agent([
            "--countries", "eth", "--variables", "tas",
            "--scenario", "historical", "--period", "2010", "2025",
            "--skip-preflight", "--dry-run",
            "--resume", "run_99991231_999999",
        ])
        # May exit 0 (DRY RUN shows plan) or non-zero (manifest not found):
        # either is acceptable — we just verify it doesn't crash with AttributeError
        assert "AttributeError" not in r.stderr
        assert "Traceback" not in r.stderr or "FileNotFoundError" in r.stderr


# ═════════════════════════════════════════════════════════════════════════════
# 13 — Preflight CDS credentials check
# ═════════════════════════════════════════════════════════════════════════════

class TestCheckCdsCredentials:
    """Unit tests for agent.preflight.check_cds_credentials()."""

    def test_ok_when_cdsapirc_exists_and_nonempty(self, tmp_path):
        from agent.preflight import check_cds_credentials

        cdsapirc = tmp_path / ".cdsapirc"
        cdsapirc.write_text("url: https://cds.climate.copernicus.eu/api/v2\nkey: 12345:abc\n")

        with patch("agent.preflight.Path.home", return_value=tmp_path):
            result = check_cds_credentials()
        assert result == "OK"

    def test_missing_when_cdsapirc_absent(self, tmp_path):
        from agent.preflight import check_cds_credentials

        with patch("agent.preflight.Path.home", return_value=tmp_path):
            result = check_cds_credentials()
        assert result.startswith("MISSING")
        assert ".cdsapirc" in result

    def test_empty_file_reported(self, tmp_path):
        from agent.preflight import check_cds_credentials

        cdsapirc = tmp_path / ".cdsapirc"
        cdsapirc.write_text("")

        with patch("agent.preflight.Path.home", return_value=tmp_path):
            result = check_cds_credentials()
        assert result.startswith("EMPTY")

    def test_missing_creds_is_warning_not_error_in_preflight(self, tmp_path):
        """check_cds_credentials() failure surfaces as WARNING in run_preflight(), not ERROR."""
        from agent.preflight import run_preflight

        request = {"countries": ["eth"], "variables": ["tas"],
                   "scenario": "historical", "period": [2010, 2025]}

        with patch("agent.preflight.Path.home", return_value=tmp_path), \
             patch("agent.preflight.check_dependencies", return_value={}), \
             patch("agent.preflight.check_scripts",
                   return_value={"run_historical_workflow.py": "OK",
                                 "run_projection_workflow.py": "OK",
                                 "run_future_vpd_workflow.py": "OK"}), \
             patch("agent.preflight.check_reference_grid", return_value="OK"), \
             patch("agent.preflight.check_boundaries",
                   return_value={"eth": "OK"}), \
             patch("agent.preflight.check_source_dirs", return_value={}):
            report = run_preflight(request)

        # CDS missing → warning, not error
        assert any("CDS" in w or "cdsapirc" in w for w in report.warnings)
        cds_errors = [e for e in report.errors if "cdsapirc" in e or "CDS" in e]
        assert not cds_errors


# ═════════════════════════════════════════════════════════════════════════════
# 14 — Parallel worker execution
# ═════════════════════════════════════════════════════════════════════════════

class TestParallelWorkers:
    """run_agent.py --workers N should accept N>1 and exit cleanly in dry-run mode."""

    def test_workers_2_dry_run_exits_zero(self):
        r = _run_agent([
            "--countries", "eth", "ken",
            "--variables", "tas", "pr",
            "--scenario", "historical",
            "--period", "2010", "2020",
            "--workers", "2",
            "--skip-preflight", "--dry-run",
        ])
        assert r.returncode == 0, r.stderr

    def test_workers_4_dry_run_exits_zero(self):
        r = _run_agent([
            "--countries", "eth", "ken", "som",
            "--variables", "tas",
            "--scenario", "ssp245",
            "--period", "2040", "2070",
            "--workers", "4",
            "--skip-preflight", "--dry-run",
        ])
        assert r.returncode == 0, r.stderr

    def test_workers_1_and_n_produce_same_plan(self):
        """Single-worker and multi-worker dry runs should list the same stages."""
        base_args = [
            "--countries", "eth",
            "--variables", "tas", "rh",
            "--scenario", "historical",
            "--period", "2010", "2020",
            "--skip-preflight", "--dry-run",
        ]
        r1 = _run_agent(base_args + ["--workers", "1"])
        r2 = _run_agent(base_args + ["--workers", "2"])
        assert r1.returncode == 0 and r2.returncode == 0
        # Both must mention the same stage names
        for stage in ("run_historical_workflow.py",):
            assert stage in r1.stdout
            assert stage in r2.stdout

    def test_workers_greater_than_slices_accepted(self):
        """Requesting more workers than slices should not crash."""
        r = _run_agent([
            "--countries", "eth",
            "--variables", "tas",
            "--scenario", "historical",
            "--period", "2010", "2020",
            "--workers", "16",
            "--skip-preflight", "--dry-run",
        ])
        assert r.returncode == 0, r.stderr

    def test_workers_zero_exits_nonzero(self):
        """--workers 0 should be rejected (argparse minimum or runtime check)."""
        r = _run_agent([
            "--countries", "eth", "--variables", "tas",
            "--scenario", "historical", "--period", "2010", "2020",
            "--workers", "0", "--skip-preflight", "--dry-run",
        ])
        assert r.returncode != 0
