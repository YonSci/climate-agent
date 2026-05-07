#!/usr/bin/env python3
"""
validate_run.py — Human-readable summary of any completed run manifest.

Usage
-----
python scripts/validate_run.py --run-id run_20260506_143000
python scripts/validate_run.py          # prints latest run
python scripts/validate_run.py --list   # list all available run IDs
"""

from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_MANIFESTS = _ROOT / "runs" / "manifests"

# Status → short display label
_STATUS_LABEL = {
    "SUCCESS": "OK  ",
    "FAILED":  "FAIL",
    "WARNING": "WARN",
    "SKIPPED": "SKIP",
}

# Ordered validation check keys (mirrors ValidationEngine output order)
_CHECK_KEYS = [
    "existence", "variable_present", "non_nan_coverage",
    "time_coverage", "daily_axis", "units",
    "grid_match", "spatial_bounds", "anomaly", "distribution",
]

# Color codes for terminal output
_COLOR = {"OK": "\033[32m", "FAIL": "\033[31m", "WARN": "\033[33m",
          "SKIP": "\033[90m", "RESET": "\033[0m"}


def _latest_run_id() -> str | None:
    manifests = sorted(_MANIFESTS.glob("run_*.json"))
    if not manifests:
        return None
    return manifests[-1].stem


def _load_manifest(run_id: str) -> dict:
    path = _MANIFESTS / f"{run_id}.json"
    if not path.exists():
        print(f"ERROR: manifest not found: {path}", file=sys.stderr)
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


def _list_runs() -> None:
    manifests = sorted(_MANIFESTS.glob("run_*.json"))
    if not manifests:
        print("No run manifests found in", _MANIFESTS)
        return
    print(f"{'RUN ID':<30}  {'TOTAL':>5}  {'OK':>4}  {'FAIL':>4}  {'WARN':>4}  {'SECS':>6}")
    print("-" * 60)
    for p in manifests:
        with open(p) as f:
            m = json.load(f)
        s = m.get("summary", {})
        print(
            f"{p.stem:<30}  "
            f"{s.get('total_slices', '?'):>5}  "
            f"{s.get('succeeded', '?'):>4}  "
            f"{s.get('failed', '?'):>4}  "
            f"{s.get('warnings', '?'):>4}  "
            f"{s.get('duration_seconds', '?'):>6}"
        )


def _flatten_validation(val: dict) -> dict:
    """
    Normalize the two validation dict shapes used by the orchestrator:
    - run_stage() writes flat {check: result}
    - run_tool()  writes nested {filename: {check: result}}
    Both are returned as a single flat {check: result} dict.
    """
    if not val:
        return {}
    if any(isinstance(v, dict) for v in val.values()):
        merged: dict[str, str] = {}
        for v in val.values():
            if isinstance(v, dict):
                merged.update({k: r for k, r in v.items() if isinstance(r, str)})
        return merged
    return {k: v for k, v in val.items() if isinstance(v, str)}


def _color(val: str, use_color: bool) -> str:
    if not use_color:
        return val
    c = _COLOR.get(val, "")
    return f"{c}{val}{_COLOR['RESET']}" if c else val


def _print_checks_table(manifest: dict, use_color: bool = True) -> None:
    """Print a per-check breakdown table — one row per stage, one column per check."""
    stages = manifest.get("stages", [])
    if not stages:
        print("  No stages recorded.")
        return

    # Determine which checks actually appear in this run
    active_checks = [k for k in _CHECK_KEYS
                     if any(k in _flatten_validation(s.get("validation", {}))
                            for s in stages)]
    if not active_checks:
        print("  No validation data recorded.")
        return

    header_checks = [k[:8] for k in active_checks]  # truncate to 8 chars for columns
    col_w = 8

    header = (
        f"  {'STAGE':<18} {'COUNTRY':<7} {'VAR':<7} {'STATUS':<5}  "
        + "  ".join(f"{h:<{col_w}}" for h in header_checks)
    )
    print(header)
    print("  " + "-" * (len(header) - 2))

    for s in stages:
        val = _flatten_validation(s.get("validation", {}))
        status_label = _STATUS_LABEL.get(s.get("status", "?"), "?   ")
        check_cols = []
        for k in active_checks:
            v = val.get(k, "-")
            check_cols.append(_color(f"{v:<{col_w}}", use_color))

        print(
            f"  {s.get('stage','?'):<18} "
            f"{s.get('country','?'):<7} "
            f"{s.get('variable','?'):<7} "
            f"{_color(status_label.strip(), use_color):<5}  "
            + "  ".join(check_cols)
        )

    # Legend
    print()
    print("  Checks: " + " | ".join(f"{k}={h}" for k, h in zip(active_checks, header_checks)
                                     if k != h))
    print(f"  Values: {_color('OK', use_color)} = pass  "
          f"{_color('FAIL', use_color)} = fail  "
          f"{_color('WARN', use_color)} = warning  "
          f"{_color('SKIP', use_color)} = skipped  - = not run")


def _print_qc_summary(manifest: dict, use_color: bool = True) -> None:
    """Print aggregated per-check pass/fail counts across all stages."""
    stages = manifest.get("stages", [])
    check_tallies: dict[str, dict[str, int]] = {}

    for s in stages:
        for k, v in _flatten_validation(s.get("validation", {})).items():
            if k not in check_tallies:
                check_tallies[k] = {"OK": 0, "FAIL": 0, "WARN": 0, "SKIP": 0}
            check_tallies[k][v] = check_tallies[k].get(v, 0) + 1

    if not check_tallies:
        return

    print(f"\n  {'CHECK':<20} {'OK':>4}  {'FAIL':>4}  {'WARN':>4}  {'SKIP':>4}")
    print(f"  {'-'*44}")
    for check in _CHECK_KEYS:
        if check not in check_tallies:
            continue
        t = check_tallies[check]
        fail_str = _color(f"{t.get('FAIL', 0):>4}", use_color) if t.get("FAIL", 0) > 0 else f"{t.get('FAIL', 0):>4}"
        warn_str = _color(f"{t.get('WARN', 0):>4}", use_color) if t.get("WARN", 0) > 0 else f"{t.get('WARN', 0):>4}"
        print(
            f"  {check:<20} "
            f"{t.get('OK', 0):>4}  "
            f"{fail_str}  "
            f"{warn_str}  "
            f"{t.get('SKIP', 0):>4}"
        )


def _print_report(manifest: dict, show_checks: bool = False,
                  use_color: bool = True) -> int:
    run_id = manifest["run_id"]
    req    = manifest.get("request", {})
    env    = manifest.get("environment", {})
    stages = manifest.get("stages", [])
    summ   = manifest.get("summary", {})

    print(f"\n{'='*60}")
    print(f"  Run ID   : {run_id}")
    print(f"  Started  : {manifest.get('timestamp', 'unknown')}")
    if "resumed_from" in manifest:
        print(f"  Resumed  : {manifest['resumed_from']}")
    print(f"  Countries: {req.get('countries', [])}")
    print(f"  Variables: {req.get('variables', [])}")
    print(f"  Scenario : {req.get('scenario', '?')}")
    print(f"  Period   : {req.get('period', '?')}")
    print(f"  Python   : {env.get('python_version', '?')}")
    print(f"  Commit   : {env.get('script_commit', '?')}")
    print(f"{'='*60}")

    if show_checks:
        print(f"\n  Validation checks by stage")
        print(f"  --------------------------")
        _print_checks_table(manifest, use_color=use_color)
        print(f"\n  Check summary (all stages)")
        print(f"  --------------------------")
        _print_qc_summary(manifest, use_color=use_color)
    elif stages:
        print(f"\n  {'STAGE':<18} {'COUNTRY':<8} {'VARIABLE':<10} {'STATUS':<6} {'ATTEMPT':>7}  VALIDATION")
        print(f"  {'-'*75}")
        for s in stages:
            label = _STATUS_LABEL.get(s.get("status", "?"), "?   ")
            val   = _flatten_validation(s.get("validation", {}))
            val_str = "  ".join(f"{k}={v}" for k, v in val.items()) if val else "-"
            if len(val_str) > 40:
                val_str = val_str[:37] + "..."
            print(
                f"  {s.get('stage','?'):<18} "
                f"{s.get('country','?'):<8} "
                f"{s.get('variable','?'):<10} "
                f"{label:<6} "
                f"{s.get('attempt', 1):>7}  "
                f"{val_str}"
            )

    print(f"\n  Summary")
    print(f"  -------")
    print(f"  Total   : {summ.get('total_slices', '?')}")
    print(f"  OK      : {summ.get('succeeded', '?')}")
    print(f"  Failed  : {summ.get('failed', '?')}")
    print(f"  Warned  : {summ.get('warnings', '?')}")
    print(f"  Skipped : {summ.get('skipped', '?')}")
    print(f"  Duration: {summ.get('duration_seconds', '?')}s")

    failed_slices = summ.get("failed_slices", [])
    if failed_slices:
        print(f"\n  Failed slices")
        print(f"  -------------")
        for fs in failed_slices:
            print(
                f"  [{fs.get('stage','?')}] "
                f"{fs.get('country','?')}/{fs.get('variable','?')} "
                f"({fs.get('scenario','')}): "
                f"{fs.get('reason','')[:100]}"
            )

    output_files = summ.get("output_files", [])
    if output_files:
        print(f"\n  Output files ({len(output_files)})")
        for p in output_files:
            exists = "[x]" if Path(p).exists() else "[ ]"
            print(f"  {exists} {p}")

    diag_files = summ.get("diagnostic_files", [])
    if diag_files:
        print(f"\n  Diagnostic files ({len(diag_files)})")
        for p in diag_files:
            exists = "[x]" if Path(p).exists() else "[ ]"
            qc_json = Path(p).with_suffix("").with_suffix("") .with_name(
                Path(p).stem.replace("_diagnostic", "") + "_qc.json"
            )
            qc_mark = " [qc]" if qc_json.exists() else ""
            print(f"  {exists} {p}{qc_mark}")

    print(f"\n{'='*60}\n")

    n_failed = summ.get("failed", 0)
    return 0 if n_failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate / inspect a climate agent run")
    parser.add_argument("--run-id", metavar="ID", default=None,
                        help="Run ID to inspect (default: latest)")
    parser.add_argument("--list", action="store_true",
                        help="List all available run IDs and exit")
    parser.add_argument("--checks", action="store_true",
                        help="Show detailed per-check validation breakdown table")
    parser.add_argument("--no-color", action="store_true",
                        help="Disable ANSI color output")
    args = parser.parse_args()

    if args.list:
        _list_runs()
        return 0

    run_id = args.run_id or _latest_run_id()
    if run_id is None:
        print("No runs found. Run the agent first.", file=sys.stderr)
        return 1

    manifest = _load_manifest(run_id)
    use_color = sys.stdout.isatty() and not args.no_color
    return _print_report(manifest, show_checks=args.checks, use_color=use_color)


if __name__ == "__main__":
    sys.exit(main())
