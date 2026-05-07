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

from agent.policy import validate_request, VALID_COUNTRIES, VALID_VARIABLES, VALID_SCENARIOS
from agent.preflight import run_preflight
from agent.task_router import TaskRouter
from agent.planner import Planner
from agent.state_store import StateStore
from agent.orchestrator import Orchestrator
from agent.artifact_manager import LOGS_DIR, run_report


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
    args = parse_args()

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
    store.close_run(
        output_files=all_outputs,
        diagnostic_files=all_diag_files,
        qc_stats=all_qc_stats or None,
    )

    report_path = run_report(run_id)
    summary = store._manifest.get("summary", {})
    with open(report_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    logger.info(f"Run report written to: {report_path}")
    logger.info(
        f"=== Run {'SUCCEEDED' if all_ok else 'FAILED'}: {run_id} "
        f"({summary.get('duration_seconds', 0):.0f}s) ==="
    )

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
