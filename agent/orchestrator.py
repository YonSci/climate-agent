"""
orchestrator.py — Executes DAG pipeline steps as subprocess calls.

The Orchestrator is the only place where subprocess.run() is called.
It handles parameter templating, retry logic, stdout/stderr capture,
post-stage validation via ValidationEngine, and delegates all recording
to the StateStore.
"""

from __future__ import annotations
import subprocess
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from agent.policy import should_retry, wait_before_retry, SHORT_TO_LONG, HIST_SOURCE_DIRS
from agent.state_store import StateStore
from agent.artifact_manager import SCRIPTS_DIR, ROOT, diagnostics_dir
from agent.validation_engine import ValidationEngine
from agent.output_resolver import ExpectedOutput
import connectors.agera5_connector as _agera5_conn
import connectors.chirps_connector as _chirps_conn

logger = logging.getLogger(__name__)

LOG_TAIL = 20
_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _tail(text: str, n: int = LOG_TAIL) -> str:
    lines = text.strip().splitlines()
    return "\n".join(lines[-n:]) if lines else ""


def _apply_legacy_rename(exp: ExpectedOutput) -> bool:
    """
    If exp.path is absent but exp.legacy_path exists, rename legacy → primary.

    Returns True if a rename happened (or primary already exists), False if
    neither path is present.
    """
    if exp.path.exists():
        return True
    legacy = getattr(exp, "legacy_path", None)
    if legacy and legacy.exists():
        exp.path.parent.mkdir(parents=True, exist_ok=True)
        legacy.rename(exp.path)
        logger.info(
            f"Legacy rename: {legacy.name} → {exp.path.name} "
            f"(script hardcoded period resolved)"
        )
        return True
    return False


def _run_output_validation(
    expected_outputs: list[ExpectedOutput],
    fast_mode: bool,
) -> tuple[dict, bool]:
    """
    Validate every expected output with ValidationEngine.

    Before validating, attempt a legacy-path rename for any missing primary file
    whose legacy_path exists (handles run_historical_workflow.py hardcoded period).

    Returns (validation_dict, all_passed).
    validation_dict keys are filenames; values are per-check result dicts.
    all_passed is False if any check returned 'FAIL'.
    """
    ve = ValidationEngine(fast_mode=fast_mode)
    results: dict[str, dict] = {}
    all_passed = True

    for exp in expected_outputs:
        _apply_legacy_rename(exp)
        check = ve.validate(
            exp.path,
            variable=exp.variable,
            expected_units=exp.expected_units,
            period=exp.period,
            require_daily_axis=exp.require_daily_axis,
            target_grid_path=getattr(exp, "target_grid_path", None),
            valid_range=getattr(exp, "valid_range", None),
            is_clipped=getattr(exp, "is_clipped", False),
        )
        results[exp.path.name] = check
        if any(v == "FAIL" for v in check.values() if isinstance(v, str)):
            all_passed = False
            logger.warning(
                f"Post-stage validation FAIL on {exp.path.name}: "
                + ", ".join(f"{k}={v}" for k, v in check.items() if v == "FAIL")
            )

    return results, all_passed


class Orchestrator:
    """Runs pipeline stages as subprocesses with retry and logging."""

    def __init__(self, store: StateStore, fast_mode: bool = False):
        self.store = store
        self.fast_mode = fast_mode

    def run_stage(self, *,
                  stage: str,
                  country: str,
                  variable: str,
                  scenario: str = "",
                  cmd: list[str],
                  input_files: list[str] | None = None,
                  output_file: str | None = None,
                  validator=None) -> bool:
        """
        Execute a single-slice pipeline stage subprocess, with retry.

        Parameters
        ----------
        stage        : stage name (must match manifest schema enum)
        country      : country short code
        variable     : variable name
        scenario     : scenario (empty for historical)
        cmd          : subprocess command list
        input_files  : list of input file paths for fingerprinting
        output_file  : expected output path
        validator    : callable(output_path, fast_mode) → dict, or None

        Returns True on success, False on failure.
        """
        if self.store.is_complete(stage, country, variable, scenario):
            logger.info(f"SKIP {stage}/{country}/{variable} (already complete)")
            self.store.record_stage(
                stage=stage, country=country, variable=variable,
                scenario=scenario, command=" ".join(cmd),
                status="SKIPPED", input_files=input_files,
                output_file=output_file
            )
            return True

        cmd_str = " ".join(str(x) for x in cmd)
        logger.info(f"RUN  {stage}/{country}/{variable} -> {cmd_str}")

        exit_code = 1
        stdout_tail = stderr_tail = ""
        for attempt in range(1, 4):
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    cwd=str(_PROJECT_ROOT))
            stdout_tail = _tail(result.stdout)
            stderr_tail = _tail(result.stderr)
            exit_code   = result.returncode

            if exit_code == 0:
                validation = {}
                if validator and output_file:
                    try:
                        validation = validator(Path(output_file), self.fast_mode)
                    except Exception as e:
                        logger.warning(f"Validator error: {e}")
                        validation = {"error": str(e)}

                val_failed = any(
                    v == "FAIL" for v in validation.values()
                    if isinstance(v, str)
                )
                self.store.record_stage(
                    stage=stage, country=country, variable=variable,
                    scenario=scenario, command=cmd_str,
                    status="WARNING" if val_failed else "SUCCESS",
                    input_files=input_files, output_file=output_file,
                    exit_code=exit_code, attempt=attempt,
                    validation=validation,
                    stdout_tail=stdout_tail, stderr_tail=stderr_tail,
                )
                return not val_failed

            logger.warning(
                f"  attempt {attempt} failed (exit {exit_code})\n"
                f"  stderr: {stderr_tail[:200]}"
            )
            if not should_retry(exit_code, attempt):
                break
            wait_before_retry(attempt)

        self.store.record_stage(
            stage=stage, country=country, variable=variable,
            scenario=scenario, command=cmd_str,
            status="FAILED", input_files=input_files, output_file=output_file,
            exit_code=exit_code, attempt=attempt,
            stdout_tail=stdout_tail, stderr_tail=stderr_tail,
            error_message=f"Failed after {attempt} attempt(s). "
                          f"Last stderr: {stderr_tail[-300:]}"
        )
        return False

    def _check_and_download_source(
        self,
        countries: list[str],
        variables: list[str],
        year_start: int,
        year_end: int,
    ) -> None:
        """
        Download missing AgERA5 / CHIRPS raw files before historical merge stages,
        using a thread pool so multiple year slices download concurrently.

        Only acts when the merge scripts' expected source directory is absent or empty.
        Downloads to the canonical raw/ location; does not raise on failure — missing
        sources will surface as errors when the workflow script itself runs.
        """
        data_root = ROOT / "data"

        # Collect all (cmd, label, raw_path) tuples that need downloading
        pending: list[tuple[list[str], str, Path]] = []

        for country in countries:
            long = SHORT_TO_LONG[country]
            for var in variables:
                src_template = HIST_SOURCE_DIRS.get(var)
                if src_template is None:
                    continue

                src_dir = data_root / src_template.format(country=long)
                if src_dir.exists() and any(src_dir.iterdir()):
                    logger.debug(f"Source present for {country}/{var}: {src_dir}")
                    continue

                logger.info(
                    f"Source dir absent or empty for {country}/{var} "
                    f"({src_dir}) — queuing raw download"
                )

                if var == "pr":
                    for year in range(year_start, year_end + 1):
                        raw = _chirps_conn.expected_path(year)
                        if not raw.exists():
                            pending.append((_chirps_conn.build_cmd(year),
                                            f"CHIRPS/{year}", raw))
                elif var in _agera5_conn.SUPPORTED_VARIABLES:
                    for year in range(year_start, year_end + 1):
                        raw = _agera5_conn.expected_path(var, year)
                        if not raw.exists():
                            pending.append((_agera5_conn.build_cmd(var, year),
                                            f"AgERA5/{var}/{year}", raw))

        if not pending:
            return

        def _run_one(item: tuple[list[str], str, Path]) -> tuple[str, bool, str]:
            cmd, label, raw = item
            logger.info(f"Downloading {label}")
            res = subprocess.run(cmd, capture_output=True, text=True,
                                 cwd=str(_PROJECT_ROOT))
            ok = res.returncode == 0
            return label, ok, _tail(res.stderr, 5) if not ok else str(raw)

        max_workers = min(len(pending), 4)
        logger.info(f"Starting {len(pending)} download(s) with {max_workers} worker(s)")
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_run_one, item): item for item in pending}
            for fut in as_completed(futures):
                label, ok, detail = fut.result()
                if ok:
                    logger.info(f"  downloaded {label} -> {detail}")
                else:
                    logger.warning(f"  download FAILED [{label}]: {detail}")

    def run_tool(self, *,
                 stage: str,
                 script_name: str,
                 args: list[str],
                 countries: list[str],
                 variables: list[str],
                 scenario: str,
                 expected_outputs: list[ExpectedOutput] | None = None) -> bool:
        """
        Run a top-level workflow script as a deterministic tool, then
        validate its expected outputs with ValidationEngine.

        Parameters
        ----------
        stage            : stage name for manifest
        script_name      : filename in scripts/
        args             : CLI arguments for the script
        countries        : short country codes (manifest metadata)
        variables        : variable names (manifest metadata)
        scenario         : scenario string (manifest metadata + skip check)
        expected_outputs : outputs to validate after subprocess succeeds;
                           None or [] skips post-stage validation

        Returns
        -------
        True  — subprocess exited 0 AND all validations passed (or skipped).
        False — subprocess failed OR (strict mode AND any validation FAIL).
        In fast mode, validation failures are recorded as WARNING but still
        return True so subsequent stages are not aborted.
        """
        country_key  = ",".join(countries)
        variable_key = ",".join(variables)

        if self.store.is_complete(stage, country_key, variable_key, scenario):
            logger.info(f"SKIP tool {stage} (already complete)")
            return True

        # ── Pre-stage: download missing source files for historical runs ─────────
        if script_name == "run_historical_workflow.py" and scenario == "historical":
            str_args = [str(a) for a in args]

            def _get_int_arg(flag: str, default: int) -> int:
                try:
                    return int(str_args[str_args.index(flag) + 1])
                except (ValueError, IndexError):
                    return default

            self._check_and_download_source(
                countries, variables,
                _get_int_arg("--start-year", 1981),
                _get_int_arg("--end-year", 2023),
            )

        script_path = SCRIPTS_DIR / script_name
        cmd = [sys.executable, str(script_path)] + [str(a) for a in args]
        cmd_str = " ".join(cmd)
        logger.info(f"RUN  tool {stage} -> {script_name} {' '.join(str(a) for a in args)}")

        exit_code = 1
        stdout_tail = stderr_tail = ""
        for attempt in range(1, 4):
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    cwd=str(_PROJECT_ROOT))
            stdout_tail = _tail(result.stdout)
            stderr_tail = _tail(result.stderr)
            exit_code   = result.returncode

            if exit_code == 0:
                # ── Post-stage output validation ──────────────────────────────
                validation_summary: dict = {}
                all_valid = True
                if expected_outputs:
                    validation_summary, all_valid = _run_output_validation(
                        expected_outputs, self.fast_mode
                    )
                    n_fail = sum(
                        1 for r in validation_summary.values()
                        if any(v == "FAIL" for v in r.values() if isinstance(v, str))
                    )
                    if n_fail:
                        logger.warning(
                            f"Post-stage validation: {n_fail}/{len(expected_outputs)} "
                            f"output(s) have FAIL checks"
                        )

                    # ── Cross-file grid consistency (≥2 outputs) ──────────────
                    if len(expected_outputs) >= 2 and not self.fast_mode:
                        consistency = ValidationEngine(fast_mode=False).check_grid_consistency(
                            [(exp.path, exp.variable) for exp in expected_outputs]
                        )
                        overall = consistency.pop("overall", "SKIP")
                        if overall == "FAIL":
                            logger.warning(
                                "Cross-file grid consistency FAIL: outputs do not share "
                                "the same lat/lon grid. Check regrid stage."
                            )
                            all_valid = False
                        validation_summary["_grid_consistency"] = consistency

                # Strict mode aborts on any FAIL; fast mode records WARNING only
                effective_status = (
                    "SUCCESS" if all_valid
                    else ("WARNING" if self.fast_mode else "WARNING")
                )

                self.store.record_stage(
                    stage=stage,
                    country=country_key,
                    variable=variable_key,
                    scenario=scenario,
                    command=cmd_str,
                    status=effective_status,
                    exit_code=exit_code,
                    attempt=attempt,
                    validation=validation_summary,
                    stdout_tail=stdout_tail,
                    stderr_tail=stderr_tail,
                )
                # In strict mode, validation failures abort subsequent stages
                return all_valid or self.fast_mode

            logger.warning(
                f"  tool attempt {attempt} failed (exit {exit_code})\n"
                f"  stderr: {stderr_tail[:200]}"
            )
            if not should_retry(exit_code, attempt):
                break
            wait_before_retry(attempt)

        self.store.record_stage(
            stage=stage,
            country=country_key,
            variable=variable_key,
            scenario=scenario,
            command=cmd_str,
            status="FAILED",
            exit_code=exit_code,
            attempt=attempt,
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
            error_message=f"Tool {script_name} failed after {attempt} attempt(s). "
                          f"Last stderr: {stderr_tail[-300:]}"
        )
        return False

    def run_diagnostics(
        self,
        run_id: str,
        expected_outputs: list[ExpectedOutput],
    ) -> tuple[list[str], dict[str, dict]]:
        """
        Call diagnose_final_netcdf.py on each output that exists on disk.

        Returns
        -------
        produced    : list of diagnostic PNG paths successfully produced
        qc_stats    : {filename: qc_dict} loaded from the _qc.json sidecars
                      written by diagnose_final_netcdf.py.

        Failures are logged as warnings but do not abort the run.
        """
        import json as _json

        script   = SCRIPTS_DIR / "diagnose_final_netcdf.py"
        diag_dir = diagnostics_dir(run_id)
        produced: list[str] = []
        qc_stats: dict[str, dict] = {}

        for exp in expected_outputs:
            if not exp.path.exists():
                logger.warning(f"Skipping diagnostics for missing output: {exp.path.name}")
                continue

            cmd = [
                sys.executable, str(script),
                "--file",    str(exp.path),
                "--var",     exp.variable,
                "--out-dir", str(diag_dir),
            ]
            logger.info(f"DIAG {exp.path.name} -> {diag_dir.name}/")
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    cwd=str(_PROJECT_ROOT))
            if result.returncode != 0:
                logger.warning(
                    f"Diagnostics failed for {exp.path.name}: "
                    f"{_tail(result.stderr, 5)}"
                )
                continue

            png = diag_dir / f"{exp.path.stem}_diagnostic.png"
            if png.exists():
                produced.append(str(png))
                logger.info(f"  plot -> {png.name}")

            # Load QC JSON sidecar written by diagnose_final_netcdf.py
            qc_json = diag_dir / f"{exp.path.stem}_qc.json"
            if qc_json.exists():
                try:
                    with open(qc_json) as f:
                        qc_stats[exp.path.name] = _json.load(f)
                    logger.info(f"  qc   -> {qc_json.name}")
                except Exception as exc:
                    logger.warning(f"Failed to load QC sidecar {qc_json.name}: {exc}")

        return produced, qc_stats
