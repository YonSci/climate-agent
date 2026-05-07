"""
state_store.py — Run manifest writer, fingerprinting, and checkpoint management.

One StateStore instance per run. Call open_run() at the start and close_run()
at the end. All pipeline stages append to the manifest incrementally via
record_stage() so progress is never lost on crash.
"""

from __future__ import annotations
import json
import hashlib
import logging
import platform
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import xarray as xr
import numpy as np

try:
    import jsonschema
    _SCHEMA_PATH = Path(__file__).resolve().parents[1] / "run_manifest_schema.json"
    with open(_SCHEMA_PATH) as _f:
        _MANIFEST_SCHEMA = json.load(_f)
    _HAS_SCHEMA = True
except Exception as _schema_exc:
    _HAS_SCHEMA = False
    _MANIFEST_SCHEMA = {}
    import logging as _log
    _log.getLogger(__name__).warning(
        f"run_manifest_schema.json could not be loaded — manifests will not be "
        f"validated against schema: {_schema_exc}"
    )

from agent.artifact_manager import manifest_path, log_path

logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return f"sha256:{h.hexdigest()}"


def _env_info() -> dict:
    def _pkg_version(name: str) -> str:
        try:
            import importlib.metadata
            return importlib.metadata.version(name)
        except Exception:
            return "unknown"

    # Prefer git commit hash; fall back to a content hash of the scripts directory
    # so the fingerprint changes whenever any script is modified, even without git.
    commit = "unknown"
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        try:
            from agent.artifact_manager import SCRIPTS_DIR
            h = hashlib.sha256()
            for p in sorted(SCRIPTS_DIR.glob("*.py")):
                h.update(p.read_bytes())
            commit = f"scripts:{h.hexdigest()[:8]}"
        except Exception:
            pass

    config_hash = "unknown"
    try:
        from agent.artifact_manager import ROOT
        cfg_path = ROOT / "agent_config.yaml"
        config_hash = "sha256:" + hashlib.sha256(cfg_path.read_bytes()).hexdigest()[:16]
    except Exception:
        pass

    return {
        "python_version": platform.python_version(),
        "xarray_version": _pkg_version("xarray"),
        "numpy_version": _pkg_version("numpy"),
        "geopandas_version": _pkg_version("geopandas"),
        "platform": platform.platform(),
        "script_commit": commit,
        "agent_config_hash": config_hash,
    }


class StateStore:
    """Manages one run's manifest, logging, and completion checkpoints."""

    def __init__(self, run_id: str, request: dict):
        self.run_id = run_id
        self._lock = threading.Lock()
        self._manifest_path = manifest_path(run_id)
        self._log_path = log_path(run_id)
        self._manifest: dict[str, Any] = {
            "run_id": run_id,
            "timestamp": _utcnow(),
            "request": request,
            "environment": _env_info(),
            "stages": [],
            "summary": {},
        }
        self._start_time = datetime.now(timezone.utc)
        self._flush()

    # ── Public API ────────────────────────────────────────────────────────────

    @classmethod
    def resume(cls, prior_run_id: str, new_run_id: str, request: dict) -> "StateStore":
        """
        Create a new StateStore seeded with successful stages from a prior run.

        Stages that were SUCCESS in *prior_run_id* will be returned as complete
        by is_complete(), causing the orchestrator to skip them without re-running.
        """
        store = cls(new_run_id, request)
        prior_path = manifest_path(prior_run_id)
        if not prior_path.exists():
            raise FileNotFoundError(
                f"Prior run manifest not found: {prior_path}"
            )
        with open(prior_path) as f:
            prior = json.load(f)

        # Guard: refuse to resume a run with a different scenario — SUCCESS stages
        # from a historical run are meaningless in a projection context and vice-versa.
        prior_req = prior.get("request", {})
        prior_scenario = prior_req.get("scenario")
        new_scenario   = request.get("scenario")
        if prior_scenario and new_scenario and prior_scenario != new_scenario:
            raise ValueError(
                f"Cannot resume {prior_run_id}: scenario mismatch "
                f"(prior={prior_scenario!r}, requested={new_scenario!r}). "
                "Use --resume only to continue a run with the same scenario."
            )

        carried = [s for s in prior.get("stages", []) if s["status"] == "SUCCESS"]
        store._manifest["stages"].extend(carried)
        store._manifest["resumed_from"] = prior_run_id
        store._flush()
        logger.info(
            f"[{new_run_id}] Resumed from {prior_run_id}: "
            f"loaded {len(carried)} completed stage(s)"
        )
        return store

    def record_stage(self, *, stage: str, country: str, variable: str,
                     scenario: str = "", command: str, status: str,
                     input_files: list[str] | None = None,
                     output_file: str | None = None,
                     exit_code: int | None = None,
                     attempt: int = 1,
                     validation: dict | None = None,
                     stdout_tail: str = "",
                     stderr_tail: str = "",
                     error_message: str = "",
                     fallback_used: bool = False,
                     fallback_path: str = "") -> None:
        entry: dict[str, Any] = {
            "stage": stage,
            "country": country,
            "variable": variable,
            "scenario": scenario,
            "command": command,
            "finished_at": _utcnow(),
            "exit_code": exit_code,
            "attempt": attempt,
            "status": status,
            "input_files": input_files or [],
            "output_file": output_file or "",
            "validation": validation or {},
            "stdout_tail": stdout_tail,
            "stderr_tail": stderr_tail,
            "error_message": error_message,
            "fallback_used": fallback_used,
            "fallback_path": fallback_path,
        }

        if output_file:
            p = Path(output_file)
            if p.exists():
                entry["output_hash"] = _sha256(p)
                entry["output_size_bytes"] = p.stat().st_size

        if input_files:
            entry["input_hashes"] = {
                f: _sha256(Path(f)) for f in input_files if Path(f).exists()
            }

        with self._lock:
            self._manifest["stages"].append(entry)
            self._flush()
        logger.info(f"[{self.run_id}] {stage}/{country}/{variable} -> {status}")

    def is_complete(self, stage: str, country: str, variable: str,
                    scenario: str = "") -> bool:
        """Return True if this slice stage already succeeded in a previous run."""
        with self._lock:
            for s in self._manifest["stages"]:
                if (s["stage"] == stage and s["country"] == country
                        and s["variable"] == variable
                        and s.get("scenario", "") == scenario
                        and s["status"] == "SUCCESS"):
                    return True
        return False

    def close_run(
        self,
        output_files: list[str],
        diagnostic_files: list[str],
        qc_stats: dict | None = None,
        download_report: list[dict] | None = None,
    ) -> None:
        with self._lock:
            stages = self._manifest["stages"]
            succeeded = sum(1 for s in stages if s["status"] == "SUCCESS")
            failed    = sum(1 for s in stages if s["status"] == "FAILED")
            warnings  = sum(1 for s in stages if s["status"] == "WARNING")
            skipped   = sum(1 for s in stages if s["status"] == "SKIPPED")

            elapsed = (datetime.now(timezone.utc) - self._start_time).total_seconds()

            failed_slices = [
                {"country": s["country"], "variable": s["variable"],
                 "scenario": s.get("scenario", ""), "stage": s["stage"],
                 "reason": s.get("error_message", "")}
                for s in stages if s["status"] == "FAILED"
            ]

            summary: dict[str, Any] = {
                "total_slices": len(stages),
                "succeeded": succeeded,
                "failed": failed,
                "warnings": warnings,
                "skipped": skipped,
                "duration_seconds": round(elapsed, 1),
                "failed_slices": failed_slices,
                "output_files": output_files,
                "diagnostic_files": diagnostic_files,
            }
            if qc_stats:
                summary["qc_stats"] = qc_stats

            if download_report:
                total_dl  = len(download_report)
                ok_dl     = sum(1 for d in download_report if d.get("ok"))
                total_mb  = sum(d.get("size_bytes", 0) for d in download_report) / 1024 / 1024
                summary["downloads"] = {
                    "total":    total_dl,
                    "succeeded": ok_dl,
                    "failed":   total_dl - ok_dl,
                    "total_mb": round(total_mb, 2),
                    "files":    download_report,
                }

            self._manifest["summary"] = summary
            self._flush(validate=True)
        logger.info(
            f"Run {self.run_id} closed — "
            f"OK={succeeded} FAIL={failed} WARN={warnings} SKIP={skipped} "
            f"({elapsed:.0f}s)"
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _flush(self, validate: bool = False) -> None:
        self._manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._manifest_path, "w") as f:
            json.dump(self._manifest, f, indent=2, default=str)
        if validate and _HAS_SCHEMA:
            self._validate_schema()

    def _validate_schema(self) -> None:
        try:
            jsonschema.validate(self._manifest, _MANIFEST_SCHEMA)
        except jsonschema.ValidationError as exc:
            logger.warning(
                f"Manifest schema violation in {self._manifest_path.name}: "
                f"{exc.message} at {list(exc.absolute_path)}"
            )
