"""
test_gap_fixes.py — Tests for the 11 codebase gaps fixed in the latest commit.

  Fix 1:  --diagnostics-only workflow routing
  Fix 2:  VPD Tetens coefficients (6.1078, 17.27, 237.3)
  Fix 3:  Fast-mode status bug (strict mode → FAILED, not WARNING)
  Fix 4:  StateStore.resume() scenario-mismatch guard
  Fix 5:  output_resolver uses _HIST_LEGACY_PERIOD (not hardcoded)
  Fix 6:  _classify_subprocess_error() actionable error messages
  Fix 7:  _validate_config() warns on missing agent_config.yaml sections
  Fix 8:  codes/ symlink verification raises RuntimeError on failure
  Fix 9:  preflight uses connector availability checkers (not raw dir exists)
  Fix 10: schema load failure logs warning instead of silently disabling
  Fix 11: historical missing sources → warning; ISIMIP → error
"""

from __future__ import annotations
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).resolve().parents[1]


# ═════════════════════════════════════════════════════════════════════════════
# Fix 1 — --diagnostics-only workflow routing
# ═════════════════════════════════════════════════════════════════════════════

class TestDiagnosticsOnlyRouting:
    """TaskRouter produces a diagnostics-only plan when request flag is set."""

    def _route(self, scenario="historical", variables=None):
        from agent.task_router import TaskRouter
        return TaskRouter().route({
            "countries": ["eth"],
            "variables": variables or ["tas"],
            "scenario": scenario,
            "period": [2010, 2025],
            "diagnostics_only": True,
        })

    def test_run_type_is_diagnostics(self):
        plan = self._route()
        assert plan.run_type == "diagnostics"

    def test_diagnostics_only_flag_set(self):
        plan = self._route()
        assert plan.diagnostics_only is True

    def test_diagnostics_flag_set(self):
        plan = self._route()
        assert plan.diagnostics is True

    def test_stages_carry_expected_outputs(self):
        plan = self._route()
        assert len(plan.stages) > 0
        assert all(len(s.expected_outputs) > 0 for s in plan.stages)

    def test_projection_diagnostics_only(self):
        plan = self._route(scenario="ssp245", variables=["tas"])
        assert plan.run_type == "diagnostics"
        assert plan.diagnostics_only is True

    def test_vpd_diagnostics_only(self):
        plan = self._route(scenario="ssp245", variables=["vpd"])
        assert plan.run_type == "diagnostics"
        assert plan.diagnostics_only is True

    def test_normal_route_is_not_diagnostics_only(self):
        from agent.task_router import TaskRouter
        plan = TaskRouter().route({
            "countries": ["eth"], "variables": ["tas"],
            "scenario": "historical", "period": [2010, 2025],
        })
        assert plan.diagnostics_only is False
        assert plan.run_type != "diagnostics"


# ═════════════════════════════════════════════════════════════════════════════
# Fix 2 — VPD Tetens coefficients
# ═════════════════════════════════════════════════════════════════════════════

class TestVpdTetensCoefficients:
    """run_future_vpd_workflow.py uses the spec Tetens constants."""

    def _load_vpd_module(self):
        import importlib.util
        scripts_dir = str(_ROOT / "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        spec = importlib.util.spec_from_file_location(
            "vpd_wf_test", _ROOT / "scripts" / "run_future_vpd_workflow.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_spec_coefficient_6_1078_present(self):
        import inspect
        mod = self._load_vpd_module()
        src = inspect.getsource(mod.compute_vpd_dataset)
        assert "6.1078" in src, "Expected Tetens coefficient 6.1078 not found"

    def test_spec_coefficient_17_27_present(self):
        import inspect
        mod = self._load_vpd_module()
        src = inspect.getsource(mod.compute_vpd_dataset)
        assert "17.27" in src, "Expected Tetens coefficient 17.27 not found"

    def test_spec_coefficient_237_3_present(self):
        import inspect
        mod = self._load_vpd_module()
        src = inspect.getsource(mod.compute_vpd_dataset)
        assert "237.3" in src, "Expected Tetens coefficient 237.3 not found"

    def test_formula_attr_matches_spec(self):
        import inspect
        mod = self._load_vpd_module()
        src = inspect.getsource(mod.compute_vpd_dataset)
        assert "6.1078" in src
        assert "17.27" in src
        assert "237.3" in src
        # Wrong Magnus constants must not appear
        assert "6.112 " not in src
        assert "17.67" not in src
        assert "243.5" not in src


# ═════════════════════════════════════════════════════════════════════════════
# Fix 3 — Fast-mode / strict-mode validation status
# ═════════════════════════════════════════════════════════════════════════════

class TestFastModeValidationStatus:
    """Strict mode records FAILED on validation failure; fast mode records WARNING."""

    def _make_orch(self, fast_mode: bool):
        from agent.orchestrator import Orchestrator
        store = MagicMock()
        store.is_complete.return_value = False
        return Orchestrator(store=store, fast_mode=fast_mode), store

    def _run_tool_with_failed_validation(self, orch, store):
        fake_output = MagicMock()
        fake_output.path = Path("/nonexistent/output.nc")

        with patch("subprocess.run") as mock_run, \
             patch("agent.orchestrator._run_output_validation",
                   return_value=({"out.nc": {"existence": "FAIL"}}, False)):
            mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
            result = orch.run_tool(
                stage="merge",
                script_name="run_historical_workflow.py",
                args=["--country", "ethiopia"],
                countries=["eth"], variables=["tas"],
                scenario="historical",
                expected_outputs=[fake_output],
            )
        return result, store.record_stage.call_args.kwargs["status"]

    def test_strict_mode_validation_fail_records_failed(self):
        orch, store = self._make_orch(fast_mode=False)
        result, status = self._run_tool_with_failed_validation(orch, store)
        assert result is False
        assert status == "FAILED"

    def test_strict_mode_validation_fail_returns_false(self):
        orch, store = self._make_orch(fast_mode=False)
        result, _ = self._run_tool_with_failed_validation(orch, store)
        assert result is False

    def test_fast_mode_validation_fail_records_warning(self):
        orch, store = self._make_orch(fast_mode=True)
        result, status = self._run_tool_with_failed_validation(orch, store)
        assert status == "WARNING"

    def test_fast_mode_validation_fail_returns_true(self):
        orch, store = self._make_orch(fast_mode=True)
        result, _ = self._run_tool_with_failed_validation(orch, store)
        assert result is True

    def test_success_records_success_in_both_modes(self):
        for fast in (True, False):
            orch, store = self._make_orch(fast_mode=fast)
            with patch("subprocess.run") as mock_run, \
                 patch("agent.orchestrator._run_output_validation",
                       return_value=({}, True)):
                mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
                orch.run_tool(
                    stage="merge", script_name="run_historical_workflow.py",
                    args=[], countries=["eth"], variables=["tas"],
                    scenario="historical", expected_outputs=[],
                )
            status = store.record_stage.call_args.kwargs["status"]
            assert status == "SUCCESS", f"Expected SUCCESS in fast_mode={fast}, got {status}"


# ═════════════════════════════════════════════════════════════════════════════
# Fix 4 — StateStore.resume() scenario-mismatch guard
# ═════════════════════════════════════════════════════════════════════════════

class TestResumeScenarioGuard:
    """resume() raises ValueError when scenario in prior run differs from new request."""

    def _write_prior(self, tmp_path: Path, run_id: str, scenario: str) -> None:
        mdir = tmp_path / "manifests"
        mdir.mkdir(parents=True, exist_ok=True)
        (mdir / f"{run_id}.json").write_text(json.dumps({
            "run_id": run_id,
            "timestamp": "2026-01-01T00:00:00+00:00",
            "request": {
                "countries": ["eth"], "variables": ["tas"],
                "scenario": scenario, "period": [2010, 2025],
            },
            "environment": {"python_version": "3.11"},
            "stages": [], "summary": {},
        }))

    def _patch_paths(self, tmp_path):
        def mpath(run_id):
            p = tmp_path / "manifests" / f"{run_id}.json"
            (tmp_path / "manifests").mkdir(parents=True, exist_ok=True)
            return p
        def lpath(run_id):
            p = tmp_path / "logs" / f"{run_id}.log"
            (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
            return p
        return (
            patch("agent.state_store.manifest_path", side_effect=mpath),
            patch("agent.state_store.log_path",      side_effect=lpath),
        )

    def test_raises_on_historical_to_ssp245(self, tmp_path):
        from agent.state_store import StateStore
        self._write_prior(tmp_path, "run_prior", "historical")
        mp, lp = self._patch_paths(tmp_path)
        with mp, lp:
            with pytest.raises(ValueError, match="scenario mismatch"):
                StateStore.resume("run_prior", "run_new", {
                    "countries": ["eth"], "variables": ["tas"],
                    "scenario": "ssp245", "period": [2040, 2070],
                })

    def test_raises_on_ssp245_to_historical(self, tmp_path):
        from agent.state_store import StateStore
        self._write_prior(tmp_path, "run_prior", "ssp245")
        mp, lp = self._patch_paths(tmp_path)
        with mp, lp:
            with pytest.raises(ValueError, match="scenario mismatch"):
                StateStore.resume("run_prior", "run_new", {
                    "countries": ["eth"], "variables": ["tas"],
                    "scenario": "historical", "period": [2010, 2025],
                })

    def test_same_scenario_does_not_raise(self, tmp_path):
        from agent.state_store import StateStore
        self._write_prior(tmp_path, "run_prior", "historical")
        mp, lp = self._patch_paths(tmp_path)
        with mp, lp:
            store = StateStore.resume("run_prior", "run_new", {
                "countries": ["eth"], "variables": ["tas"],
                "scenario": "historical", "period": [2010, 2025],
            })
        assert store.run_id == "run_new"

    def test_missing_prior_scenario_does_not_raise(self, tmp_path):
        """If prior manifest has no scenario field, resume proceeds without error."""
        from agent.state_store import StateStore
        mdir = tmp_path / "manifests"
        mdir.mkdir(parents=True, exist_ok=True)
        (mdir / "run_prior.json").write_text(json.dumps({
            "run_id": "run_prior", "timestamp": "2026-01-01T00:00:00+00:00",
            "request": {}, "environment": {}, "stages": [], "summary": {},
        }))
        mp, lp = self._patch_paths(tmp_path)
        with mp, lp:
            store = StateStore.resume("run_prior", "run_new", {
                "countries": ["eth"], "variables": ["tas"],
                "scenario": "historical", "period": [2010, 2025],
            })
        assert store.run_id == "run_new"


# ═════════════════════════════════════════════════════════════════════════════
# Fix 5 — output_resolver uses _HIST_LEGACY_PERIOD constant
# ═════════════════════════════════════════════════════════════════════════════

class TestOutputResolverLegacyPeriod:
    """output_resolver uses _HIST_LEGACY_PERIOD (not _HIST_HARDCODED_PERIOD)."""

    def test_legacy_period_constant_exists(self):
        from agent import output_resolver
        assert hasattr(output_resolver, "_HIST_LEGACY_PERIOD"), \
            "_HIST_LEGACY_PERIOD constant missing from output_resolver"

    def test_hardcoded_period_constant_removed(self):
        from agent import output_resolver
        assert not hasattr(output_resolver, "_HIST_HARDCODED_PERIOD"), \
            "_HIST_HARDCODED_PERIOD should be renamed to _HIST_LEGACY_PERIOD"

    def test_legacy_path_set_for_non_default_period(self):
        from agent.output_resolver import historical_outputs
        outputs = historical_outputs(["eth"], ["tas"], (1985, 2010))
        assert all(o.legacy_path is not None for o in outputs)

    def test_legacy_path_none_for_default_period(self):
        from agent.output_resolver import historical_outputs, _HIST_LEGACY_PERIOD
        outputs = historical_outputs(["eth"], ["tas"], _HIST_LEGACY_PERIOD)
        assert all(o.legacy_path is None for o in outputs)

    def test_primary_path_uses_requested_period(self):
        from agent.output_resolver import historical_outputs
        outputs = historical_outputs(["eth"], ["tas"], (1985, 2010))
        assert all("1985_2010" in str(o.path) for o in outputs)


# ═════════════════════════════════════════════════════════════════════════════
# Fix 6 — _classify_subprocess_error actionable messages
# ═════════════════════════════════════════════════════════════════════════════

class TestClassifySubprocessError:
    """_classify_subprocess_error returns actionable hints for known error patterns."""

    def _classify(self, stderr: str, attempts: int = 1) -> str:
        from agent.orchestrator import _classify_subprocess_error
        return _classify_subprocess_error("test_script.py", stderr, attempts)

    def test_missing_file_hint(self):
        msg = self._classify("FileNotFoundError: [Errno 2] No such file or directory: 'data.nc'")
        assert "Missing input file" in msg

    def test_no_such_file_lowercase(self):
        msg = self._classify("no such file or directory")
        assert "Missing input file" in msg

    def test_permission_denied_hint(self):
        msg = self._classify("PermissionError: [Errno 13] Permission denied: '/data/out.nc'")
        assert "Permission error" in msg

    def test_network_timeout_hint(self):
        msg = self._classify("requests.exceptions.ConnectionError: connection timeout")
        assert "Network" in msg

    def test_ssl_error_hint(self):
        msg = self._classify("ssl.SSLError: certificate verify failed")
        assert "Network" in msg

    def test_out_of_memory_hint(self):
        msg = self._classify("MemoryError: unable to allocate array")
        assert "memory" in msg.lower()

    def test_grid_mismatch_hint(self):
        msg = self._classify("grid shape mismatch: expected (720,1440) got (360,720)")
        assert "Grid mismatch" in msg

    def test_unit_mismatch_hint(self):
        msg = self._classify("units mismatch: expected 'K' found 'degC'")
        assert "Unit mismatch" in msg

    def test_unknown_error_includes_script_name(self):
        msg = self._classify("something completely unexpected happened")
        assert "test_script.py" in msg

    def test_stderr_tail_always_included(self):
        stderr = "Error: some detailed message"
        msg = self._classify(stderr)
        assert "some detailed message" in msg


# ═════════════════════════════════════════════════════════════════════════════
# Fix 7 — _validate_config warns on missing sections
# ═════════════════════════════════════════════════════════════════════════════

class TestValidateConfig:
    """_validate_config() logs warnings for missing agent_config.yaml sections."""

    _COMPLETE_CFG = {
        "paths": {
            "data_raw": "data/raw", "data_intermediate": "data/intermediate",
            "data_final": "data/final", "data_diagnostics": "data/diagnostics",
            "runs_manifests": "runs/manifests", "runs_logs": "runs/logs",
            "scripts": "scripts", "boundaries": "boundaries",
        },
        "countries": [], "reference_grid": {}, "compression": {},
        "retry": {}, "validation": {}, "cleanup": {},
    }

    def test_complete_config_no_warnings(self, caplog):
        import logging
        from agent.artifact_manager import _validate_config
        with caplog.at_level(logging.WARNING, logger="agent.artifact_manager"):
            _validate_config(self._COMPLETE_CFG)
        assert not any("missing" in r.message.lower() for r in caplog.records)

    def test_missing_section_logs_warning(self, caplog):
        import logging
        from agent.artifact_manager import _validate_config
        cfg = {k: v for k, v in self._COMPLETE_CFG.items() if k != "retry"}
        with caplog.at_level(logging.WARNING, logger="agent.artifact_manager"):
            _validate_config(cfg)
        assert any("retry" in r.message for r in caplog.records)

    def test_missing_path_key_logs_warning(self, caplog):
        import logging
        from agent.artifact_manager import _validate_config
        cfg = {**self._COMPLETE_CFG}
        cfg["paths"] = {k: v for k, v in cfg["paths"].items() if k != "scripts"}
        with caplog.at_level(logging.WARNING, logger="agent.artifact_manager"):
            _validate_config(cfg)
        assert any("scripts" in r.message for r in caplog.records)

    def test_empty_config_warns_all_sections(self, caplog):
        import logging
        from agent.artifact_manager import _validate_config
        with caplog.at_level(logging.WARNING, logger="agent.artifact_manager"):
            _validate_config({})
        assert caplog.records


# ═════════════════════════════════════════════════════════════════════════════
# Fix 8 — codes/ symlink verification
# ═════════════════════════════════════════════════════════════════════════════

class TestCodesSymlinkVerification:
    """_ensure_codes_alias() raises RuntimeError when symlink creation fails."""

    def test_raises_runtime_error_when_codes_not_created(self, tmp_path, monkeypatch):
        import run_agent as ra
        # Point _HERE to tmp_path so the alias is created there
        monkeypatch.setattr(ra, "_HERE", tmp_path)
        (tmp_path / "scripts").mkdir()

        # Make both creation methods fail silently (no actual symlink written)
        with patch("os.symlink", side_effect=OSError("not permitted")), \
             patch("subprocess.run", return_value=MagicMock(returncode=0)):
            # codes/ will not exist after the failed attempts
            with pytest.raises(RuntimeError, match="codes/"):
                ra._ensure_codes_alias()

    def test_no_error_when_codes_already_exists(self, tmp_path, monkeypatch):
        import run_agent as ra
        monkeypatch.setattr(ra, "_HERE", tmp_path)
        (tmp_path / "codes").mkdir()   # pre-exists
        # Should return without error and without calling os.symlink
        with patch("os.symlink") as mock_sym:
            ra._ensure_codes_alias()
        mock_sym.assert_not_called()


# ═════════════════════════════════════════════════════════════════════════════
# Fix 9 — preflight uses connector availability checkers
# ═════════════════════════════════════════════════════════════════════════════

class TestPreflightConnectorCheckers:
    """check_source_dirs() delegates to connector is_source_available() functions."""

    def test_agera5_available_returns_ok(self):
        from agent.preflight import check_source_dirs
        with patch("agent.connectors.agera5.is_source_available", return_value=True):
            result = check_source_dirs({
                "countries": ["eth"], "variables": ["tas"],
                "scenario": "historical", "period": [2010, 2025],
            })
        assert result["eth/tas/agera5"] == "OK"

    def test_agera5_missing_includes_auto_download_note(self, tmp_path):
        from agent.preflight import check_source_dirs
        with patch("agent.connectors.agera5.is_source_available", return_value=False), \
             patch("agent.connectors.agera5.source_dir", return_value=tmp_path / "agera5"):
            result = check_source_dirs({
                "countries": ["eth"], "variables": ["tas"],
                "scenario": "historical", "period": [2010, 2025],
            })
        assert "auto-download available" in result["eth/tas/agera5"]

    def test_chirps_available_returns_ok(self):
        from agent.preflight import check_source_dirs
        with patch("agent.connectors.chirps.is_source_available", return_value=True):
            result = check_source_dirs({
                "countries": ["eth"], "variables": ["pr"],
                "scenario": "historical", "period": [2010, 2025],
            })
        assert result["eth/pr/chirps"] == "OK"

    def test_chirps_missing_includes_auto_download_note(self, tmp_path):
        from agent.preflight import check_source_dirs
        with patch("agent.connectors.chirps.is_source_available", return_value=False), \
             patch("agent.connectors.chirps.source_dir", return_value=tmp_path / "chirps"):
            result = check_source_dirs({
                "countries": ["eth"], "variables": ["pr"],
                "scenario": "historical", "period": [2010, 2025],
            })
        assert "auto-download available" in result["eth/pr/chirps"]


# ═════════════════════════════════════════════════════════════════════════════
# Fix 10 — schema load failure logs a warning
# ═════════════════════════════════════════════════════════════════════════════

class TestSchemaLoadWarning:
    """state_store warns (not silently disables) when schema cannot be loaded."""

    def test_warning_text_present_in_source(self):
        import inspect
        from agent import state_store
        src = inspect.getsource(state_store)
        assert "could not be loaded" in src, \
            "Warning message for schema load failure not found in state_store.py"

    def test_has_schema_flag_exists(self):
        from agent import state_store
        assert hasattr(state_store, "_HAS_SCHEMA")

    def test_manifest_schema_dict_exists(self):
        from agent import state_store
        assert hasattr(state_store, "_MANIFEST_SCHEMA")


# ═════════════════════════════════════════════════════════════════════════════
# Fix 11 — source dir severity: historical → warning, ISIMIP → error
# ═════════════════════════════════════════════════════════════════════════════

class TestSourceDirSeverity:
    """Missing historical sources become preflight warnings; ISIMIP missing → error."""

    _INFRA_PATCHES = [
        ("agent.preflight.check_dependencies",   {}),
        ("agent.preflight.check_scripts",        {
            "run_historical_workflow.py": "OK",
            "run_projection_workflow.py": "OK",
            "run_future_vpd_workflow.py": "OK",
        }),
        ("agent.preflight.check_boundaries",     {"eth": "OK"}),
        ("agent.preflight.check_cds_credentials", "OK"),
        ("agent.preflight.check_reference_grid",  "OK"),
    ]

    def _run_preflight_with_infra(self, extra_patches: list, request: dict):
        from agent.preflight import run_preflight
        from contextlib import ExitStack
        with ExitStack() as stack:
            for target, retval in self._INFRA_PATCHES:
                stack.enter_context(patch(target, return_value=retval))
            for ctx in extra_patches:
                stack.enter_context(ctx)
            return run_preflight(request)

    def test_historical_missing_chirps_is_warning_not_error(self, tmp_path):
        report = self._run_preflight_with_infra(
            extra_patches=[
                patch("agent.connectors.chirps.is_source_available", return_value=False),
                patch("agent.connectors.chirps.source_dir", return_value=tmp_path / "ch"),
            ],
            request={"countries": ["eth"], "variables": ["pr"],
                     "scenario": "historical", "period": [2010, 2025]},
        )
        assert not report.has_errors
        assert any("auto-download" in w for w in report.warnings)

    def test_isimip_missing_source_is_error(self, tmp_path):
        report = self._run_preflight_with_infra(
            extra_patches=[patch("agent.preflight.ROOT", tmp_path)],
            request={"countries": ["eth"], "variables": ["tas"],
                     "scenario": "ssp245", "period": [2040, 2070]},
        )
        assert report.has_errors
        assert any("isimip" in e.lower() or "ssp245" in e.lower() for e in report.errors)

    def test_historical_missing_agera5_is_warning_not_error(self, tmp_path):
        report = self._run_preflight_with_infra(
            extra_patches=[
                patch("agent.connectors.agera5.is_source_available", return_value=False),
                patch("agent.connectors.agera5.source_dir", return_value=tmp_path / "ag"),
            ],
            request={"countries": ["eth"], "variables": ["tas"],
                     "scenario": "historical", "period": [2010, 2025]},
        )
        assert not report.has_errors
        assert any("auto-download" in w for w in report.warnings)

    def test_historical_present_source_no_auto_download_warning(self):
        report = self._run_preflight_with_infra(
            extra_patches=[
                patch("agent.connectors.chirps.is_source_available", return_value=True),
            ],
            request={"countries": ["eth"], "variables": ["pr"],
                     "scenario": "historical", "period": [2010, 2025]},
        )
        assert not any("auto-download" in w for w in report.warnings)
