#!/usr/bin/env python3
"""Aggregate hourly NetCDF data to daily resolution."""

from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Iterator

import xarray as xr


DEFAULT_TIME_CANDIDATES = ("time", "valid_time")
DEFAULT_CHUNK_HOURS = 24 * 30
AGG_CHOICES = ("mean", "sum", "min", "max", "first", "last")


def build_netcdf_encoding(ds: xr.Dataset) -> dict[str, dict[str, object]]:
    encoding: dict[str, dict[str, object]] = {}
    for var_name, var in ds.data_vars.items():
        if var.dtype.kind in {"f", "i", "u"}:
            encoding[var_name] = {"zlib": True, "complevel": 4, "shuffle": True}
    return encoding


def write_netcdf(ds: xr.Dataset, output_path: Path) -> None:
    if output_path.exists():
        output_path.unlink()
    ds.to_netcdf(output_path, encoding=build_netcdf_encoding(ds))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate an hourly NetCDF file or directory of NetCDF files to daily "
            "resolution along the time dimension."
        )
    )
    parser.add_argument(
        "--source",
        required=True,
        help="Input NetCDF file or directory containing NetCDF files.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output NetCDF file path.",
    )
    parser.add_argument(
        "--agg",
        default="mean",
        choices=AGG_CHOICES,
        help="Daily aggregation method to apply to data variables.",
    )
    parser.add_argument(
        "--time-name",
        default=None,
        help="Time coordinate name. If omitted, tries common names like 'time'.",
    )
    parser.add_argument(
        "--chunk-hours",
        type=int,
        default=DEFAULT_CHUNK_HOURS,
        help=(
            "Chunk length applied to the time dimension before aggregation to reduce "
            "memory pressure. Use 0 to disable chunking."
        ),
    )
    parser.add_argument(
        "--skipna",
        action="store_true",
        help="Ignore NaN values for mean, sum, min, and max aggregations.",
    )
    return parser.parse_args()


def detect_coord_name(ds: xr.Dataset, candidates: tuple[str, ...]) -> str:
    for name in candidates:
        if name in ds.coords:
            return name
    raise ValueError(f"Could not find any of {candidates} in coordinates: {list(ds.coords)}")


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


def chunk_for_daily_aggregation(ds: xr.Dataset, time_name: str, chunk_hours: int) -> xr.Dataset:
    if chunk_hours <= 0:
        return ds
    if time_name not in ds.sizes:
        return ds
    if ds.sizes[time_name] <= chunk_hours:
        return ds
    return ds.chunk({time_name: chunk_hours})


def aggregate_hourly_to_daily(
    ds: xr.Dataset,
    *,
    time_name: str,
    agg: str,
    skipna: bool,
) -> xr.Dataset:
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


def main() -> None:
    args = parse_args()

    source_path = Path(args.source)
    output_path = Path(args.output)

    if not source_path.exists():
        raise FileNotFoundError(f"Source path not found: {source_path}")

    with open_source_dataset(source_path) as (source_ds, source_desc):
        print(f"Loaded source dataset from: {source_desc}")

        time_name = args.time_name or detect_coord_name(source_ds, DEFAULT_TIME_CANDIDATES)
        chunked = chunk_for_daily_aggregation(source_ds, time_name, args.chunk_hours)
        daily = aggregate_hourly_to_daily(
            chunked,
            time_name=time_name,
            agg=args.agg,
            skipna=args.skipna,
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
    write_netcdf(daily, output_path)

    print(
        f"Wrote daily dataset to: {output_path} "
        f"(aggregation={args.agg}, time={time_name})"
    )


if __name__ == "__main__":
    main()