"""
Tests for agent/orchestrator.py — run_stage, run_tool, run_diagnostics.

All subprocess calls are mocked so no real scripts are executed.
StateStore is constructed with tmp_path redirection so no real manifests
are written to runs/.
"""

from __future__ import annotations
import subprocess
import logging
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pytest

from agent.orchestrator import Orchestrator
from agent.state_store import StateStore
from agent.output_resolver import ExpectedOutput


# ── helpers ───────────────────────────────────────────────────────────────────

_REQUEST = {
    "countries": ["eth"],
    "variables": ["pr"],
    "scenario": "historical",
    "period": [2010, 2025],
}


def _make_store(tmp_path: Path, run_id: str = "run_orch_test") -> StateStore:
    with patch("agent.state_store.manifest_path",
               return_value=tmp_path / "manifests" / f"{run_id}.json"), \
         patch("agent.state_store.log_path",
               return_value=tmp_path / "logs" / f"{run_id}.log"):
        return StateStore(run_id, _REQUEST)


def _completed_process(returncode: int = 0,
                       stdout: str = "done\n",
                       stderr: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


def _exp_output(tmp_path: Path, name: str = "out.nc",
                variable: str = "pr") -> ExpectedOutput:
    return ExpectedOutput(
        path=tmp_path / name,
        variable=variable,
        expected_units="mm/day",
        period=(2010, 2025),
        require_daily_axis=True,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# run_stage
# ═══════════════════════════════════════════════════════════════════════════════

class TestRunStage:
    """Orchestrator.run_stage() — single-slice subprocess with retry."""

    def test_success_returns_true(self, tmp_path):
        store = _make_store(tmp_path)
        orch = Orchestrator(store)
        with patch("subprocess.run", return_value=_completed_process(0)):
            result = orch.run_stage(
                stage="merge", country="eth", variable="pr",
                cmd=["python", "scripts/merge.py"],
            )
        assert result is True

    def test_success_records_success_status(self, tmp_path):
        store = _make_store(tmp_path)
        orch = Orchestrator(store)
        with patch("subprocess.run", return_value=_completed_process(0)):
            orch.run_stage(
                stage="merge", country="eth", variable="pr",
                cmd=["python", "scripts/merge.py"],
            )
        assert store._manifest["stages"][0]["status"] == "SUCCESS"

    def test_failure_returns_false(self, tmp_path):
        store = _make_store(tmp_path)
        orch = Orchestrator(store)
        with patch("subprocess.run", return_value=_completed_process(1)), \
             patch("agent.orchestrator.should_retry", return_value=False):
            result = orch.run_stage(
                stage="merge", country="eth", variable="pr",
                cmd=["python", "scripts/merge.py"],
            )
        assert result is False

    def test_failure_records_failed_status(self, tmp_path):
        store = _make_store(tmp_path)
        orch = Orchestrator(store)
        with patch("subprocess.run", return_value=_completed_process(1)), \
             patch("agent.orchestrator.should_retry", return_value=False):
            orch.run_stage(
                stage="merge", country="eth", variable="pr",
                cmd=["python", "scripts/merge.py"],
            )
        assert store._manifest["stages"][0]["status"] == "FAILED"

    def test_skip_when_already_complete(self, tmp_path):
        store = _make_store(tmp_path)
        store.record_stage(
            stage="merge", country="eth", variable="pr",
            scenario="historical", command="old cmd", status="SUCCESS",
        )
        orch = Orchestrator(store)
        with patch("subprocess.run") as mock_run:
            result = orch.run_stage(
                stage="merge", country="eth", variable="pr",
                scenario="historical",
                cmd=["python", "scripts/merge.py"],
            )
            mock_run.assert_not_called()
        assert result is True

    def test_skip_records_skipped_status(self, tmp_path):
        store = _make_store(tmp_path)
        store.record_stage(
            stage="merge", country="eth", variable="pr",
            scenario="historical", command="old cmd", status="SUCCESS",
        )
        orch = Orchestrator(store)
        with patch("subprocess.run"):
            orch.run_stage(
                stage="merge", country="eth", variable="pr",
                scenario="historical",
                cmd=["python", "scripts/merge.py"],
            )
        statuses = [s["status"] for s in store._manifest["stages"]]
        assert "SKIPPED" in statuses

    def test_retry_called_on_transient_failure(self, tmp_path):
        store = _make_store(tmp_path)
        orch = Orchestrator(store)
        responses = [
            _completed_process(1),
            _completed_process(1),
            _completed_process(0),
        ]
        with patch("subprocess.run", side_effect=responses), \
             patch("agent.orchestrator.should_retry", return_value=True), \
             patch("agent.orchestrator.wait_before_retry"):
            result = orch.run_stage(
                stage="merge", country="eth", variable="pr",
                cmd=["python", "scripts/merge.py"],
            )
        assert result is True

    def test_attempt_count_recorded_on_retry(self, tmp_path):
        store = _make_store(tmp_path)
        orch = Orchestrator(store)
        responses = [_completed_process(1), _completed_process(0)]
        with patch("subprocess.run", side_effect=responses), \
             patch("agent.orchestrator.should_retry", return_value=True), \
             patch("agent.orchestrator.wait_before_retry"):
            orch.run_stage(
                stage="merge", country="eth", variable="pr",
                cmd=["python", "scripts/merge.py"],
            )
        assert store._manifest["stages"][0]["attempt"] == 2

    def test_validator_called_on_success(self, tmp_path):
        store = _make_store(tmp_path)
        orch = Orchestrator(store)
        out = tmp_path / "output.nc"
        out.write_bytes(b"fake")
        validator = MagicMock(return_value={"units": "OK"})
        with patch("subprocess.run", return_value=_completed_process(0)):
            orch.run_stage(
                stage="merge", country="eth", variable="pr",
                cmd=["python", "scripts/merge.py"],
                output_file=str(out),
                validator=validator,
            )
        validator.assert_called_once()

    def test_validator_fail_records_warning_status(self, tmp_path):
        store = _make_store(tmp_path)
        orch = Orchestrator(store)
        out = tmp_path / "output.nc"
        out.write_bytes(b"fake")
        validator = MagicMock(return_value={"units": "FAIL"})
        with patch("subprocess.run", return_value=_completed_process(0)):
            result = orch.run_stage(
                stage="merge", country="eth", variable="pr",
                cmd=["python", "scripts/merge.py"],
                output_file=str(out),
                validator=validator,
            )
        assert result is False
        assert store._manifest["stages"][0]["status"] == "WARNING"

    def test_stdout_stderr_captured(self, tmp_path):
        store = _make_store(tmp_path)
        orch = Orchestrator(store)
        with patch("subprocess.run",
                   return_value=_completed_process(0, stdout="ok\n", stderr="warn\n")):
            orch.run_stage(
                stage="merge", country="eth", variable="pr",
                cmd=["python", "scripts/merge.py"],
            )
        s = store._manifest["stages"][0]
        assert "ok" in s["stdout_tail"]
        assert "warn" in s["stderr_tail"]

    def test_input_files_passed_to_record(self, tmp_path):
        store = _make_store(tmp_path)
        orch = Orchestrator(store)
        with patch("subprocess.run", return_value=_completed_process(0)):
            orch.run_stage(
                stage="merge", country="eth", variable="pr",
                cmd=["python", "scripts/merge.py"],
                input_files=["data/raw/a.nc"],
            )
        assert "data/raw/a.nc" in store._manifest["stages"][0]["input_files"]


# ═══════════════════════════════════════════════════════════════════════════════
# run_tool
# ═══════════════════════════════════════════════════════════════════════════════

class TestRunTool:
    """Orchestrator.run_tool() — top-level workflow script with output validation."""

    def test_success_no_outputs_returns_true(self, tmp_path):
        store = _make_store(tmp_path)
        orch = Orchestrator(store)
        with patch("subprocess.run", return_value=_completed_process(0)), \
             patch("agent.orchestrator.SCRIPTS_DIR", tmp_path):
            result = orch.run_tool(
                stage="regrid", script_name="regrid.py", args=["--input", "a.nc"],
                countries=["eth"], variables=["pr"], scenario="historical",
            )
        assert result is True

    def test_success_records_success_status(self, tmp_path):
        store = _make_store(tmp_path)
        orch = Orchestrator(store)
        with patch("subprocess.run", return_value=_completed_process(0)), \
             patch("agent.orchestrator.SCRIPTS_DIR", tmp_path):
            orch.run_tool(
                stage="regrid", script_name="regrid.py", args=[],
                countries=["eth"], variables=["pr"], scenario="historical",
            )
        assert store._manifest["stages"][0]["status"] == "SUCCESS"

    def test_failure_returns_false(self, tmp_path):
        store = _make_store(tmp_path)
        orch = Orchestrator(store)
        with patch("subprocess.run", return_value=_completed_process(1)), \
             patch("agent.orchestrator.should_retry", return_value=False), \
             patch("agent.orchestrator.SCRIPTS_DIR", tmp_path):
            result = orch.run_tool(
                stage="regrid", script_name="regrid.py", args=[],
                countries=["eth"], variables=["pr"], scenario="historical",
            )
        assert result is False

    def test_failure_records_failed_status(self, tmp_path):
        store = _make_store(tmp_path)
        orch = Orchestrator(store)
        with patch("subprocess.run", return_value=_completed_process(1)), \
             patch("agent.orchestrator.should_retry", return_value=False), \
             patch("agent.orchestrator.SCRIPTS_DIR", tmp_path):
            orch.run_tool(
                stage="regrid", script_name="regrid.py", args=[],
                countries=["eth"], variables=["pr"], scenario="historical",
            )
        assert store._manifest["stages"][0]["status"] == "FAILED"

    def test_skips_when_already_complete(self, tmp_path):
        store = _make_store(tmp_path)
        store.record_stage(
            stage="regrid", country="eth", variable="pr",
            scenario="historical", command="old", status="SUCCESS",
        )
        orch = Orchestrator(store)
        with patch("subprocess.run") as mock_run, \
             patch("agent.orchestrator.SCRIPTS_DIR", tmp_path):
            result = orch.run_tool(
                stage="regrid", script_name="regrid.py", args=[],
                countries=["eth"], variables=["pr"], scenario="historical",
            )
            mock_run.assert_not_called()
        assert result is True

    def test_validation_called_when_expected_outputs_given(self, tmp_path):
        store = _make_store(tmp_path)
        orch = Orchestrator(store)
        exp = _exp_output(tmp_path)
        with patch("subprocess.run", return_value=_completed_process(0)), \
             patch("agent.orchestrator.SCRIPTS_DIR", tmp_path), \
             patch("agent.orchestrator._run_output_validation",
                   return_value=({}, True)) as mock_val:
            orch.run_tool(
                stage="regrid", script_name="regrid.py", args=[],
                countries=["eth"], variables=["pr"], scenario="historical",
                expected_outputs=[exp],
            )
        mock_val.assert_called_once()

    def test_validation_fail_strict_returns_false(self, tmp_path):
        store = _make_store(tmp_path)
        orch = Orchestrator(store, fast_mode=False)
        exp = _exp_output(tmp_path)
        with patch("subprocess.run", return_value=_completed_process(0)), \
             patch("agent.orchestrator.SCRIPTS_DIR", tmp_path), \
             patch("agent.orchestrator._run_output_validation",
                   return_value=({"out.nc": {"units": "FAIL"}}, False)):
            result = orch.run_tool(
                stage="regrid", script_name="regrid.py", args=[],
                countries=["eth"], variables=["pr"], scenario="historical",
                expected_outputs=[exp],
            )
        assert result is False

    def test_validation_fail_fast_mode_returns_true(self, tmp_path):
        store = _make_store(tmp_path)
        orch = Orchestrator(store, fast_mode=True)
        exp = _exp_output(tmp_path)
        with patch("subprocess.run", return_value=_completed_process(0)), \
             patch("agent.orchestrator.SCRIPTS_DIR", tmp_path), \
             patch("agent.orchestrator._run_output_validation",
                   return_value=({"out.nc": {"units": "FAIL"}}, False)):
            result = orch.run_tool(
                stage="regrid", script_name="regrid.py", args=[],
                countries=["eth"], variables=["pr"], scenario="historical",
                expected_outputs=[exp],
            )
        assert result is True

    def test_validation_summary_stored_in_manifest(self, tmp_path):
        store = _make_store(tmp_path)
        orch = Orchestrator(store)
        exp = _exp_output(tmp_path)
        val_summary = {"out.nc": {"existence": "OK", "units": "OK"}}
        with patch("subprocess.run", return_value=_completed_process(0)), \
             patch("agent.orchestrator.SCRIPTS_DIR", tmp_path), \
             patch("agent.orchestrator._run_output_validation",
                   return_value=(val_summary, True)):
            orch.run_tool(
                stage="regrid", script_name="regrid.py", args=[],
                countries=["eth"], variables=["pr"], scenario="historical",
                expected_outputs=[exp],
            )
        recorded_val = store._manifest["stages"][0]["validation"]
        assert "out.nc" in recorded_val

    def test_country_and_variable_joined_as_keys(self, tmp_path):
        store = _make_store(tmp_path)
        orch = Orchestrator(store)
        with patch("subprocess.run", return_value=_completed_process(0)), \
             patch("agent.orchestrator.SCRIPTS_DIR", tmp_path):
            orch.run_tool(
                stage="regrid", script_name="regrid.py", args=[],
                countries=["eth", "ken"], variables=["pr", "tas"],
                scenario="historical",
            )
        s = store._manifest["stages"][0]
        assert s["country"] == "eth,ken"
        assert s["variable"] == "pr,tas"

    def test_retry_on_transient_failure(self, tmp_path):
        store = _make_store(tmp_path)
        orch = Orchestrator(store)
        responses = [_completed_process(1), _completed_process(0)]
        with patch("subprocess.run", side_effect=responses), \
             patch("agent.orchestrator.should_retry", return_value=True), \
             patch("agent.orchestrator.wait_before_retry"), \
             patch("agent.orchestrator.SCRIPTS_DIR", tmp_path):
            result = orch.run_tool(
                stage="regrid", script_name="regrid.py", args=[],
                countries=["eth"], variables=["pr"], scenario="historical",
            )
        assert result is True
        assert store._manifest["stages"][0]["attempt"] == 2


# ═══════════════════════════════════════════════════════════════════════════════
# run_diagnostics
# ═══════════════════════════════════════════════════════════════════════════════

class TestRunDiagnostics:
    """Orchestrator.run_diagnostics() — per-output diagnostic plot generation."""

    def test_missing_output_skipped_with_warning(self, tmp_path, caplog):
        store = _make_store(tmp_path)
        orch = Orchestrator(store)
        exp = _exp_output(tmp_path, "nonexistent.nc")

        with caplog.at_level(logging.WARNING, logger="agent.orchestrator"), \
             patch("subprocess.run") as mock_run:
            produced, qc = orch.run_diagnostics("run_test", [exp])
            mock_run.assert_not_called()

        assert produced == []
        assert any("nonexistent.nc" in r.message for r in caplog.records
                   if r.levelno == logging.WARNING)

    def test_subprocess_failure_logs_warning(self, tmp_path, caplog):
        store = _make_store(tmp_path)
        orch = Orchestrator(store)
        out = tmp_path / "output.nc"
        out.write_bytes(b"fake")
        exp = _exp_output(tmp_path, "output.nc")

        with caplog.at_level(logging.WARNING, logger="agent.orchestrator"), \
             patch("subprocess.run",
                   return_value=_completed_process(1, stderr="error msg")), \
             patch("agent.orchestrator.SCRIPTS_DIR", tmp_path), \
             patch("agent.orchestrator.diagnostics_dir", return_value=tmp_path / "diag"):
            produced, qc = orch.run_diagnostics("run_test", [exp])

        assert produced == []
        assert any("Diagnostics failed" in r.message for r in caplog.records)

    def test_success_returns_png_path(self, tmp_path):
        store = _make_store(tmp_path)
        orch = Orchestrator(store)
        out = tmp_path / "output.nc"
        out.write_bytes(b"fake")
        exp = _exp_output(tmp_path, "output.nc")
        diag_dir = tmp_path / "diag"
        diag_dir.mkdir()
        png = diag_dir / "output_diagnostic.png"
        png.write_bytes(b"PNG")

        with patch("subprocess.run", return_value=_completed_process(0)), \
             patch("agent.orchestrator.SCRIPTS_DIR", tmp_path), \
             patch("agent.orchestrator.diagnostics_dir", return_value=diag_dir):
            produced, qc = orch.run_diagnostics("run_test", [exp])

        assert str(png) in produced

    def test_multiple_outputs_processed_independently(self, tmp_path):
        store = _make_store(tmp_path)
        orch = Orchestrator(store)
        diag_dir = tmp_path / "diag"
        diag_dir.mkdir()

        outs = []
        for name in ("a.nc", "b.nc"):
            p = tmp_path / name
            p.write_bytes(b"fake")
            outs.append(_exp_output(tmp_path, name, variable="pr"))
            (diag_dir / f"{name.replace('.nc', '')}_diagnostic.png").write_bytes(b"PNG")

        with patch("subprocess.run", return_value=_completed_process(0)), \
             patch("agent.orchestrator.SCRIPTS_DIR", tmp_path), \
             patch("agent.orchestrator.diagnostics_dir", return_value=diag_dir):
            produced, qc = orch.run_diagnostics("run_test", outs)

        assert len(produced) == 2

    def test_missing_png_not_added_to_produced(self, tmp_path):
        store = _make_store(tmp_path)
        orch = Orchestrator(store)
        out = tmp_path / "output.nc"
        out.write_bytes(b"fake")
        exp = _exp_output(tmp_path, "output.nc")
        diag_dir = tmp_path / "diag"
        diag_dir.mkdir()

        with patch("subprocess.run", return_value=_completed_process(0)), \
             patch("agent.orchestrator.SCRIPTS_DIR", tmp_path), \
             patch("agent.orchestrator.diagnostics_dir", return_value=diag_dir):
            produced, qc = orch.run_diagnostics("run_test", [exp])

        assert produced == []

    def test_partial_failure_continues_remaining(self, tmp_path):
        store = _make_store(tmp_path)
        orch = Orchestrator(store)
        diag_dir = tmp_path / "diag"
        diag_dir.mkdir()

        fail_out = tmp_path / "fail.nc"
        fail_out.write_bytes(b"fake")
        ok_out = tmp_path / "ok.nc"
        ok_out.write_bytes(b"fake")
        (diag_dir / "ok_diagnostic.png").write_bytes(b"PNG")

        exps = [
            _exp_output(tmp_path, "fail.nc"),
            _exp_output(tmp_path, "ok.nc"),
        ]
        responses = [_completed_process(1, stderr="err"), _completed_process(0)]

        with patch("subprocess.run", side_effect=responses), \
             patch("agent.orchestrator.SCRIPTS_DIR", tmp_path), \
             patch("agent.orchestrator.diagnostics_dir", return_value=diag_dir):
            produced, qc = orch.run_diagnostics("run_test", exps)

        assert len(produced) == 1
        assert str(diag_dir / "ok_diagnostic.png") in produced

    def test_qc_json_sidecar_loaded_into_returned_dict(self, tmp_path):
        store = _make_store(tmp_path)
        orch = Orchestrator(store)
        out = tmp_path / "output.nc"
        out.write_bytes(b"fake")
        exp = _exp_output(tmp_path, "output.nc")
        diag_dir = tmp_path / "diag"
        diag_dir.mkdir()
        (diag_dir / "output_diagnostic.png").write_bytes(b"PNG")
        # Write a fake QC sidecar that diagnose_final_netcdf.py would normally produce
        import json as _json
        qc_data = {"coverage": {"finite_ratio": 0.97}, "value_stats": {"mean": 42.0}}
        (diag_dir / "output_qc.json").write_text(_json.dumps(qc_data))

        with patch("subprocess.run", return_value=_completed_process(0)), \
             patch("agent.orchestrator.SCRIPTS_DIR", tmp_path), \
             patch("agent.orchestrator.diagnostics_dir", return_value=diag_dir):
            produced, qc = orch.run_diagnostics("run_test", [exp])

        assert "output.nc" in qc
        assert qc["output.nc"]["coverage"]["finite_ratio"] == 0.97


# ── _apply_legacy_rename ──────────────────────────────────────────────────────

class TestApplyLegacyRename:
    """orchestrator._apply_legacy_rename() — hardcoded-period rename logic."""

    def test_returns_true_when_primary_exists(self, tmp_path):
        from agent.orchestrator import _apply_legacy_rename
        primary = tmp_path / "primary.nc"
        primary.write_bytes(b"data")
        exp = ExpectedOutput(path=primary, variable="rh",
                             expected_units=None, period=(2010, 2025))
        assert _apply_legacy_rename(exp) is True
        assert primary.exists()

    def test_renames_legacy_to_primary_when_primary_missing(self, tmp_path):
        from agent.orchestrator import _apply_legacy_rename
        primary = tmp_path / "primary_2015_2020.nc"
        legacy  = tmp_path / "legacy_2010_2025.nc"
        legacy.write_bytes(b"data")
        exp = ExpectedOutput(path=primary, variable="rh",
                             expected_units=None, period=(2015, 2020),
                             legacy_path=legacy)
        result = _apply_legacy_rename(exp)
        assert result is True
        assert primary.exists()
        assert not legacy.exists()

    def test_returns_false_when_neither_exists(self, tmp_path):
        from agent.orchestrator import _apply_legacy_rename
        primary = tmp_path / "primary.nc"
        legacy  = tmp_path / "legacy.nc"
        exp = ExpectedOutput(path=primary, variable="rh",
                             expected_units=None, period=(2010, 2025),
                             legacy_path=legacy)
        assert _apply_legacy_rename(exp) is False

    def test_returns_false_when_legacy_is_none_and_primary_missing(self, tmp_path):
        from agent.orchestrator import _apply_legacy_rename
        primary = tmp_path / "missing.nc"
        exp = ExpectedOutput(path=primary, variable="rh",
                             expected_units=None, period=(2010, 2025))
        assert _apply_legacy_rename(exp) is False

    def test_primary_unchanged_when_it_already_exists(self, tmp_path):
        from agent.orchestrator import _apply_legacy_rename
        primary = tmp_path / "primary.nc"
        primary.write_bytes(b"CORRECT")
        legacy  = tmp_path / "legacy.nc"
        legacy.write_bytes(b"LEGACY")
        exp = ExpectedOutput(path=primary, variable="rh",
                             expected_units=None, period=(2010, 2025),
                             legacy_path=legacy)
        _apply_legacy_rename(exp)
        assert primary.read_bytes() == b"CORRECT"  # not overwritten by legacy
