#!/usr/bin/env python3
"""Run ISIMIP projection workflows step by step and validate outputs."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
import subprocess
import sys
from time import perf_counter
from pathlib import Path
from typing import Iterable

import numpy as np
import xarray as xr


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
CODES_DIR = WORKSPACE_ROOT / "codes"
DATA_DIR = WORKSPACE_ROOT / "data"
MERGED_DIR = DATA_DIR / "merged_files"
PROJECTION_DIR = DATA_DIR / "projection_data"
BOUNDARY_DIR = DATA_DIR / "boundaries"

COUNTRIES = ("ethiopia", "kenya", "somalia")
SCENARIOS = ("ssp_245", "ssp_585")
VARIABLES = ("rh", "pr", "tas")
SOURCE_SPAN = {"ssp_245": "2031_2070", "ssp_585": "2036_2070"}
CLIP_SPAN = "2040_2070"
DIAGNOSTIC_DIR = {
    "ethiopia": DATA_DIR / "merged_files_et" / "diagnostics",
    "kenya": DATA_DIR / "merged_files_ke" / "diagnostics",
    "somalia": DATA_DIR / "merged_files_so" / "diagnostics",
}
VARIABLE_CONFIG = {
    "rh": {
        "source_name": "hurs",
        "var_name": "rh",
        "rename_args": [],
        "daily_agg": {"ssp_245": None, "ssp_585": "mean"},
        "expected_units": None,
    },
    "pr": {
        "source_name": "pr",
        "var_name": "pr",
        "rename_args": ["--convert-pr-to-mm-day"],
        "daily_agg": {"ssp_245": None, "ssp_585": "sum"},
        "expected_units": "mm/day",
    },
    "tas": {
        "source_name": "tas",
        "var_name": "tas",
        "rename_args": ["--convert-kelvin-to-celsius"],
        "daily_agg": {"ssp_245": None, "ssp_585": "mean"},
        "expected_units": "degC",
    },
}
INTERMEDIATE_COMPRESSION_LEVEL = 0
FINAL_COMPRESSION_LEVEL = 1
DEFAULT_MAX_WORKERS = 1
FAST_MODE_COMPRESSION_LEVEL = 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run the corrected projection-processing workflow for one or more country/"
            "scenario/variable combinations, validating outputs after each step."
        )
    )
    parser.add_argument(
        "--country",
        nargs="+",
        default=["all"],
        help="Country name(s): ethiopia, kenya, somalia, or all.",
    )
    parser.add_argument(
        "--scenario",
        nargs="+",
        default=["all"],
        help="Scenario name(s): ssp_245, ssp245, ssp_585, ssp585, or all.",
    )
    parser.add_argument(
        "--variable",
        nargs="+",
        default=["all"],
        help="Variable name(s): rh, pr, tas, or all.",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=2040,
        help="Start year for the clipped period. Default: 2040.",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=2070,
        help="End year for the clipped period. Default: 2070.",
    )
    parser.add_argument(
        "--method",
        default="linear",
        choices=["linear", "nearest"],
        help="Spatial interpolation method. Default: linear.",
    )
    parser.add_argument(
        "--diagnostic-time-index",
        type=int,
        default=6416,
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
        help="Number of country/scenario/variable slices to run in parallel. Default: 1.",
    )
    parser.add_argument(
        "--fast-mode",
        action="store_true",
        help=(
            "Reduce compression and skip expensive grid-shape and daily-axis validation checks "
            "for faster batch runs."
        ),
    )
    return parser.parse_args()


def normalize_selection(values: Iterable[str], allowed: tuple[str, ...], aliases: dict[str, str] | None = None) -> list[str]:
    aliases = aliases or {}
    normalized = []
    for value in values:
        key = aliases.get(value.lower(), value.lower())
        if key == "all":
            return list(allowed)
        if key not in allowed:
            raise ValueError(f"Unsupported selection '{value}'. Allowed: {allowed} or all")
        normalized.append(key)
    return list(dict.fromkeys(normalized))


def build_work_items(
    countries: Iterable[str],
    scenarios: Iterable[str],
    variables: Iterable[str],
) -> list[tuple[str, str, str]]:
    return [
        (country, scenario, variable)
        for country in countries
        for scenario in scenarios
        for variable in variables
    ]


def relpath(path: Path) -> str:
    return path.relative_to(WORKSPACE_ROOT).as_posix()


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.2f}s"
    minutes, remainder = divmod(seconds, 60)
    return f"{int(minutes)}m {remainder:.1f}s"


def get_compression_levels(args: argparse.Namespace) -> tuple[int, int]:
    if args.fast_mode:
        return FAST_MODE_COMPRESSION_LEVEL, FAST_MODE_COMPRESSION_LEVEL
    return INTERMEDIATE_COMPRESSION_LEVEL, FINAL_COMPRESSION_LEVEL


def run_command(command: list[str], *, dry_run: bool) -> float:
    printable = " ".join(command)
    print(f"$ {printable}")
    if dry_run:
        return 0.0
    started = perf_counter()
    subprocess.run(command, cwd=WORKSPACE_ROOT, check=True)
    elapsed = perf_counter() - started
    print(f"Completed in {format_duration(elapsed)}")
    return elapsed


def detect_coord_name(ds: xr.Dataset, candidates: tuple[str, ...]) -> str:
    for name in candidates:
        if name in ds.coords:
            return name
    raise ValueError(f"Missing coordinate from {candidates}. Found: {list(ds.coords)}")


def detect_time_name(ds: xr.Dataset) -> str:
    return detect_coord_name(ds, ("time", "valid_time"))


def ensure_path_exists(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"Expected output was not written: {path}")


def ensure_variable(ds: xr.Dataset, var_name: str) -> xr.DataArray:
    if var_name not in ds.data_vars:
        raise ValueError(f"Variable '{var_name}' missing from {list(ds.data_vars)}")
    return ds[var_name]


def assert_non_empty(ds: xr.Dataset, var_name: str) -> None:
    data = ensure_variable(ds, var_name)
    if any(size == 0 for size in ds.sizes.values()):
        raise ValueError(f"Dataset has an empty dimension: {dict(ds.sizes)}")
    finite_count = int(data.count().item())
    if finite_count == 0:
        raise ValueError(f"Variable '{var_name}' contains no finite values")


def validate_output(
    output_path: Path,
    *,
    var_name: str,
    expected_units: str | None,
    start_year: int,
    end_year: int,
    target_grid_path: Path | None = None,
    require_grid_match: bool = False,
    require_within_target_bounds: bool = False,
    require_daily_axis: bool = False,
) -> None:
    with ExitStack() as stack:
        ds = stack.enter_context(xr.open_dataset(output_path))
        target = None
        if target_grid_path is not None:
            target = stack.enter_context(xr.open_dataset(target_grid_path))

        assert_non_empty(ds, var_name)

        if expected_units is not None:
            units = str(ensure_variable(ds, var_name).attrs.get("units", "")).strip()
            if units != expected_units:
                raise ValueError(f"Unexpected units for {output_path.name}: '{units}' != '{expected_units}'")

        time_name = detect_time_name(ds)
        years = ds[time_name].dt.year.values
        if years.min() < start_year or years.max() > end_year:
            raise ValueError(
                f"Time range mismatch for {output_path.name}: {int(years.min())}-{int(years.max())}"
            )

        if require_daily_axis:
            values = ds[time_name].values
            if values.size >= 2:
                deltas = np.diff(values).astype("timedelta64[D]")
                if not np.all(deltas == np.timedelta64(1, "D")):
                    raise ValueError(f"Time axis is not daily for {output_path.name}")

        if target is None:
            return

        out_lat = detect_coord_name(ds, ("lat", "latitude"))
        out_lon = detect_coord_name(ds, ("lon", "longitude"))
        tgt_lat = detect_coord_name(target, ("lat", "latitude"))
        tgt_lon = detect_coord_name(target, ("lon", "longitude"))

        if require_grid_match:
            if ds.sizes[out_lat] != target.sizes[tgt_lat] or ds.sizes[out_lon] != target.sizes[tgt_lon]:
                raise ValueError(
                    f"Grid mismatch for {output_path.name}: {dict(ds.sizes)} vs target {dict(target.sizes)}"
                )

            if not np.allclose(ds[out_lat].values, target[tgt_lat].values):
                raise ValueError(f"Latitude coordinates do not match target grid for {output_path.name}")
            if not np.allclose(ds[out_lon].values, target[tgt_lon].values):
                raise ValueError(f"Longitude coordinates do not match target grid for {output_path.name}")

        if require_within_target_bounds:
            if ds.sizes[out_lat] > target.sizes[tgt_lat] or ds.sizes[out_lon] > target.sizes[tgt_lon]:
                raise ValueError(f"Clipped file exceeds target grid size for {output_path.name}")

            lat_values = np.asarray(ds[out_lat].values, dtype=float)
            lon_values = np.asarray(ds[out_lon].values, dtype=float)
            target_lat = np.asarray(target[tgt_lat].values, dtype=float)
            target_lon = np.asarray(target[tgt_lon].values, dtype=float)

            if lat_values.min() < target_lat.min() or lat_values.max() > target_lat.max():
                raise ValueError(f"Latitude bounds fall outside target grid for {output_path.name}")
            if lon_values.min() < target_lon.min() or lon_values.max() > target_lon.max():
                raise ValueError(f"Longitude bounds fall outside target grid for {output_path.name}")


def choose_time_index(output_path: Path, preferred_index: int) -> int:
    with xr.open_dataset(output_path) as ds:
        time_name = detect_time_name(ds)
        time_len = ds.sizes[time_name]
    return max(0, min(preferred_index, time_len - 1))


def build_paths(country: str, scenario: str, variable: str, start_year: int, end_year: int) -> dict[str, Path]:
    scenario_label = scenario.replace("_", "")
    source_span = SOURCE_SPAN[scenario]
    clip_span = f"{start_year}_{end_year}"
    prefix = f"{country}_{variable}_{scenario_label}"
    target_grid = MERGED_DIR / f"{country}_pr_2010_2025.nc"
    source_dir = PROJECTION_DIR / f"isimip-download-{country}" / scenario / VARIABLE_CONFIG[variable]["source_name"]
    boundary = BOUNDARY_DIR / f"{country}_adm0.geojson"
    diagnostics = DIAGNOSTIC_DIR[country]

    if scenario == "ssp_585" and variable == "pr":
        processed = MERGED_DIR / f"{prefix}_{clip_span}_daily.nc"
        clipped_time = processed
        clipped_boundary = MERGED_DIR / f"{prefix}_{clip_span}_daily_clipped.nc"
        daily = clipped_boundary
        preclip_daily = processed
    elif scenario == "ssp_585":
        processed = MERGED_DIR / f"{prefix}_{clip_span}_025deg.nc"
        clipped_time = processed
        clipped_boundary = MERGED_DIR / f"{prefix}_{clip_span}_025deg_clipped.nc"
        daily = MERGED_DIR / f"{prefix}_{clip_span}_daily.nc"
        preclip_daily = MERGED_DIR / f"{prefix}_{clip_span}_daily_full.nc"
    else:
        processed = MERGED_DIR / f"{prefix}_{clip_span}_025deg.nc"
        clipped_time = processed
        clipped_boundary = MERGED_DIR / f"{prefix}_{clip_span}_025deg_clipped.nc"
        daily = clipped_boundary
        preclip_daily = processed

    return {
        "source_dir": source_dir,
        "target_grid": target_grid,
        "boundary": boundary,
        "diagnostics": diagnostics,
        "processed": processed,
        "clipped_time": clipped_time,
        "clipped_boundary": clipped_boundary,
        "daily": daily,
        "preclip_daily": preclip_daily,
    }


def run_diagnostics(output_path: Path, var_name: str, diagnostics_dir: Path, preferred_index: int, dry_run: bool) -> None:
    time_index = choose_time_index(output_path, preferred_index)
    command = [
        sys.executable,
        relpath(CODES_DIR / "diagnose_final_netcdf.py"),
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
    png_path = diagnostics_dir / f"{output_path.stem}_diagnostic.png"
    ensure_path_exists(png_path)


def process_one(country: str, scenario: str, variable: str, args: argparse.Namespace) -> None:
    config = VARIABLE_CONFIG[variable]
    paths = build_paths(country, scenario, variable, args.start_year, args.end_year)
    expected_units = config["expected_units"]
    daily_agg = config["daily_agg"][scenario]
    intermediate_compression, final_compression = get_compression_levels(args)
    workflow_started = perf_counter()

    print(f"\n=== {country} {scenario} {variable} ===")

    rename_output = paths["processed"]

    rename_command = [
        sys.executable,
        relpath(CODES_DIR / "rename_and_regrid_netcdf.py"),
        "--source",
        relpath(paths["source_dir"]),
        "--target-grid",
        relpath(paths["target_grid"]),
        "--output",
        relpath(rename_output),
        "--method",
        args.method,
        "--start-year",
        str(args.start_year),
        "--end-year",
        str(args.end_year),
        "--compression-level",
        str(intermediate_compression),
    ]
    rename_command.extend(config["rename_args"])
    if daily_agg is not None:
        rename_command.extend(["--aggregate-daily", "--daily-agg", daily_agg])

    print("Running rename/regrid step...")
    run_command(rename_command, dry_run=args.dry_run)
    if not args.dry_run:
        ensure_path_exists(rename_output)
        validation_started = perf_counter()
        validate_output(
            rename_output,
            var_name=config["var_name"],
            expected_units=expected_units,
            start_year=args.start_year,
            end_year=args.end_year,
            target_grid_path=None if args.fast_mode else paths["target_grid"],
            require_grid_match=not args.fast_mode,
            require_daily_axis=daily_agg is not None and not args.fast_mode,
        )
        print(f"Validated rename/regrid output in {format_duration(perf_counter() - validation_started)}")

    clip_shape_command = [
        sys.executable,
        relpath(CODES_DIR / "clip_netcdf_by_shapefile.py"),
        "--input",
        relpath(rename_output),
        "--boundary",
        relpath(paths["boundary"]),
        "--output",
        relpath(paths["clipped_boundary"]),
        "--compression-level",
        str(final_compression),
    ]
    print("Running clip step...")
    run_command(clip_shape_command, dry_run=args.dry_run)

    clipped_output = paths["clipped_boundary"]
    if not args.dry_run:
        ensure_path_exists(clipped_output)
        validation_started = perf_counter()
        validate_output(
            clipped_output,
            var_name=config["var_name"],
            expected_units=expected_units,
            start_year=args.start_year,
            end_year=args.end_year,
            target_grid_path=None if args.fast_mode else paths["target_grid"],
            require_within_target_bounds=not args.fast_mode,
            require_daily_axis=daily_agg is not None and not args.fast_mode,
        )
        print(f"Validated clipped output in {format_duration(perf_counter() - validation_started)}")

    final_output = clipped_output

    if args.run_diagnostics:
        print("Running diagnostics step...")
        run_diagnostics(
            output_path=final_output,
            var_name=config["var_name"],
            diagnostics_dir=paths["diagnostics"],
            preferred_index=args.diagnostic_time_index,
            dry_run=args.dry_run,
        )

    if not args.dry_run:
        print(f"Workflow slice completed in {format_duration(perf_counter() - workflow_started)}")


def process_work_item(work_item: tuple[str, str, str], args: argparse.Namespace) -> None:
    country, scenario, variable = work_item
    process_one(country, scenario, variable, args)


def main() -> None:
    args = parse_args()
    if args.max_workers < 1:
        raise ValueError("--max-workers must be at least 1")

    countries = normalize_selection(args.country, COUNTRIES)
    scenarios = normalize_selection(
        args.scenario,
        SCENARIOS,
        aliases={"ssp245": "ssp_245", "ssp585": "ssp_585"},
    )
    variables = normalize_selection(args.variable, VARIABLES)

    work_items = build_work_items(countries, scenarios, variables)
    max_workers = min(args.max_workers, len(work_items))

    if max_workers == 1:
        for work_item in work_items:
            process_work_item(work_item, args)
    else:
        print(f"Running {len(work_items)} workflow slices with {max_workers} workers.")
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(process_work_item, work_item, args): work_item
                for work_item in work_items
            }
            for future in as_completed(futures):
                country, scenario, variable = futures[future]
                try:
                    future.result()
                except Exception as error:
                    raise RuntimeError(
                        f"Workflow slice failed for {country} {scenario} {variable}"
                    ) from error

    print("\nWorkflow completed successfully.")


if __name__ == "__main__":
    main()