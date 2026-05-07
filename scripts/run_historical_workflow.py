#!/usr/bin/env python3
"""Run historical 2010-2025 workflows for merged, regridded, and clipped NetCDF outputs."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import sys

from run_projection_workflow import (
    BOUNDARY_DIR,
    COUNTRIES,
    DATA_DIR,
    MERGED_DIR,
    WORKSPACE_ROOT,
    choose_time_index,
    ensure_path_exists,
    normalize_selection,
    relpath,
    run_command,
    validate_output,
)


PERIOD_LABEL = "2010_2025"
DEFAULT_START_YEAR = 2010
DEFAULT_END_YEAR = 2025
DEFAULT_MAX_WORKERS = 1
DEFAULT_INTERMEDIATE_COMPRESSION = 0
DEFAULT_FINAL_COMPRESSION = 1
FAST_MODE_COMPRESSION = 0
DIAGNOSTIC_DIR = {
    "ethiopia": DATA_DIR / "merged_files_et" / "diagnostics",
    "kenya": DATA_DIR / "merged_files_ke" / "diagnostics",
    "somalia": DATA_DIR / "merged_files_so" / "diagnostics",
}
VARIABLES = ("pr", "rh", "temp", "vpd")
VARIABLE_CONFIG = {
    "pr": {
        "source_name": "precip",
        "final_var_name": "precip",
        "expected_units": "mm/day",
        "rename_args": [],
        "requires_merge": False,
    },
    "rh": {
        "source_name": "Relative_Humidity_2m_06h",
        "final_var_name": "rh",
        "expected_units": None,
        "rename_args": [],
        "requires_merge": True,
    },
    "temp": {
        "source_name": "Temperature_Air_2m_Mean_24h",
        "final_var_name": "t2m",
        "expected_units": None,
        "rename_args": [],
        "requires_merge": True,
    },
    "vpd": {
        "source_name": "Vapour_Pressure_Deficit_at_Maximum_Temperature",
        "final_var_name": "vpd",
        "expected_units": None,
        "rename_args": [],
        "requires_merge": True,
    },
}
MERGE_SCRIPT = {
    ("ethiopia", "rh"): "merge_netcdf_ethiopia_relative_humidity.py",
    ("ethiopia", "temp"): "merge_netcdf_ethiopia_temperature.py",
    ("ethiopia", "vpd"): "merge_netcdf_ethiopia_vapour_pressure_deficit.py",
    ("kenya", "rh"): "merge_netcdf_kenya_relative_humidity.py",
    ("kenya", "temp"): "merge_netcdf_kenya_temperature.py",
    ("kenya", "vpd"): "merge_netcdf_kenya_vapour_pressure_deficit.py",
    ("somalia", "rh"): "merge_netcdf_somalia_relative_humidity_mean.py",
    ("somalia", "temp"): "merge_netcdf_somalia_temperature.py",
    ("somalia", "vpd"): "merge_netcdf_somalia_vapour_pressure_deficit.py",
}
MERGE_INPUT_DIR = {
    "rh": "relative_humidity_mean",
    "temp": "temperature",
    "vpd": "vapour_pressure_deficit",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the historical 2010-2025 merge, regrid, clip, and validation workflow "
            "for one or more country/variable combinations."
        )
    )
    parser.add_argument(
        "--country",
        nargs="+",
        default=["all"],
        help="Country name(s): ethiopia, kenya, somalia, or all.",
    )
    parser.add_argument(
        "--variable",
        nargs="+",
        default=["all"],
        help="Variable name(s): pr, rh, temp, vpd, or all.",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=DEFAULT_START_YEAR,
        help=f"Start year for validation. Default: {DEFAULT_START_YEAR}.",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=DEFAULT_END_YEAR,
        help=f"End year for validation. Default: {DEFAULT_END_YEAR}.",
    )
    parser.add_argument(
        "--method",
        default="linear",
        choices=["linear", "nearest"],
        help="Spatial interpolation method used for regridding. Default: linear.",
    )
    parser.add_argument(
        "--diagnostic-time-index",
        type=int,
        default=0,
        help="Preferred time index for QA plots; capped to the dataset length.",
    )
    diagnostics_group = parser.add_mutually_exclusive_group()
    diagnostics_group.add_argument(
        "--run-diagnostics",
        dest="run_diagnostics",
        action="store_true",
        help="Run diagnose_final_netcdf.py after validation.",
    )
    diagnostics_group.add_argument(
        "--skip-diagnostics",
        dest="run_diagnostics",
        action="store_false",
        help="Deprecated compatibility flag. Diagnostics are skipped by default.",
    )
    parser.set_defaults(run_diagnostics=False)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without executing them.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=DEFAULT_MAX_WORKERS,
        help="Number of country/variable slices to run in parallel. Default: 1.",
    )
    parser.add_argument(
        "--fast-mode",
        action="store_true",
        help=(
            "Reduce compression and skip expensive target-grid and daily-axis validation checks "
            "for faster batch runs."
        ),
    )
    parser.add_argument(
        "--skip-merge",
        action="store_true",
        help="Reuse existing merged historical files in data/merged_files instead of rerunning merge scripts.",
    )
    return parser.parse_args()


def build_work_items(countries: list[str], variables: list[str]) -> list[tuple[str, str]]:
    return [(country, variable) for country in countries for variable in variables]


def get_compression_levels(args: argparse.Namespace) -> tuple[int, int]:
    if args.fast_mode:
        return FAST_MODE_COMPRESSION, FAST_MODE_COMPRESSION
    return DEFAULT_INTERMEDIATE_COMPRESSION, DEFAULT_FINAL_COMPRESSION


def build_paths(country: str, variable: str) -> dict[str, Path]:
    raw_output = MERGED_DIR / f"{country}_{variable}_{PERIOD_LABEL}.nc"
    clipped_output = MERGED_DIR / f"{country}_{variable}_{PERIOD_LABEL}_025deg_clipped.nc"
    target_grid = MERGED_DIR / f"{country}_pr_{PERIOD_LABEL}.nc"
    boundary = BOUNDARY_DIR / f"{country}_adm0.geojson"

    if variable == "pr":
        processed_output = raw_output
        merge_input_dir = None
        merge_script = None
    else:
        processed_output = MERGED_DIR / f"{country}_{variable}_{PERIOD_LABEL}_025deg.nc"
        merge_input_dir = DATA_DIR / f"{country}_{MERGE_INPUT_DIR[variable]}" / "netcdf"
        merge_script = WORKSPACE_ROOT / "codes" / MERGE_SCRIPT[(country, variable)]

    return {
        "raw_output": raw_output,
        "processed_output": processed_output,
        "clipped_output": clipped_output,
        "target_grid": target_grid,
        "boundary": boundary,
        "diagnostics": DIAGNOSTIC_DIR[country],
        "merge_input_dir": merge_input_dir,
        "merge_script": merge_script,
    }


def run_diagnostics(output_path: Path, var_name: str, diagnostics_dir: Path, preferred_index: int, dry_run: bool) -> None:
    time_index = choose_time_index(output_path, preferred_index)
    command = [
        sys.executable,
        relpath(WORKSPACE_ROOT / "codes" / "diagnose_final_netcdf.py"),
        "--file",
        relpath(output_path),
        "--var",
        var_name,
        "--time-index",
        str(time_index),
        "--out-dir",
        relpath(diagnostics_dir),
    ]
    run_command(command, dry_run=dry_run)
    if dry_run:
        return
    ensure_path_exists(diagnostics_dir / f"{output_path.stem}_diagnostic.png")


def process_one(country: str, variable: str, args: argparse.Namespace) -> None:
    config = VARIABLE_CONFIG[variable]
    paths = build_paths(country, variable)
    intermediate_compression, final_compression = get_compression_levels(args)

    print(f"\n=== {country} historical {variable} ===")

    if config["requires_merge"]:
        if args.skip_merge:
            print("Skipping merge step and reusing existing merged file...")
        else:
            merge_command = [
                sys.executable,
                relpath(paths["merge_script"]),
                "--input-dir",
                relpath(paths["merge_input_dir"]),
                "--output",
                relpath(paths["raw_output"]),
            ]
            print("Running merge step...")
            run_command(merge_command, dry_run=args.dry_run)

        if not args.dry_run:
            ensure_path_exists(paths["raw_output"])
            validate_output(
                paths["raw_output"],
                var_name=config["source_name"],
                expected_units=None,
                start_year=args.start_year,
                end_year=args.end_year,
            )
    else:
        if not args.dry_run:
            ensure_path_exists(paths["raw_output"])
            validate_output(
                paths["raw_output"],
                var_name=config["source_name"],
                expected_units=config["expected_units"],
                start_year=args.start_year,
                end_year=args.end_year,
            )

    processed_output = paths["processed_output"]
    if variable != "pr":
        rename_command = [
            sys.executable,
            relpath(WORKSPACE_ROOT / "codes" / "rename_and_regrid_netcdf.py"),
            "--source",
            relpath(paths["raw_output"]),
            "--target-grid",
            relpath(paths["target_grid"]),
            "--output",
            relpath(processed_output),
            "--method",
            args.method,
            "--compression-level",
            str(intermediate_compression),
        ]
        rename_command.extend(config["rename_args"])
        print("Running rename/regrid step...")
        run_command(rename_command, dry_run=args.dry_run)
        if not args.dry_run:
            ensure_path_exists(processed_output)
            validate_output(
                processed_output,
                var_name=config["final_var_name"],
                expected_units=config["expected_units"],
                start_year=args.start_year,
                end_year=args.end_year,
                target_grid_path=None if args.fast_mode else paths["target_grid"],
                require_grid_match=not args.fast_mode,
            )

    clip_input = processed_output
    clip_command = [
        sys.executable,
        relpath(WORKSPACE_ROOT / "codes" / "clip_netcdf_by_shapefile.py"),
        "--input",
        relpath(clip_input),
        "--boundary",
        relpath(paths["boundary"]),
        "--output",
        relpath(paths["clipped_output"]),
        "--compression-level",
        str(final_compression),
    ]
    print("Running clip step...")
    run_command(clip_command, dry_run=args.dry_run)

    if not args.dry_run:
        ensure_path_exists(paths["clipped_output"])
        validate_output(
            paths["clipped_output"],
            var_name=config["final_var_name"],
            expected_units=config["expected_units"],
            start_year=args.start_year,
            end_year=args.end_year,
            target_grid_path=None if args.fast_mode else paths["target_grid"],
            require_within_target_bounds=not args.fast_mode,
        )

    if args.run_diagnostics:
        print("Running diagnostics step...")
        run_diagnostics(
            output_path=paths["clipped_output"],
            var_name=config["final_var_name"],
            diagnostics_dir=paths["diagnostics"],
            preferred_index=args.diagnostic_time_index,
            dry_run=args.dry_run,
        )


def process_work_item(work_item: tuple[str, str], args: argparse.Namespace) -> None:
    country, variable = work_item
    process_one(country, variable, args)


def main() -> None:
    args = parse_args()
    if args.max_workers < 1:
        raise ValueError("--max-workers must be at least 1")
    if args.start_year > args.end_year:
        raise ValueError("--start-year must be less than or equal to --end-year")

    countries = normalize_selection(args.country, COUNTRIES)
    variables = normalize_selection(args.variable, VARIABLES)
    work_items = build_work_items(countries, variables)
    max_workers = min(args.max_workers, len(work_items))

    if max_workers == 1:
        for work_item in work_items:
            process_work_item(work_item, args)
    else:
        print(f"Running {len(work_items)} historical workflow slices with {max_workers} workers.")
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(process_work_item, work_item, args): work_item
                for work_item in work_items
            }
            for future in as_completed(futures):
                country, variable = futures[future]
                try:
                    future.result()
                except Exception as error:
                    raise RuntimeError(
                        f"Historical workflow slice failed for {country} {variable}"
                    ) from error

    print("\nHistorical workflow completed successfully.")


if __name__ == "__main__":
    main()