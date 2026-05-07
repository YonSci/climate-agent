"""
Tests for agent/state_store.py — manifest lifecycle, idempotency, fingerprinting,
resume, and schema validation.

Uses a tmp_path fixture so every test writes to a fresh directory without
touching the real runs/ tree.
"""

import json
import logging
import threading
import time
import pytest
from pathlib import Path
from unittest.mock import patch

from agent.state_store import StateStore, _sha256


# ── fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path):
    """StateStore backed by tmp_path instead of the real runs/ directory."""
    run_id = "run_test_001"
    request = {
        "countries": ["eth"],
        "variables": ["pr"],
        "scenario": "historical",
        "period": [2010, 2025],
    }
    with patch("agent.state_store.manifest_path",
               return_value=tmp_path / "manifests" / f"{run_id}.json"), \
         patch("agent.state_store.log_path",
               return_value=tmp_path / "logs" / f"{run_id}.log"):
        s = StateStore(run_id, request)
    return s


@pytest.fixture
def manifest_file(store, tmp_path):
    """Path to the manifest JSON that store writes to."""
    return tmp_path / "manifests" / "run_test_001.json"


# ── initialisation ────────────────────────────────────────────────────────────

class TestInit:
    def test_manifest_written_on_init(self, manifest_file):
        assert manifest_file.exists()

    def test_manifest_has_run_id(self, store, manifest_file):
        data = json.loads(manifest_file.read_text())
        assert data["run_id"] == "run_test_001"

    def test_manifest_has_request(self, manifest_file):
        data = json.loads(manifest_file.read_text())
        assert data["request"]["scenario"] == "historical"

    def test_manifest_stages_empty_on_init(self, manifest_file):
        data = json.loads(manifest_file.read_text())
        assert data["stages"] == []

    def test_manifest_has_environment(self, manifest_file):
        data = json.loads(manifest_file.read_text())
        assert "python_version" in data["environment"]

    def test_manifest_has_timestamp(self, manifest_file):
        data = json.loads(manifest_file.read_text())
        assert "timestamp" in data

    def test_script_commit_is_not_unknown(self, manifest_file):
        # Either git hash or scripts: content fingerprint — never "unknown"
        data = json.loads(manifest_file.read_text())
        commit = data["environment"].get("script_commit", "unknown")
        assert commit != "unknown"

    def test_script_commit_format(self, manifest_file):
        data = json.loads(manifest_file.read_text())
        commit = data["environment"].get("script_commit", "")
        # Valid forms: bare hex (git), "scripts:<8hex>" (content fingerprint)
        assert len(commit) > 4


# ── record_stage ──────────────────────────────────────────────────────────────

class TestRecordStage:
    def test_stage_appended_to_manifest(self, store, manifest_file):
        store.record_stage(
            stage="merge", country="eth", variable="pr",
            scenario="historical", command="python scripts/run.py",
            status="SUCCESS",
        )
        data = json.loads(manifest_file.read_text())
        assert len(data["stages"]) == 1

    def test_stage_fields_present(self, store, manifest_file):
        store.record_stage(
            stage="merge", country="eth", variable="pr",
            scenario="historical", command="python scripts/run.py",
            status="SUCCESS", exit_code=0, attempt=1,
        )
        s = json.loads(manifest_file.read_text())["stages"][0]
        assert s["stage"] == "merge"
        assert s["country"] == "eth"
        assert s["variable"] == "pr"
        assert s["status"] == "SUCCESS"
        assert s["exit_code"] == 0

    def test_multiple_stages_accumulate(self, store, manifest_file):
        for var in ["pr", "rh", "tas"]:
            store.record_stage(
                stage="merge", country="eth", variable=var,
                command="cmd", status="SUCCESS",
            )
        data = json.loads(manifest_file.read_text())
        assert len(data["stages"]) == 3

    def test_failed_stage_recorded(self, store, manifest_file):
        store.record_stage(
            stage="regrid", country="ken", variable="tas",
            command="cmd", status="FAILED",
            error_message="exit code 1",
        )
        s = json.loads(manifest_file.read_text())["stages"][0]
        assert s["status"] == "FAILED"
        assert "exit code 1" in s["error_message"]

    def test_validation_dict_stored(self, store, manifest_file):
        store.record_stage(
            stage="merge", country="eth", variable="pr",
            command="cmd", status="SUCCESS",
            validation={"existence": "OK", "units": "FAIL"},
        )
        s = json.loads(manifest_file.read_text())["stages"][0]
        assert s["validation"]["units"] == "FAIL"

    def test_stdout_stderr_stored(self, store, manifest_file):
        store.record_stage(
            stage="merge", country="eth", variable="pr",
            command="cmd", status="SUCCESS",
            stdout_tail="done", stderr_tail="warning: something",
        )
        s = json.loads(manifest_file.read_text())["stages"][0]
        assert s["stdout_tail"] == "done"
        assert "warning" in s["stderr_tail"]

    def test_output_hash_computed_when_file_exists(self, store, manifest_file, tmp_path):
        out = tmp_path / "output.nc"
        out.write_bytes(b"fake netcdf content")
        store.record_stage(
            stage="merge", country="eth", variable="pr",
            command="cmd", status="SUCCESS",
            output_file=str(out),
        )
        s = json.loads(manifest_file.read_text())["stages"][0]
        assert s["output_hash"].startswith("sha256:")

    def test_output_hash_absent_when_file_missing(self, store, manifest_file):
        store.record_stage(
            stage="merge", country="eth", variable="pr",
            command="cmd", status="SUCCESS",
            output_file="/nonexistent/file.nc",
        )
        s = json.loads(manifest_file.read_text())["stages"][0]
        assert "output_hash" not in s

    def test_input_hashes_computed_for_existing_files(self, store, manifest_file, tmp_path):
        f1 = tmp_path / "input1.nc"
        f1.write_bytes(b"data1")
        store.record_stage(
            stage="merge", country="eth", variable="pr",
            command="cmd", status="SUCCESS",
            input_files=[str(f1)],
        )
        s = json.loads(manifest_file.read_text())["stages"][0]
        assert str(f1) in s["input_hashes"]
        assert s["input_hashes"][str(f1)].startswith("sha256:")

    def test_missing_input_files_skipped_in_hashes(self, store, manifest_file):
        store.record_stage(
            stage="merge", country="eth", variable="pr",
            command="cmd", status="SUCCESS",
            input_files=["/nonexistent/input.nc"],
        )
        s = json.loads(manifest_file.read_text())["stages"][0]
        assert s["input_hashes"] == {}


# ── is_complete ───────────────────────────────────────────────────────────────

class TestIsComplete:
    def test_returns_false_before_any_stage(self, store):
        assert not store.is_complete("merge", "eth", "pr", "historical")

    def test_returns_true_after_success(self, store):
        store.record_stage(
            stage="merge", country="eth", variable="pr",
            scenario="historical", command="cmd", status="SUCCESS",
        )
        assert store.is_complete("merge", "eth", "pr", "historical")

    def test_returns_false_after_failure(self, store):
        store.record_stage(
            stage="merge", country="eth", variable="pr",
            scenario="historical", command="cmd", status="FAILED",
        )
        assert not store.is_complete("merge", "eth", "pr", "historical")

    def test_returns_false_for_different_country(self, store):
        store.record_stage(
            stage="merge", country="eth", variable="pr",
            scenario="historical", command="cmd", status="SUCCESS",
        )
        assert not store.is_complete("merge", "ken", "pr", "historical")

    def test_returns_false_for_different_variable(self, store):
        store.record_stage(
            stage="merge", country="eth", variable="pr",
            scenario="historical", command="cmd", status="SUCCESS",
        )
        assert not store.is_complete("merge", "eth", "rh", "historical")

    def test_returns_false_for_different_scenario(self, store):
        store.record_stage(
            stage="merge", country="eth", variable="pr",
            scenario="historical", command="cmd", status="SUCCESS",
        )
        assert not store.is_complete("merge", "eth", "pr", "ssp245")

    def test_returns_false_for_different_stage(self, store):
        store.record_stage(
            stage="merge", country="eth", variable="pr",
            scenario="historical", command="cmd", status="SUCCESS",
        )
        assert not store.is_complete("regrid", "eth", "pr", "historical")

    def test_warning_status_is_not_complete(self, store):
        store.record_stage(
            stage="merge", country="eth", variable="pr",
            scenario="historical", command="cmd", status="WARNING",
        )
        assert not store.is_complete("merge", "eth", "pr", "historical")


# ── close_run ─────────────────────────────────────────────────────────────────

class TestCloseRun:
    def test_summary_written_to_manifest(self, store, manifest_file):
        store.record_stage(stage="merge", country="eth", variable="pr",
                           command="cmd", status="SUCCESS")
        store.close_run(output_files=[], diagnostic_files=[])
        data = json.loads(manifest_file.read_text())
        assert "total_slices" in data["summary"]

    def test_succeeded_count_correct(self, store, manifest_file):
        store.record_stage(stage="merge", country="eth", variable="pr",
                           command="cmd", status="SUCCESS")
        store.record_stage(stage="merge", country="eth", variable="rh",
                           command="cmd", status="FAILED")
        store.close_run(output_files=[], diagnostic_files=[])
        data = json.loads(manifest_file.read_text())
        assert data["summary"]["succeeded"] == 1
        assert data["summary"]["failed"] == 1

    def test_failed_slices_listed(self, store, manifest_file):
        store.record_stage(stage="merge", country="ken", variable="tas",
                           command="cmd", status="FAILED",
                           error_message="timeout")
        store.close_run(output_files=[], diagnostic_files=[])
        data = json.loads(manifest_file.read_text())
        slices = data["summary"]["failed_slices"]
        assert len(slices) == 1
        assert slices[0]["country"] == "ken"

    def test_duration_seconds_positive(self, store, manifest_file):
        store.close_run(output_files=[], diagnostic_files=[])
        data = json.loads(manifest_file.read_text())
        assert data["summary"]["duration_seconds"] >= 0

    def test_output_files_stored_in_summary(self, store, manifest_file):
        store.close_run(
            output_files=["data/final/eth/pr.nc"],
            diagnostic_files=["data/diagnostics/qa.png"],
        )
        data = json.loads(manifest_file.read_text())
        assert "data/final/eth/pr.nc" in data["summary"]["output_files"]

    def test_skipped_count_correct(self, store, manifest_file):
        store.record_stage(stage="merge", country="eth", variable="pr",
                           command="cmd", status="SKIPPED")
        store.close_run(output_files=[], diagnostic_files=[])
        data = json.loads(manifest_file.read_text())
        assert data["summary"]["skipped"] == 1


# ── _sha256 helper ────────────────────────────────────────────────────────────

class TestSha256:
    def test_returns_sha256_prefixed_string(self, tmp_path):
        f = tmp_path / "file.bin"
        f.write_bytes(b"hello world")
        result = _sha256(f)
        assert result.startswith("sha256:")
        assert len(result) == 7 + 64  # "sha256:" + 64 hex chars

    def test_different_content_different_hash(self, tmp_path):
        f1 = tmp_path / "a.bin"
        f2 = tmp_path / "b.bin"
        f1.write_bytes(b"content A")
        f2.write_bytes(b"content B")
        assert _sha256(f1) != _sha256(f2)

    def test_same_content_same_hash(self, tmp_path):
        f1 = tmp_path / "x.bin"
        f2 = tmp_path / "y.bin"
        f1.write_bytes(b"identical")
        f2.write_bytes(b"identical")
        assert _sha256(f1) == _sha256(f2)


# ── resume ────────────────────────────────────────────────────────────────────

def _make_prior_manifest(tmp_path: Path, run_id: str, stages: list[dict]) -> Path:
    """Write a minimal prior-run manifest JSON and return its path."""
    data = {
        "run_id": run_id,
        "timestamp": "2026-05-06T10:00:00+00:00",
        "request": {"countries": ["eth"], "variables": ["pr"],
                    "scenario": "historical", "period": [2010, 2025]},
        "environment": {},
        "stages": stages,
        "summary": {},
    }
    p = tmp_path / "manifests" / f"{run_id}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data))
    return p


class TestResume:
    """StateStore.resume() loads prior SUCCESS stages into a new run."""

    _REQUEST = {"countries": ["eth"], "variables": ["pr"],
                "scenario": "historical", "period": [2010, 2025]}

    def _patch(self, tmp_path: Path):
        """Return a context-manager pair that routes manifest_path / log_path to tmp_path."""
        def _mp(rid):
            return tmp_path / "manifests" / f"{rid}.json"
        def _lp(rid):
            return tmp_path / "logs" / f"{rid}.log"
        return (
            patch("agent.state_store.manifest_path", side_effect=_mp),
            patch("agent.state_store.log_path",      side_effect=_lp),
        )

    def _resume(self, tmp_path: Path, prior_id: str = "run_prior_001",
                new_id: str = "run_new_001") -> StateStore:
        mp, lp = self._patch(tmp_path)
        with mp, lp:
            return StateStore.resume(prior_id, new_id, self._REQUEST)

    def test_resume_raises_for_missing_prior(self, tmp_path):
        mp, lp = self._patch(tmp_path)
        with mp, lp, pytest.raises(FileNotFoundError, match="Prior run manifest not found"):
            StateStore.resume("run_missing", "run_new", self._REQUEST)

    def test_resumed_from_recorded_in_manifest(self, tmp_path):
        _make_prior_manifest(tmp_path, "run_prior_001", [
            {"stage": "merge", "country": "eth", "variable": "pr",
             "scenario": "historical", "status": "SUCCESS",
             "command": "cmd", "finished_at": "2026-05-06T10:01:00+00:00"},
        ])
        store = self._resume(tmp_path)
        assert store._manifest.get("resumed_from") == "run_prior_001"

    def test_only_success_stages_carried(self, tmp_path):
        _make_prior_manifest(tmp_path, "run_prior_001", [
            {"stage": "merge", "country": "eth", "variable": "pr",
             "scenario": "historical", "status": "SUCCESS",
             "command": "cmd", "finished_at": "2026-05-06T10:01:00+00:00"},
            {"stage": "regrid", "country": "eth", "variable": "pr",
             "scenario": "historical", "status": "FAILED",
             "command": "cmd", "finished_at": "2026-05-06T10:02:00+00:00"},
            {"stage": "clip", "country": "eth", "variable": "pr",
             "scenario": "historical", "status": "WARNING",
             "command": "cmd", "finished_at": "2026-05-06T10:03:00+00:00"},
        ])
        store = self._resume(tmp_path)
        carried = store._manifest["stages"]
        assert len(carried) == 1
        assert carried[0]["stage"] == "merge"

    def test_is_complete_true_for_resumed_success(self, tmp_path):
        _make_prior_manifest(tmp_path, "run_prior_001", [
            {"stage": "merge", "country": "eth", "variable": "pr",
             "scenario": "historical", "status": "SUCCESS",
             "command": "cmd", "finished_at": "2026-05-06T10:01:00+00:00"},
        ])
        store = self._resume(tmp_path)
        assert store.is_complete("merge", "eth", "pr", "historical") is True

    def test_is_complete_false_for_non_resumed_stage(self, tmp_path):
        _make_prior_manifest(tmp_path, "run_prior_001", [
            {"stage": "merge", "country": "eth", "variable": "pr",
             "scenario": "historical", "status": "SUCCESS",
             "command": "cmd", "finished_at": "2026-05-06T10:01:00+00:00"},
        ])
        store = self._resume(tmp_path)
        assert store.is_complete("regrid", "eth", "pr", "historical") is False

    def test_is_complete_false_for_failed_prior_stage(self, tmp_path):
        _make_prior_manifest(tmp_path, "run_prior_001", [
            {"stage": "merge", "country": "eth", "variable": "pr",
             "scenario": "historical", "status": "FAILED",
             "command": "cmd", "finished_at": "2026-05-06T10:01:00+00:00"},
        ])
        store = self._resume(tmp_path)
        assert store.is_complete("merge", "eth", "pr", "historical") is False

    def test_new_stages_recorded_after_resume(self, tmp_path):
        _make_prior_manifest(tmp_path, "run_prior_001", [
            {"stage": "merge", "country": "eth", "variable": "pr",
             "scenario": "historical", "status": "SUCCESS",
             "command": "cmd", "finished_at": "2026-05-06T10:01:00+00:00"},
        ])
        mp, lp = self._patch(tmp_path)
        with mp, lp:
            store = StateStore.resume("run_prior_001", "run_new_001", self._REQUEST)
            store.record_stage(
                stage="regrid", country="eth", variable="pr",
                scenario="historical", command="new cmd", status="SUCCESS",
            )
        assert len(store._manifest["stages"]) == 2
        assert store._manifest["stages"][1]["stage"] == "regrid"

    def test_empty_prior_stages_handled(self, tmp_path):
        _make_prior_manifest(tmp_path, "run_prior_001", [])
        store = self._resume(tmp_path)
        assert store._manifest["stages"] == []
        assert store._manifest.get("resumed_from") == "run_prior_001"

    def test_multiple_success_stages_all_carried(self, tmp_path):
        _make_prior_manifest(tmp_path, "run_prior_001", [
            {"stage": "merge", "country": "eth", "variable": "pr",
             "scenario": "historical", "status": "SUCCESS",
             "command": "cmd", "finished_at": "2026-05-06T10:01:00+00:00"},
            {"stage": "merge", "country": "eth", "variable": "tas",
             "scenario": "historical", "status": "SUCCESS",
             "command": "cmd", "finished_at": "2026-05-06T10:02:00+00:00"},
        ])
        store = self._resume(tmp_path)
        assert len(store._manifest["stages"]) == 2


# ── schema validation ─────────────────────────────────────────────────────────

class TestSchemaValidation:
    """_flush(validate=True) / close_run() triggers jsonschema checks."""

    def test_valid_manifest_logs_no_warning(self, tmp_path, caplog):
        run_id = "run_20260506_143000"
        request = {"countries": ["eth"], "variables": ["pr"],
                   "scenario": "historical", "period": [2010, 2025]}
        with patch("agent.state_store.manifest_path",
                   return_value=tmp_path / "manifests" / f"{run_id}.json"), \
             patch("agent.state_store.log_path",
                   return_value=tmp_path / "logs" / f"{run_id}.log"):
            s = StateStore(run_id, request)
            s.record_stage(
                stage="merge", country="eth", variable="pr",
                scenario="historical", command="cmd", status="SUCCESS",
                exit_code=0, attempt=1,
            )
            with caplog.at_level(logging.WARNING, logger="agent.state_store"):
                s.close_run(output_files=[], diagnostic_files=[])
        schema_warnings = [r for r in caplog.records
                           if "schema violation" in r.message.lower()]
        assert schema_warnings == []

    def test_schema_validation_runs_only_on_close(self, store, manifest_file):
        import agent.state_store as ss_module
        if not ss_module._HAS_SCHEMA:
            pytest.skip("jsonschema not installed")
        validate_calls = []
        original = store._validate_schema
        store._validate_schema = lambda: validate_calls.append(1) or original()
        store.record_stage(
            stage="merge", country="eth", variable="pr",
            command="cmd", status="SUCCESS",
        )
        assert validate_calls == []
        store.close_run(output_files=[], diagnostic_files=[])
        assert len(validate_calls) == 1

    def test_schema_skip_when_jsonschema_unavailable(self, store, manifest_file, caplog):
        import agent.state_store as ss_module
        original = ss_module._HAS_SCHEMA
        ss_module._HAS_SCHEMA = False
        try:
            with caplog.at_level(logging.WARNING, logger="agent.state_store"):
                store.close_run(output_files=[], diagnostic_files=[])
            schema_warnings = [r for r in caplog.records
                               if "schema" in r.message.lower()]
            assert schema_warnings == []
        finally:
            ss_module._HAS_SCHEMA = original


# ── close_run with qc_stats ───────────────────────────────────────────────────

class TestCloseRunQcStats:
    def test_qc_stats_embedded_in_summary(self, tmp_path):
        run_id = "run_20260506_120000"
        request = {"countries": ["eth"], "variables": ["pr"],
                   "scenario": "historical", "period": [2010, 2025]}
        with patch("agent.state_store.manifest_path",
                   return_value=tmp_path / "manifests" / f"{run_id}.json"), \
             patch("agent.state_store.log_path",
                   return_value=tmp_path / "logs" / f"{run_id}.log"):
            s = StateStore(run_id, request)
            qc = {"ethiopia_pr_2010_2025.nc": {"coverage": {"finite_ratio": 0.95}}}
            s.close_run(output_files=[], diagnostic_files=[], qc_stats=qc)
            data = json.loads(
                (tmp_path / "manifests" / f"{run_id}.json").read_text()
            )
        assert "qc_stats" in data["summary"]
        assert "ethiopia_pr_2010_2025.nc" in data["summary"]["qc_stats"]

    def test_qc_stats_absent_when_none(self, tmp_path):
        run_id = "run_20260506_130000"
        request = {"countries": ["eth"], "variables": ["pr"],
                   "scenario": "historical", "period": [2010, 2025]}
        with patch("agent.state_store.manifest_path",
                   return_value=tmp_path / "manifests" / f"{run_id}.json"), \
             patch("agent.state_store.log_path",
                   return_value=tmp_path / "logs" / f"{run_id}.log"):
            s = StateStore(run_id, request)
            s.close_run(output_files=[], diagnostic_files=[], qc_stats=None)
            data = json.loads(
                (tmp_path / "manifests" / f"{run_id}.json").read_text()
            )
        assert "qc_stats" not in data["summary"]


# ── thread safety ─────────────────────────────────────────────────────────────

class TestThreadSafety:
    """Concurrent record_stage() calls must not corrupt the manifest."""

    N = 24  # enough threads to make races likely if locking is wrong

    def _make_threadsafe_store(self, tmp_path: Path) -> StateStore:
        run_id = "run_20260506_150000"
        request = {"countries": ["eth"], "variables": ["pr"],
                   "scenario": "historical", "period": [2010, 2025]}
        with patch("agent.state_store.manifest_path",
                   return_value=tmp_path / "manifests" / f"{run_id}.json"), \
             patch("agent.state_store.log_path",
                   return_value=tmp_path / "logs" / f"{run_id}.log"):
            return StateStore(run_id, request)

    def test_concurrent_writes_produce_correct_stage_count(self, tmp_path):
        store = self._make_threadsafe_store(tmp_path)
        errors: list[Exception] = []

        def _record(i: int) -> None:
            try:
                store.record_stage(
                    stage="merge",
                    country=f"c{i:03d}",
                    variable="pr",
                    command=f"cmd_{i}",
                    status="SUCCESS",
                    exit_code=0,
                    attempt=1,
                )
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_record, args=(i,)) for i in range(self.N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Exceptions during concurrent writes: {errors}"
        assert len(store._manifest["stages"]) == self.N

    def test_concurrent_writes_manifest_is_valid_json(self, tmp_path):
        store = self._make_threadsafe_store(tmp_path)
        barrier = threading.Barrier(self.N)

        def _record(i: int) -> None:
            barrier.wait()  # all threads start simultaneously
            store.record_stage(
                stage="merge", country=f"c{i:03d}", variable="pr",
                command=f"cmd", status="SUCCESS", exit_code=0, attempt=1,
            )

        threads = [threading.Thread(target=_record, args=(i,)) for i in range(self.N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # The manifest file must be parseable JSON after concurrent writes
        manifest_file = store._manifest_path
        data = json.loads(manifest_file.read_text())
        assert isinstance(data["stages"], list)
        assert len(data["stages"]) == self.N

    def test_is_complete_thread_safe(self, tmp_path):
        store = self._make_threadsafe_store(tmp_path)
        store.record_stage(
            stage="merge", country="eth", variable="pr",
            command="cmd", status="SUCCESS", exit_code=0, attempt=1,
        )
        results: list[bool] = []
        errors: list[Exception] = []

        def _check() -> None:
            try:
                results.append(store.is_complete("merge", "eth", "pr", ""))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_check) for _ in range(self.N)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert all(results)
