"""
Tests for scripts/validate_run.py — report rendering and --checks flag.

No real run manifests are needed; tests build minimal in-memory dicts and
call the rendering functions directly.
"""

from __future__ import annotations
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pytest

# Add scripts/ to path so we can import validate_run as a module
import importlib.util, types

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate_run.py"
_spec = importlib.util.spec_from_file_location("validate_run", _SCRIPT)
vr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vr)


# ── helpers ───────────────────────────────────────────────────────────────────

def _manifest(stages: list[dict] | None = None,
              summary: dict | None = None) -> dict:
    return {
        "run_id":    "run_20260506_143000",
        "timestamp": "2026-05-06T14:30:00+00:00",
        "request":   {"countries": ["eth"], "variables": ["rh"],
                      "scenario": "historical", "period": [2010, 2025]},
        "environment": {"python_version": "3.11.0", "script_commit": "abc1234"},
        "stages":    stages or [],
        "summary":   summary or {"total_slices": 0, "succeeded": 0, "failed": 0,
                                 "warnings": 0, "skipped": 0, "duration_seconds": 1.0,
                                 "failed_slices": [], "output_files": [],
                                 "diagnostic_files": []},
    }


def _stage(status: str = "SUCCESS",
           validation: dict | None = None) -> dict:
    return {
        "stage": "merge", "country": "eth", "variable": "rh",
        "scenario": "historical", "command": "python scripts/merge.py",
        "status": status, "attempt": 1,
        "validation": validation or {
            "existence": "OK", "variable_present": "OK",
            "non_nan_coverage": "OK", "time_coverage": "OK",
            "daily_axis": "OK", "units": "SKIP",
            "grid_match": "SKIP", "spatial_bounds": "SKIP",
            "anomaly": "SKIP", "distribution": "OK",
        },
    }


def _capture(fn, *args, **kwargs) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        fn(*args, **kwargs)
    return buf.getvalue()


# ── _print_report basic ───────────────────────────────────────────────────────

class TestPrintReport:
    def test_returns_zero_when_no_failures(self):
        m = _manifest(summary={"total_slices": 1, "succeeded": 1, "failed": 0,
                                "warnings": 0, "skipped": 0, "duration_seconds": 2.0,
                                "failed_slices": [], "output_files": [],
                                "diagnostic_files": []})
        code = vr._print_report(m, use_color=False)
        assert code == 0

    def test_returns_one_when_failures_exist(self):
        m = _manifest(summary={"total_slices": 1, "succeeded": 0, "failed": 1,
                                "warnings": 0, "skipped": 0, "duration_seconds": 2.0,
                                "failed_slices": [], "output_files": [],
                                "diagnostic_files": []})
        code = vr._print_report(m, use_color=False)
        assert code == 1

    def test_run_id_appears_in_output(self):
        out = _capture(vr._print_report, _manifest(), use_color=False)
        assert "run_20260506_143000" in out

    def test_countries_appear_in_output(self):
        out = _capture(vr._print_report, _manifest(), use_color=False)
        assert "eth" in out

    def test_resumed_from_shown_when_present(self):
        m = _manifest()
        m["resumed_from"] = "run_20260505_100000"
        out = _capture(vr._print_report, m, use_color=False)
        assert "run_20260505_100000" in out

    def test_failed_slices_printed(self):
        summ = {"total_slices": 1, "succeeded": 0, "failed": 1,
                "warnings": 0, "skipped": 0, "duration_seconds": 1.0,
                "failed_slices": [{"country": "ken", "variable": "tas",
                                   "scenario": "ssp245", "stage": "regrid",
                                   "reason": "grid mismatch"}],
                "output_files": [], "diagnostic_files": []}
        out = _capture(vr._print_report, _manifest(summary=summ), use_color=False)
        assert "ken" in out
        assert "grid mismatch" in out

    def test_output_files_listed(self, tmp_path):
        f = tmp_path / "out.nc"
        f.write_bytes(b"x")
        summ = {"total_slices": 1, "succeeded": 1, "failed": 0,
                "warnings": 0, "skipped": 0, "duration_seconds": 1.0,
                "failed_slices": [], "output_files": [str(f)],
                "diagnostic_files": []}
        out = _capture(vr._print_report, _manifest(summary=summ), use_color=False)
        assert "out.nc" in out
        assert "[x]" in out  # file exists marker


# ── --checks flag (_print_checks_table) ──────────────────────────────────────

class TestChecksTable:
    def test_check_keys_appear_as_columns(self):
        m = _manifest(stages=[_stage()])
        out = _capture(vr._print_checks_table, m, use_color=False)
        assert "existence" in out or "existenc" in out  # may be truncated to 8

    def test_ok_result_appears_in_table(self):
        m = _manifest(stages=[_stage()])
        out = _capture(vr._print_checks_table, m, use_color=False)
        assert "OK" in out

    def test_fail_result_appears_in_table(self):
        m = _manifest(stages=[_stage(validation={"existence": "FAIL"})])
        out = _capture(vr._print_checks_table, m, use_color=False)
        assert "FAIL" in out

    def test_no_stages_handled_gracefully(self):
        m = _manifest(stages=[])
        out = _capture(vr._print_checks_table, m, use_color=False)
        assert "No" in out  # "No stages" or "No validation data"

    def test_show_checks_true_triggers_table(self):
        m = _manifest(stages=[_stage()])
        out = _capture(vr._print_report, m, show_checks=True, use_color=False)
        assert "check" in out.lower()


# ── _print_qc_summary ─────────────────────────────────────────────────────────

class TestQcSummary:
    def test_tallies_ok_count(self):
        stages = [
            _stage(validation={"existence": "OK", "non_nan_coverage": "OK"}),
            _stage(validation={"existence": "OK", "non_nan_coverage": "FAIL"}),
        ]
        m = _manifest(stages=stages)
        out = _capture(vr._print_qc_summary, m, use_color=False)
        assert "existence" in out
        assert "2" in out  # 2 OK for existence

    def test_tallies_fail_count(self):
        stages = [_stage(validation={"non_nan_coverage": "FAIL"})]
        m = _manifest(stages=stages)
        out = _capture(vr._print_qc_summary, m, use_color=False)
        assert "1" in out

    def test_no_stages_no_crash(self):
        m = _manifest(stages=[])
        _capture(vr._print_qc_summary, m, use_color=False)  # must not raise

    def test_all_checks_summarised(self):
        m = _manifest(stages=[_stage()])
        out = _capture(vr._print_qc_summary, m, use_color=False)
        # At least some check names should be in the output
        assert any(k in out for k in ("existence", "non_nan", "time_cov"))


# ── _list_runs ────────────────────────────────────────────────────────────────

class TestListRuns:
    def test_no_manifests_prints_message(self, tmp_path):
        with patch.object(vr, "_MANIFESTS", tmp_path):
            out = _capture(vr._list_runs)
        assert "No run manifests" in out

    def test_manifest_appears_in_listing(self, tmp_path):
        m = _manifest()
        p = tmp_path / "run_20260506_143000.json"
        p.write_text(json.dumps(m))
        with patch.object(vr, "_MANIFESTS", tmp_path):
            out = _capture(vr._list_runs)
        assert "run_20260506_143000" in out


# ── _flatten_validation ────────────────────────────────────────────────────────

class TestFlattenValidation:
    """_flatten_validation handles both flat (run_stage) and nested (run_tool) formats."""

    def test_flat_dict_returned_unchanged(self):
        val = {"existence": "OK", "units": "SKIP"}
        assert vr._flatten_validation(val) == val

    def test_nested_dict_merged_to_flat(self):
        val = {"file_a.nc": {"existence": "OK", "units": "SKIP"}}
        result = vr._flatten_validation(val)
        assert result["existence"] == "OK"
        assert result["units"] == "SKIP"

    def test_multi_file_nested_merged(self):
        val = {
            "a.nc": {"existence": "OK", "time_coverage": "OK"},
            "b.nc": {"existence": "OK", "time_coverage": "FAIL"},
        }
        result = vr._flatten_validation(val)
        # Last file wins on conflict
        assert result["existence"] == "OK"
        assert result["time_coverage"] == "FAIL"

    def test_empty_dict_returns_empty(self):
        assert vr._flatten_validation({}) == {}

    def test_checks_table_works_with_nested_validation(self):
        m = _manifest(stages=[{
            "stage": "merge", "country": "eth", "variable": "rh",
            "scenario": "historical", "status": "WARNING", "attempt": 1,
            "validation": {
                "ethiopia_rh_2010_2025_025deg_clipped.nc": {
                    "existence": "OK", "non_nan_coverage": "FAIL",
                    "time_coverage": "OK", "distribution": "OK",
                }
            },
        }])
        out = _capture(vr._print_checks_table, m, use_color=False)
        assert "OK" in out
        assert "FAIL" in out
        assert "existence" in out or "existenc" in out
