#!/usr/bin/env python3
"""
run_agent.py — Climate Data Processing Agent entry point.

Usage
-----
python run_agent.py \\
    --countries eth ken \\
    --variables tas rh pr \\
    --scenario historical \\
    --period 2010 2025 \\
    --mode strict \\
    --workers 2

python run_agent.py \\
    --countries eth \\
    --variables rh pr tas vpd \\
    --scenario ssp245 \\
    --period 2040 2070 \\
    --diagnostics
"""

from __future__ import annotations
import argparse
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

# Ensure the project root is on sys.path so 'agent' package resolves correctly
# when the script is called from any working directory.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


def _ensure_codes_alias() -> None:
    """Create codes/ → scripts/ alias required by the workflow scripts.

    The workflow scripts call sub-scripts via WORKSPACE_ROOT/codes/... .
    On a fresh clone only scripts/ exists; codes/ must be created as a
    symlink (Unix) or directory junction (Windows) before any run.
    """
    codes = _HERE / "codes"
    scripts = _HERE / "scripts"
    if codes.exists() or codes.is_symlink():
        return
    try:
        import os
        os.symlink(scripts, codes, target_is_directory=True)
    except (OSError, NotImplementedError):
        import subprocess
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(codes), str(scripts)],
            check=True, capture_output=True,
        )


_ensure_codes_alias()

from agent.policy import validate_request, VALID_COUNTRIES, VALID_VARIABLES, VALID_SCENARIOS
from agent.preflight import run_preflight
from agent.task_router import TaskRouter
from agent.planner import Planner
from agent.state_store import StateStore
from agent.orchestrator import Orchestrator
from agent.artifact_manager import LOGS_DIR, run_report, cleanup_intermediates


def _setup_logging(run_id: str, level: str = "INFO") -> None:
    log_file = LOGS_DIR / f"{run_id}.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=fmt,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file),
        ],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Climate Data Processing Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--countries", nargs="+", required=True,
        metavar="CODE",
        help=f"Country short code(s): {sorted(VALID_COUNTRIES)}",
    )
    parser.add_argument(
        "--variables", nargs="+", required=True,
        metavar="VAR",
        help=f"Variable(s): {sorted(VALID_VARIABLES)}",
    )
    parser.add_argument(
        "--scenario", required=True,
        choices=sorted(VALID_SCENARIOS),
        help="Climate scenario",
    )
    parser.add_argument(
        "--period", nargs=2, type=int, required=True,
        metavar=("START", "END"),
        help="Year range, e.g. --period 2010 2025",
    )
    parser.add_argument(
        "--mode", choices=["strict", "fast"], default="strict",
        help="Validation mode (default: strict)",
    )
    parser.add_argument(
        "--diagnostics", action="store_true",
        help="Produce QA diagnostic plots for each output",
    )
    parser.add_argument(
        "--workers", type=int, default=1,
        help="Parallel worker count (default: 1)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print planned commands without executing",
    )
    parser.add_argument(
        "--skip-preflight", action="store_true",
        help="Skip preflight environment checks (not recommended)",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO)",
    )
    parser.add_argument(
        "--resume",
        metavar="RUN_ID",
        default=None,
        help="Resume from a previous run: skip stages already recorded as SUCCESS "
             "in runs/manifests/{RUN_ID}.json",
    )
    return parser.parse_args()


def _run_list_runs_mode() -> int | None:
    """Handle --list-runs [--limit N] [--failed] early exit.

    Scans runs/manifests/ and prints a summary table of past runs sorted by
    most-recent first. Returns exit code when handled, None to continue.
    """
    if "--list-runs" not in sys.argv:
        return None

    args = sys.argv[1:]
    limit = 20
    failed_only = "--failed" in args
    try:
        li = args.index("--limit")
        limit = int(args[li + 1])
    except (ValueError, IndexError):
        pass

    from agent.artifact_manager import MANIFESTS_DIR

    manifests_dir = MANIFESTS_DIR
    try:
        mi = args.index("--manifests-dir")
        manifests_dir = Path(args[mi + 1])
    except (ValueError, IndexError):
        pass

    manifests = sorted(manifests_dir.glob("run_*.json"), reverse=True) if manifests_dir.exists() else []
    if not manifests:
        print(f"No run manifests found in {manifests_dir}.")
        return 0

    rows = []
    for mpath in manifests:
        try:
            with open(mpath) as f:
                m = json.load(f)
        except Exception:
            continue

        summary = m.get("summary", {})
        req     = m.get("request", {})
        ok      = summary.get("failed", 1) == 0
        if failed_only and ok:
            continue

        rows.append({
            "run_id":    m.get("run_id", mpath.stem),
            "timestamp": m.get("timestamp", "")[:19].replace("T", " "),
            "scenario":  req.get("scenario", "?"),
            "countries": ",".join(req.get("countries", [])),
            "variables": ",".join(req.get("variables", [])),
            "period":    "{}-{}".format(*req["period"]) if req.get("period") else "?",
            "ok":        summary.get("succeeded", 0),
            "fail":      summary.get("failed", 0),
            "warn":      summary.get("warnings", 0),
            "dur":       f"{summary.get('duration_seconds', 0):.0f}s",
            "status":    "OK" if ok else "FAIL",
        })
        if len(rows) >= limit:
            break

    if not rows:
        print("No matching runs found.")
        return 0

    # Print table
    hdr = f"{'RUN ID':<26}  {'TIMESTAMP':<19}  {'SCENARIO':<12}  {'COUNTRIES':<15}  {'VARIABLES':<16}  {'PERIOD':<10}  {'OK':>4}  {'FAIL':>4}  {'WARN':>4}  {'DUR':>6}  STATUS"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(
            f"{r['run_id']:<26}  {r['timestamp']:<19}  {r['scenario']:<12}  "
            f"{r['countries']:<15}  {r['variables']:<16}  {r['period']:<10}  "
            f"{r['ok']:>4}  {r['fail']:>4}  {r['warn']:>4}  {r['dur']:>6}  {r['status']}"
        )
    print(f"\n{len(rows)} run(s) shown. Use --limit N or --failed to filter.")
    return 0


def _run_validate_mode() -> int | None:
    """Handle --validate-run [RUN_ID] [--checks] [--no-color] early exit.

    Invoked before parse_args() so users don't need to supply --countries etc.
    Returns exit code when handled, None to continue normal pipeline mode.
    """
    if "--validate-run" not in sys.argv:
        return None
    import importlib.util as _ilu
    args = sys.argv[1:]
    idx = args.index("--validate-run")
    run_id = args[idx + 1] if idx + 1 < len(args) and not args[idx + 1].startswith("-") else None
    show_checks = "--checks" in args
    no_color = "--no-color" in args

    vr_path = _HERE / "scripts" / "validate_run.py"
    spec = _ilu.spec_from_file_location("validate_run", vr_path)
    vr = _ilu.module_from_spec(spec)
    spec.loader.exec_module(vr)

    vr_args = []
    if run_id:
        vr_args += ["--run-id", run_id]
    if show_checks:
        vr_args += ["--checks"]
    if no_color:
        vr_args += ["--no-color"]
    orig_argv, sys.argv = sys.argv[:], [sys.argv[0]] + vr_args
    try:
        return vr.main()
    finally:
        sys.argv = orig_argv


def _run_country_plan(
    plan,
    orch,
    run_id: str,
) -> tuple[bool, list[str], list[str], dict]:
    """Execute all stages for a single-country sub-plan (runs in a thread)."""
    outputs: list[str] = []
    diag_files: list[str] = []
    qc_stats: dict = {}
    for stage in plan.stages:
        ok = orch.run_tool(
            stage=stage.name,
            script_name=stage.script,
            args=stage.args,
            countries=plan.countries,
            variables=plan.variables,
            scenario=plan.scenario,
            expected_outputs=stage.expected_outputs,
        )
        if not ok:
            return False, outputs, diag_files, qc_stats
        outputs.extend(
            str(o.path) for o in stage.expected_outputs if o.path.exists()
        )
        if plan.diagnostics and stage.expected_outputs:
            plots, stage_qc = orch.run_diagnostics(run_id, stage.expected_outputs)
            diag_files.extend(plots)
            qc_stats.update(stage_qc)
    return True, outputs, diag_files, qc_stats


def main() -> int:
    code = _run_list_runs_mode()
    if code is not None:
        return code

    code = _run_validate_mode()
    if code is not None:
        return code

    args = parse_args()

    if args.workers < 1:
        print(f"ERROR: --workers must be at least 1 (got {args.workers})", file=sys.stderr)
        return 1

    run_id = f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    _setup_logging(run_id, args.log_level)
    logger = logging.getLogger(__name__)

    logger.info(f"=== Climate Agent — {run_id} ===")

    request = {
        "countries":     args.countries,
        "variables":     args.variables,
        "scenario":      args.scenario,
        "period":        args.period,
        "quality_level": args.mode,
        "diagnostics":   args.diagnostics,
        "workers":       args.workers,
    }

    # ── Request validation ────────────────────────────────────────────────────
    try:
        validate_request(
            request["countries"],
            request["variables"],
            request["scenario"],
            tuple(request["period"]),
        )
    except ValueError as exc:
        logger.error(f"Invalid request: {exc}")
        return 1

    logger.info(
        f"Request: countries={args.countries} variables={args.variables} "
        f"scenario={args.scenario} period={args.period} mode={args.mode}"
    )

    # ── Preflight ─────────────────────────────────────────────────────────────
    if not args.skip_preflight:
        logger.info("Running preflight checks…")
        report = run_preflight(request)
        if report.has_errors:
            logger.error(f"Preflight FAILED — resolve errors before re-running:\n{report}")
            return 1
        if report.warnings:
            logger.warning(f"Preflight warnings (continuing):\n{report}")

    # ── Build workflow plan ───────────────────────────────────────────────────
    router = TaskRouter()
    try:
        plan = router.route(request)
    except ValueError as exc:
        logger.error(f"Routing failed: {exc}")
        return 1

    logger.info(
        f"Workflow plan: type={plan.run_type} "
        f"stages={[s.name for s in plan.stages]}"
    )

    # ── Plan validation ───────────────────────────────────────────────────────
    plan_issues = Planner().validate(plan)
    for issue in plan_issues:
        logger.warning(f"Plan issue: {issue}")

    if args.dry_run:
        print(f"\nDRY RUN — run_id: {run_id}")
        print(f"Run type : {plan.run_type}")
        print(f"Countries: {plan.countries}")
        print(f"Variables: {plan.variables}")
        print(f"Scenario : {plan.scenario}")
        print(f"Period   : {plan.period[0]}–{plan.period[1]}")
        if plan_issues:
            print(f"\nPlan warnings ({len(plan_issues)}):")
            for issue in plan_issues:
                print(f"  ! {issue}")
        print()
        for i, stage in enumerate(plan.stages, 1):
            print(f"Stage {i}: {stage.name}")
            print(f"  script: {stage.script}")
            print(f"  args  : {' '.join(stage.args)}")
        return 0

    # ── Execute pipeline ──────────────────────────────────────────────────────
    if args.resume:
        try:
            store = StateStore.resume(args.resume, run_id, request)
            logger.info(f"Resuming from prior run: {args.resume}")
        except FileNotFoundError as exc:
            logger.error(str(exc))
            return 1
    else:
        store = StateStore(run_id, request)
    orch  = Orchestrator(store, fast_mode=(args.mode == "fast"))

    all_ok = True
    all_outputs: list[str] = []
    all_diag_files: list[str] = []
    all_qc_stats: dict = {}

    if args.workers > 1 and len(plan.countries) > 1:
        # Fan out one subprocess per country and run them in parallel.
        # StateStore is thread-safe (uses threading.Lock internally).
        country_plans = plan.split_by_country()
        logger.info(
            f"Parallel execution: {len(country_plans)} countries "
            f"across {args.workers} workers"
        )
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futs = {
                executor.submit(_run_country_plan, cp, orch, run_id): cp.countries[0]
                for cp in country_plans
            }
            for fut in as_completed(futs):
                country = futs[fut]
                ok, c_outputs, c_diags, c_qc = fut.result()
                if not ok:
                    logger.error(f"Country '{country}' FAILED")
                    all_ok = False
                all_outputs.extend(c_outputs)
                all_diag_files.extend(c_diags)
                all_qc_stats.update(c_qc)
    else:
        for stage in plan.stages:
            logger.info(f"Executing stage: {stage.name}")
            success = orch.run_tool(
                stage=stage.name,
                script_name=stage.script,
                args=stage.args,
                countries=plan.countries,
                variables=plan.variables,
                scenario=plan.scenario,
                expected_outputs=stage.expected_outputs,
            )
            if not success:
                logger.error(f"Stage '{stage.name}' FAILED — aborting remaining stages")
                all_ok = False
                break

            all_outputs.extend(
                str(o.path) for o in stage.expected_outputs if o.path.exists()
            )
            if plan.diagnostics and stage.expected_outputs:
                logger.info(f"Running diagnostics for stage: {stage.name}")
                plots, stage_qc = orch.run_diagnostics(run_id, stage.expected_outputs)
                all_diag_files.extend(plots)
                all_qc_stats.update(stage_qc)

    # ── Close run ─────────────────────────────────────────────────────────────
    dl_report = orch.download_report if orch.download_report else None
    if dl_report:
        ok_dl  = sum(1 for d in dl_report if d.get("ok"))
        tot_mb = sum(d.get("size_bytes", 0) for d in dl_report) / 1024 / 1024
        logger.info(
            f"Downloads: {ok_dl}/{len(dl_report)} succeeded, "
            f"{tot_mb:.1f} MB total"
        )
        for d in dl_report:
            status = "OK" if d["ok"] else f"FAILED ({d.get('error', '')})"
            mb = d.get("size_bytes", 0) / 1024 / 1024
            logger.info(f"  {d['label']:<30} {mb:>7.1f} MB  {status}")

    store.close_run(
        output_files=all_outputs,
        diagnostic_files=all_diag_files,
        qc_stats=all_qc_stats or None,
        download_report=dl_report,
    )

    report_path = run_report(run_id)
    summary = store._manifest.get("summary", {})
    with open(report_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    logger.info(f"Run report written to: {report_path}")

    # ── Post-run cleanup ──────────────────────────────────────────────────────
    if all_ok:
        deleted = cleanup_intermediates(args.countries, args.variables)
        if deleted:
            logger.info(
                f"Cleaned up {len(deleted)} intermediate file(s) "
                "(cleanup.delete_intermediates_on_success=true)"
            )

    logger.info(
        f"=== Run {'SUCCEEDED' if all_ok else 'FAILED'}: {run_id} "
        f"({summary.get('duration_seconds', 0):.0f}s) ==="
    )

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
