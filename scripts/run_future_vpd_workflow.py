#!/usr/bin/env python3
"""Compute daily future vapour pressure deficit from future tas and rh outputs."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
import sys
from time import perf_counter
from uuid import uuid4

import numpy as np
import xarray as xr

from run_projection_workflow import (
    COUNTRIES,
    DIAGNOSTIC_DIR,
    MERGED_DIR,
    WORKSPACE_ROOT,
    choose_time_index,
    ensure_path_exists,
    format_duration,
    normalize_selection,
    relpath,
    run_command,
    validate_output,
)


SCENARIOS = ("ssp_245", "ssp_585")
DEFAULT_START_YEAR = 2040
DEFAULT_END_YEAR = 2070
DEFAULT_MAX_WORKERS = 1
DEFAULT_COMPRESSION_LEVEL = 1
FAST_MODE_COMPRESSION_LEVEL = 0


def format_slice_label(country: str, scenario: str) -> str:
    return f"[{country} {scenario}]"


def log_slice_step(country: str, scenario: str, message: str) -> None:
    print(f"{format_slice_label(country, scenario)} {message}")


def build_netcdf_encoding(ds: xr.Dataset, compression_level: int) -> dict[str, dict[str, object]]:
    encoding: dict[str, dict[str, object]] = {}
    for var_name, var in ds.data_vars.items():
        if var.dtype.kind in {"f", "i", "u"}:
            if compression_level > 0:
                encoding[var_name] = {
                    "zlib": True,
                    "complevel": compression_level,
                    "shuffle": True,
                }
            else:
                encoding[var_name] = {"zlib": False}
    return encoding


def write_netcdf(ds: xr.Dataset, output_path: Path, compression_level: int) -> None:
    temp_path = output_path.with_name(f"{output_path.stem}.{uuid4().hex}.tmp.nc")
    ds.to_netcdf(temp_path, encoding=build_netcdf_encoding(ds, compression_level))
    temp_path.replace(output_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compute daily vapour pressure deficit for future scenarios from future tas and rh outputs "
            "for one or more countries and scenarios."
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
        "--start-year",
        type=int,
        default=DEFAULT_START_YEAR,
        help=f"Start year for the output period. Default: {DEFAULT_START_YEAR}.",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=DEFAULT_END_YEAR,
        help=f"End year for the output period. Default: {DEFAULT_END_YEAR}.",
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
        help="Number of country/scenario slices to run in parallel. Default: 1.",
    )
    parser.add_argument(
        "--fast-mode",
        action="store_true",
        help="Reduce compression and skip expensive grid validation checks for faster batch runs.",
    )
    return parser.parse_args()


def build_work_items(countries: list[str], scenarios: list[str]) -> list[tuple[str, str]]:
    return [(country, scenario) for country in countries for scenario in scenarios]


def get_compression_level(args: argparse.Namespace) -> int:
    if args.fast_mode:
        return FAST_MODE_COMPRESSION_LEVEL
    return DEFAULT_COMPRESSION_LEVEL


def detect_time_name(ds: xr.Dataset) -> str:
    for name in ("time", "valid_time"):
        if name in ds.coords:
            return name
    raise ValueError(f"Missing time coordinate. Found: {list(ds.coords)}")


def ensure_variable(ds: xr.Dataset, name: str) -> xr.DataArray:
    if name not in ds.data_vars:
        raise ValueError(f"Variable '{name}' missing from {list(ds.data_vars)}")
    return ds[name]


def format_year_list(years: np.ndarray) -> str:
    values = [str(int(year)) for year in years]
    if len(values) <= 6:
        return ", ".join(values)
    return ", ".join(values[:3] + ["..."] + values[-2:])


def ensure_year_coverage(
    ds: xr.Dataset,
    time_name: str,
    *,
    start_year: int,
    end_year: int,
    dataset_label: str,
) -> None:
    years = np.unique(np.asarray(ds[time_name].dt.year.values, dtype=int))
    expected_years = np.arange(start_year, end_year + 1, dtype=int)
    missing_years = expected_years[~np.isin(expected_years, years)]
    if missing_years.size == 0:
        return

    found_range = f"{int(years.min())}-{int(years.max())}" if years.size else "no years"
    raise ValueError(
        f"Incomplete requested year coverage for {dataset_label}: expected {start_year}-{end_year}, "
        f"found {found_range}, missing {format_year_list(missing_years)}"
    )


def is_already_daily_time_axis(ds: xr.Dataset, time_name: str) -> bool:
    if time_name not in ds.sizes or ds.sizes[time_name] <= 1:
        return True

    time_values = np.asarray(ds[time_name].values)
    if not np.issubdtype(time_values.dtype, np.datetime64):
        return False

    diffs = np.diff(time_values)
    one_day = np.timedelta64(1, "D")
    if diffs.size == 0 or np.any(diffs != one_day):
        return False

    return np.all(time_values == time_values.astype("datetime64[D]").astype(time_values.dtype))


def resample_to_daily_mean(ds: xr.Dataset, time_name: str) -> xr.Dataset:
    if is_already_daily_time_axis(ds, time_name):
        daily = ds.copy(deep=False)
        daily.attrs = dict(ds.attrs)
        daily.attrs["temporal_aggregation"] = str(ds.attrs.get("temporal_aggregation", "daily_mean"))
        daily.attrs["temporal_output_resolution"] = "daily"
        return daily

    daily = ds.resample({time_name: "1D"}).mean(keep_attrs=True, skipna=True)
    daily.attrs = dict(ds.attrs)
    daily.attrs["temporal_aggregation"] = "daily_mean"
    daily.attrs["temporal_output_resolution"] = "daily"
    return daily


def build_paths(country: str, scenario: str, start_year: int, end_year: int) -> dict[str, Path]:
    span_label = f"{start_year}_{end_year}"
    scenario_label = scenario.replace("_", "")

    if scenario == "ssp_245":
        rh_input = MERGED_DIR / f"{country}_rh_{scenario_label}_{span_label}_025deg_clipped.nc"
        tas_input = MERGED_DIR / f"{country}_tas_{scenario_label}_{span_label}_025deg_clipped.nc"
        output = MERGED_DIR / f"{country}_vpd_{scenario_label}_{span_label}_025deg_clipped.nc"
    else:
        rh_input = MERGED_DIR / f"{country}_rh_{scenario_label}_{span_label}_025deg_clipped.nc"
        tas_input = MERGED_DIR / f"{country}_tas_{scenario_label}_{span_label}_025deg_clipped.nc"
        output = MERGED_DIR / f"{country}_vpd_{scenario_label}_{span_label}_daily.nc"

    return {
        "rh_input": rh_input,
        "tas_input": tas_input,
        "output": output,
        "diagnostics": DIAGNOSTIC_DIR[country],
    }


def build_input_candidates(path: Path) -> list[Path]:
    repaired = path.with_name(f"{path.stem}_repaired{path.suffix}")
    candidates = [path, repaired]
    # Backward compatibility: if looking for 025deg_clipped.nc, also try the old daily.nc naming.
    if path.stem.endswith("_025deg_clipped"):
        old_stem = path.stem[: -len("_025deg_clipped")] + "_daily"
        old_daily = path.with_name(old_stem + path.suffix)
        candidates.append(old_daily)
        candidates.append(old_daily.with_name(f"{old_stem}_repaired{path.suffix}"))
    return candidates


def dataset_has_requested_year_coverage(path: Path, start_year: int, end_year: int) -> bool:
    with xr.open_dataset(path) as ds:
        time_name = detect_time_name(ds)
        ensure_year_coverage(
            ds,
            time_name,
            start_year=start_year,
            end_year=end_year,
            dataset_label=path.name,
        )
    return True


def resolve_input_path(path: Path, start_year: int, end_year: int) -> Path:
    first_existing: Path | None = None
    coverage_errors: list[str] = []

    for candidate in build_input_candidates(path):
        if not candidate.exists():
            continue
        if first_existing is None:
            first_existing = candidate
        try:
            dataset_has_requested_year_coverage(candidate, start_year, end_year)
            return candidate
        except ValueError as error:
            coverage_errors.append(str(error))

    if first_existing is not None:
        details = "; ".join(coverage_errors) if coverage_errors else "no candidate covered the requested period"
        raise ValueError(f"No valid input file found for {path.name}: {details}")

    raise FileNotFoundError(f"Expected input file was not found: {path}")


def compute_vpd_dataset(
    tas_ds: xr.Dataset,
    rh_ds: xr.Dataset,
    *,
    start_year: int,
    end_year: int,
    progress: callable | None = None,
) -> xr.Dataset:
    if progress is not None:
        progress("Resampling tas to daily mean...")
    tas_time = detect_time_name(tas_ds)
    tas_daily = resample_to_daily_mean(tas_ds, tas_time)

    if progress is not None:
        progress("Resampling rh to daily mean...")
    rh_time = detect_time_name(rh_ds)
    rh_daily = resample_to_daily_mean(rh_ds, rh_time)

    if tas_time != "time":
        tas_daily = tas_daily.rename({tas_time: "time"})
    if rh_time != "time":
        rh_daily = rh_daily.rename({rh_time: "time"})

    if progress is not None:
        progress("Checking requested year coverage...")
    ensure_year_coverage(
        tas_daily,
        "time",
        start_year=start_year,
        end_year=end_year,
        dataset_label="tas input",
    )
    ensure_year_coverage(
        rh_daily,
        "time",
        start_year=start_year,
        end_year=end_year,
        dataset_label="rh input",
    )

    if progress is not None:
        progress("Aligning daily tas and rh timestamps...")
    tas_data, rh_data = xr.align(ensure_variable(tas_daily, "tas"), ensure_variable(rh_daily, "rh"), join="inner")
    if tas_data.sizes.get("time", 0) == 0:
        raise ValueError("No overlapping daily timestamps between tas and rh datasets")

    # Tetens saturation vapor pressure over water, with VPD in hPa.
    if progress is not None:
        progress("Computing Tetens VPD...")
    saturation_vapor_pressure = 6.1078 * np.exp((17.27 * tas_data) / (tas_data + 237.3))
    vpd = (saturation_vapor_pressure * (1.0 - (rh_data / 100.0))).astype(np.float32)
    vpd.name = "vpd"
    vpd.attrs = {
        "long_name": "Vapour Pressure Deficit",
        "units": "hPa",
        "formula": "6.1078 * exp((17.27 * tas) / (tas + 237.3)) * (1 - rh / 100)",
        "tas_units": str(tas_data.attrs.get("units", "")),
        "rh_units": str(rh_data.attrs.get("units", "")),
        "storage_dtype": "float32",
    }

    output_ds = vpd.to_dataset()
    output_ds.attrs = dict(tas_ds.attrs)
    output_ds.attrs["derived_from"] = "tas,rh"
    output_ds.attrs["temporal_resolution"] = "daily"
    if progress is not None:
        progress("Checking aligned output coverage...")
    ensure_year_coverage(
        output_ds,
        "time",
        start_year=start_year,
        end_year=end_year,
        dataset_label="aligned tas/rh overlap",
    )
    return output_ds


def run_diagnostics(output_path: Path, diagnostics_dir: Path, preferred_index: int, dry_run: bool) -> None:
    time_index = choose_time_index(output_path, preferred_index)
    command = [
        sys.executable,
        relpath(WORKSPACE_ROOT / "codes" / "diagnose_final_netcdf.py"),
        "--file",
        relpath(output_path),
        "--var",
        "vpd",
        "--time-index",
        str(time_index),
        "--out-dir",
        relpath(diagnostics_dir),
    ]
    run_command(command, dry_run=dry_run)
    if dry_run:
        return
    ensure_path_exists(diagnostics_dir / f"{output_path.stem}_diagnostic.png")


def process_one(country: str, scenario: str, args: argparse.Namespace) -> None:
    started = perf_counter()
    compression_level = get_compression_level(args)
    paths = build_paths(country, scenario, args.start_year, args.end_year)
    rh_input = resolve_input_path(paths["rh_input"], args.start_year, args.end_year)
    tas_input = resolve_input_path(paths["tas_input"], args.start_year, args.end_year)

    print(f"\n=== {country} {scenario} vpd ===")
    log_slice_step(country, scenario, "Checking input files...")
    ensure_path_exists(rh_input)
    ensure_path_exists(tas_input)

    if rh_input != paths["rh_input"]:
        log_slice_step(country, scenario, f"Using repaired RH input {relpath(rh_input)}")
    if tas_input != paths["tas_input"]:
        log_slice_step(country, scenario, f"Using repaired TAS input {relpath(tas_input)}")

    if args.dry_run:
        print(f"Would compute VPD from {relpath(tas_input)} and {relpath(rh_input)}")
        print(f"Would write {relpath(paths['output'])}")
        return

    log_slice_step(country, scenario, "Opening inputs...")
    with xr.open_dataset(tas_input) as tas_ds, xr.open_dataset(rh_input) as rh_ds:
        output_ds = compute_vpd_dataset(
            tas_ds,
            rh_ds,
            start_year=args.start_year,
            end_year=args.end_year,
            progress=lambda message: log_slice_step(country, scenario, message),
        )

    paths["output"].parent.mkdir(parents=True, exist_ok=True)
    log_slice_step(country, scenario, f"Writing output to {relpath(paths['output'])}...")
    write_netcdf(output_ds, paths["output"], compression_level)
    print(f"Wrote output file: {paths['output']}")

    log_slice_step(country, scenario, "Validating output...")
    validate_output(
        paths["output"],
        var_name="vpd",
        expected_units="hPa",
        start_year=args.start_year,
        end_year=args.end_year,
        target_grid_path=None if args.fast_mode else tas_input,
        require_grid_match=not args.fast_mode,
        require_daily_axis=True,
    )

    if args.run_diagnostics:
        log_slice_step(country, scenario, "Running diagnostics step...")
        run_diagnostics(paths["output"], paths["diagnostics"], args.diagnostic_time_index, args.dry_run)

    print(f"Workflow slice completed in {format_duration(perf_counter() - started)}")


def process_work_item(work_item: tuple[str, str], args: argparse.Namespace) -> None:
    country, scenario = work_item
    process_one(country, scenario, args)


def main() -> None:
    args = parse_args()
    if args.max_workers < 1:
        raise ValueError("--max-workers must be at least 1")
    if args.start_year > args.end_year:
        raise ValueError("--start-year must be less than or equal to --end-year")

    countries = normalize_selection(args.country, COUNTRIES)
    scenarios = normalize_selection(args.scenario, SCENARIOS, aliases={"ssp245": "ssp_245", "ssp585": "ssp_585"})
    work_items = build_work_items(countries, scenarios)
    max_workers = min(args.max_workers, len(work_items))

    if max_workers == 1:
        for work_item in work_items:
            process_work_item(work_item, args)
    else:
        print(f"Running {len(work_items)} future VPD workflow slices with {max_workers} workers.")
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(process_work_item, work_item, args): work_item for work_item in work_items}
            for future in as_completed(futures):
                country, scenario = futures[future]
                try:
                    future.result()
                except Exception as error:
                    raise RuntimeError(f"Future VPD workflow slice failed for {country} {scenario}") from error

    print("\nFuture VPD workflow completed successfully.")


if __name__ == "__main__":
    main()