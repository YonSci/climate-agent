#!/usr/bin/env python3
"""Rename NetCDF variable names and optionally regrid to a target grid."""

from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
from pathlib import Path
import time
from typing import Iterator
from uuid import uuid4

import xarray as xr


RENAME_MAP = {
    "Vapour_Pressure_Deficit_at_Maximum_Temperature": "vpd",
    "Temperature_Air_2m_Mean_24h": "t2m",
    "Relative_Humidity_2m_06h": "rh",
    "hurs": "rh",
}

PR_FLUX_UNITS = {"kg m-2 s-1", "kg m^-2 s^-1", "kg/m^2/s"}
PR_HOURLY_UNITS = {
    "mm per 1 hour",
    "mm/hour",
    "mm/hr",
    "mm h-1",
    "mm hr-1",
}
KELVIN_UNITS = {"k", "kelvin", "degree_kelvin", "degrees_kelvin"}
INTERP_CHUNK_LENGTH = 720
DEFAULT_TIME_CANDIDATES = ("time", "valid_time")
DAILY_AGG_CHOICES = ("mean", "sum", "min", "max", "first", "last")
LINEAR_DAILY_AGGREGATIONS = {"mean", "sum"}


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

    last_error: PermissionError | None = None
    for _ in range(5):
        try:
            temp_path.replace(output_path)
            return
        except PermissionError as error:
            last_error = error
            time.sleep(1)

    try:
        temp_path.unlink(missing_ok=True)
    except PermissionError:
        pass

    if last_error is not None:
        raise last_error


def clip_dataset_by_year(ds: xr.Dataset, time_name: str, start_year: int, end_year: int) -> xr.Dataset:
    years = ds[time_name].dt.year
    mask = (years >= start_year) & (years <= end_year)
    clipped = ds.where(mask, drop=True)

    if clipped.sizes.get(time_name, 0) == 0:
        raise ValueError(
            f"No time values found between {start_year} and {end_year} in coordinate '{time_name}'."
        )

    return clipped


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Rename known climate variable names (vpd/t2m/rh) and optionally regrid "
            "a source NetCDF to match a target grid. Optionally convert pr from "
            "kg m-2 s-1 to mm/day and temperature variables from Kelvin to degC."
        )
    )
    parser.add_argument(
        "--source",
        default="data/merged_files/ethiopia_rh_2010_2025.nc",
        help="Input NetCDF file or directory containing NetCDF files to process.",
    )
    parser.add_argument(
        "--output",
        default="data/merged_files/ethiopia_rh_2010_2025_025deg.nc",
        help="Output NetCDF file path.",
    )
    parser.add_argument(
        "--target-grid",
        default="data/merged_files/ethiopia_pr_2010_2025.nc",
        help=(
            "NetCDF file that provides the target grid coordinates. "
            "If omitted, only renaming is applied."
        ),
    )
    parser.add_argument(
        "--method",
        default="linear",
        choices=["linear", "nearest"],
        help="Interpolation method for regridding.",
    )
    parser.add_argument(
        "--rename-only",
        action="store_true",
        help="Only rename variables and skip regridding.",
    )
    parser.add_argument(
        "--convert-pr-to-mm-day",
        action="store_true",
        help=(
            "Convert precipitation variable 'pr' from kg m-2 s-1 to mm/day "
            "by multiplying by 86400."
        ),
    )
    parser.add_argument(
        "--convert-kelvin-to-celsius",
        action="store_true",
        help=(
            "Convert any data variable with Kelvin units to degrees Celsius "
            "by subtracting 273.15."
        ),
    )
    parser.add_argument(
        "--aggregate-daily",
        action="store_true",
        help="Aggregate the result from hourly to daily resolution before writing output.",
    )
    parser.add_argument(
        "--daily-agg",
        default="mean",
        choices=DAILY_AGG_CHOICES,
        help="Aggregation method used when --aggregate-daily is set.",
    )
    parser.add_argument(
        "--time-name",
        default=None,
        help="Time coordinate name. If omitted, tries common names like 'time'.",
    )
    parser.add_argument(
        "--daily-skipna",
        action="store_true",
        help="Ignore NaN values for mean, sum, min, and max daily aggregations.",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=None,
        help="Optional start year (inclusive) to clip before regridding and writing.",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=None,
        help="Optional end year (inclusive) to clip before regridding and writing.",
    )
    parser.add_argument(
        "--compression-level",
        type=int,
        default=4,
        choices=range(0, 10),
        help="NetCDF compression level from 0 (off) to 9. Default: 4.",
    )
    return parser.parse_args()


def detect_coord_name(ds: xr.Dataset, candidates: tuple[str, ...]) -> str:
    for name in candidates:
        if name in ds.coords:
            return name
    raise ValueError(f"Could not find any of {candidates} in coordinates: {list(ds.coords)}")


def apply_variable_renames(ds: xr.Dataset) -> xr.Dataset:
    renames = {old: new for old, new in RENAME_MAP.items() if old in ds.data_vars}
    if renames:
        ds = ds.rename(renames)
    if "crs" in ds.data_vars:
        ds = ds.drop_vars("crs")
    return ds


def convert_pr_flux_to_mm_day(
    ds: xr.Dataset,
    *,
    aggregate_daily: bool = False,
    daily_agg: str = "mean",
) -> tuple[xr.Dataset, str]:
    if "pr" not in ds.data_vars:
        return ds, "Skipped pr conversion: variable 'pr' not found."

    pr = ds["pr"]
    units = str(pr.attrs.get("units", "")).strip()
    normalized_units = units.lower()
    sum_to_daily = aggregate_daily and daily_agg == "sum"

    if units:
        if normalized_units in PR_FLUX_UNITS:
            if sum_to_daily:
                converted = pr * 3600.0
                conversion = "Converted from kg m-2 s-1 to mm per hour by multiplying by 3600 before daily sum aggregation"
                output_units = "mm per 1 hour"
                message = "Converted 'pr' from kg m-2 s-1 to hourly mm before daily sum aggregation."
            else:
                converted = pr * 86400.0
                conversion = "Converted from kg m-2 s-1 to mm/day by multiplying by 86400"
                output_units = "mm/day"
                message = "Converted 'pr' from kg m-2 s-1 to mm/day."
        elif normalized_units in PR_HOURLY_UNITS:
            if sum_to_daily:
                converted = pr
                conversion = "Preserved hourly precipitation in mm per 1 hour for daily sum aggregation"
                output_units = units
                message = "Prepared 'pr' hourly precipitation for daily sum aggregation."
            else:
                converted = pr * 24.0
                conversion = "Converted from mm per hour to mm/day by multiplying by 24"
                output_units = "mm/day"
                message = "Converted 'pr' from mm per 1 hour to mm/day."
        else:
            return ds, f"Skipped pr conversion: unexpected units '{units}'."
    else:
        if sum_to_daily:
            converted = pr * 3600.0
            conversion = "Converted from kg m-2 s-1 to mm per hour by multiplying by 3600 before daily sum aggregation"
            output_units = "mm per 1 hour"
            message = "Converted 'pr' from kg m-2 s-1 to hourly mm before daily sum aggregation."
        else:
            converted = pr * 86400.0
            conversion = "Converted from kg m-2 s-1 to mm/day by multiplying by 86400"
            output_units = "mm/day"
            message = "Converted 'pr' from kg m-2 s-1 to mm/day."

    converted.attrs = dict(pr.attrs)
    converted.attrs["units"] = output_units
    converted.attrs["conversion"] = conversion

    ds_out = ds.copy()
    ds_out["pr"] = converted
    return ds_out, message


def convert_kelvin_to_celsius(ds: xr.Dataset) -> tuple[xr.Dataset, str]:
    converted_names: list[str] = []
    ds_out = ds.copy()

    for var_name, var in ds.data_vars.items():
        units = str(var.attrs.get("units", "")).strip().lower()
        if units not in KELVIN_UNITS:
            continue

        converted = var - 273.15
        converted.attrs = dict(var.attrs)
        converted.attrs["units"] = "degC"
        converted.attrs["conversion"] = "Converted from Kelvin to degrees Celsius by subtracting 273.15"
        ds_out[var_name] = converted
        converted_names.append(var_name)

    if not converted_names:
        return ds, "Skipped Kelvin conversion: no data variables with Kelvin units found."

    converted_label = ", ".join(converted_names)
    return ds_out, f"Converted from Kelvin to degC: {converted_label}."


def chunk_for_regridding(ds: xr.Dataset) -> xr.Dataset:
    chunk_sizes: dict[str, int] = {}

    for dim_name, dim_size in ds.sizes.items():
        if dim_name in {"lat", "lon", "latitude", "longitude"}:
            continue
        if dim_size > INTERP_CHUNK_LENGTH:
            chunk_sizes[dim_name] = INTERP_CHUNK_LENGTH

    if not chunk_sizes:
        return ds

    return ds.chunk(chunk_sizes)


def chunk_for_daily_aggregation(ds: xr.Dataset, time_name: str) -> xr.Dataset:
    if time_name not in ds.sizes:
        return ds
    if ds.sizes[time_name] <= INTERP_CHUNK_LENGTH:
        return ds
    return ds.chunk({time_name: INTERP_CHUNK_LENGTH})


def aggregate_to_daily(ds: xr.Dataset, time_name: str, agg: str, skipna: bool) -> xr.Dataset:
    resampler = ds.resample({time_name: "1D"})

    if agg in {"mean", "sum", "min", "max"}:
        daily = getattr(resampler, agg)(keep_attrs=True, skipna=skipna)
    else:
        daily = getattr(resampler, agg)(keep_attrs=True)

    daily.attrs = dict(ds.attrs)
    daily.attrs["temporal_aggregation"] = f"hourly_to_daily:{agg}"
    daily.attrs["temporal_source_resolution"] = "hourly"
    daily.attrs["temporal_output_resolution"] = "daily"
    return daily


def finalize_daily_pr_units(ds: xr.Dataset, daily_agg: str) -> xr.Dataset:
    if "pr" not in ds.data_vars or daily_agg != "sum":
        return ds

    pr = ds["pr"]
    units = str(pr.attrs.get("units", "")).strip().lower()
    if units not in PR_HOURLY_UNITS:
        return ds

    finalized = pr.copy()
    finalized.attrs = dict(pr.attrs)
    finalized.attrs["units"] = "mm/day"
    finalized.attrs["conversion"] = "Summed hourly precipitation to daily total in mm/day"

    ds_out = ds.copy()
    ds_out["pr"] = finalized
    return ds_out


def should_aggregate_before_regridding(aggregate_daily: bool, daily_agg: str) -> bool:
    return aggregate_daily and daily_agg in LINEAR_DAILY_AGGREGATIONS


def regrid_to_target(ds: xr.Dataset, target_grid_ds: xr.Dataset, method: str) -> xr.Dataset:
    src_lat = detect_coord_name(ds, ("lat", "latitude"))
    src_lon = detect_coord_name(ds, ("lon", "longitude"))
    tgt_lat = detect_coord_name(target_grid_ds, ("lat", "latitude"))
    tgt_lon = detect_coord_name(target_grid_ds, ("lon", "longitude"))

    target_lat = target_grid_ds[tgt_lat]
    target_lon = target_grid_ds[tgt_lon]

    if src_lat != "lat" or src_lon != "lon":
        ds = ds.rename({src_lat: "lat", src_lon: "lon"})

    ds = chunk_for_regridding(ds)

    regridded = ds.interp(lat=target_lat, lon=target_lon, method=method)
    return regridded


@contextmanager
def open_source_dataset(source_path: Path) -> Iterator[tuple[xr.Dataset, str]]:
    if source_path.is_file():
        with xr.open_dataset(source_path) as ds:
            yield ds, str(source_path)
        return

    if source_path.is_dir():
        nc_files = sorted(p for p in source_path.rglob("*.nc") if p.is_file())
        if not nc_files:
            raise FileNotFoundError(f"No .nc files found in source directory: {source_path}")

        with ExitStack() as stack:
            datasets = [stack.enter_context(xr.open_dataset(path)) for path in nc_files]
            try:
                combined = xr.combine_by_coords(datasets, combine_attrs="override")
            except ValueError:
                combined = xr.concat(
                    datasets,
                    dim="time",
                    data_vars="minimal",
                    coords="minimal",
                    compat="override",
                )
            if "time" in combined.coords:
                combined = combined.sortby("time")

            yield combined, f"{source_path} ({len(nc_files)} files)"
        return

    raise FileNotFoundError(f"Source path not found: {source_path}")


def main() -> None:
    args = parse_args()

    source_path = Path(args.source)
    output_path = Path(args.output)
    target_path = Path(args.target_grid)

    if not source_path.exists():
        raise FileNotFoundError(f"Source path not found: {source_path}")
    if (args.start_year is None) != (args.end_year is None):
        raise ValueError("--start-year and --end-year must be provided together")
    if args.start_year is not None and args.start_year > args.end_year:
        raise ValueError("--start-year must be less than or equal to --end-year")

    with open_source_dataset(source_path) as (source_ds, source_desc):
        print(f"Loaded source dataset from: {source_desc}")
        processed = source_ds
        if args.start_year is not None:
            time_name = args.time_name or detect_coord_name(processed, DEFAULT_TIME_CANDIDATES)
            original_count = processed.sizes.get(time_name, 0)
            processed = clip_dataset_by_year(processed, time_name, args.start_year, args.end_year)
            clipped_count = processed.sizes.get(time_name, 0)
            print(
                f"Clipped source dataset to years {args.start_year}-{args.end_year} on '{time_name}' "
                f"({original_count} -> {clipped_count} records)."
            )

        processed = apply_variable_renames(processed)
        if args.convert_pr_to_mm_day:
            processed, message = convert_pr_flux_to_mm_day(
                processed,
                aggregate_daily=args.aggregate_daily,
                daily_agg=args.daily_agg,
            )
            print(message)
        if args.convert_kelvin_to_celsius:
            processed, message = convert_kelvin_to_celsius(processed)
            print(message)

        aggregate_before_regrid = should_aggregate_before_regridding(
            args.aggregate_daily,
            args.daily_agg,
        )
        if aggregate_before_regrid:
            time_name = args.time_name or detect_coord_name(processed, DEFAULT_TIME_CANDIDATES)
            processed = chunk_for_daily_aggregation(processed, time_name)
            processed = aggregate_to_daily(
                processed,
                time_name=time_name,
                agg=args.daily_agg,
                skipna=args.daily_skipna,
            )
            processed = finalize_daily_pr_units(processed, args.daily_agg)
            print(
                f"Aggregated source from hourly to daily using {args.daily_agg} on '{time_name}' before regridding."
            )

        if args.rename_only:
            final_ds = processed
            print("Applied variable renaming and unit conversion only; skipped regridding because --rename-only was set.")
        else:
            if not target_path.exists():
                raise FileNotFoundError(f"Target grid file not found: {target_path}")

            with xr.open_dataset(target_path) as target_ds:
                final_ds = regrid_to_target(processed, target_ds, method=args.method)

            print(
                f"Applied variable renaming and regridding using target grid: {target_path} "
                f"(method={args.method})."
            )

        if args.aggregate_daily and not aggregate_before_regrid:
            time_name = args.time_name or detect_coord_name(final_ds, DEFAULT_TIME_CANDIDATES)
            final_ds = chunk_for_daily_aggregation(final_ds, time_name)
            final_ds = aggregate_to_daily(
                final_ds,
                time_name=time_name,
                agg=args.daily_agg,
                skipna=args.daily_skipna,
            )
            final_ds = finalize_daily_pr_units(final_ds, args.daily_agg)
            print(f"Aggregated output from hourly to daily using {args.daily_agg} on '{time_name}'.")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_netcdf(final_ds, output_path, args.compression_level)

    print(f"Wrote output file: {output_path}")


if __name__ == "__main__":
    main()