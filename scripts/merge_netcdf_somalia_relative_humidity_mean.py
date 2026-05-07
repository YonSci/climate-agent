#!/usr/bin/env python3
"""Merge Somalia relative humidity NetCDF files into one time-series NetCDF file."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import xarray as xr


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Merge multiple NetCDF files from a folder into one NetCDF file."
    )
    parser.add_argument(
        "--input-dir",
        default="data/somalia_relative_humidity_mean/netcdf",
        help="Directory containing NetCDF files to merge.",
    )
    parser.add_argument(
        "--pattern",
        default="*.nc",
        help="Glob pattern for files in input directory (default: *.nc).",
    )
    parser.add_argument(
        "--output",
        default="data/somalia_relative_humidity_mean/somalia_relative_humidity_mean_merged.nc",
        help="Output merged NetCDF file path.",
    )
    return parser.parse_args()


def drop_duplicate_time(ds: xr.Dataset) -> xr.Dataset:
    if "time" not in ds.coords:
        return ds

    time_values = ds["time"].values
    _, keep_idx = np.unique(time_values, return_index=True)
    keep_idx = np.sort(keep_idx)
    if len(keep_idx) != len(time_values):
        ds = ds.isel(time=keep_idx)
    return ds


def main() -> None:
    args = parse_args()

    input_dir = Path(args.input_dir)
    output_path = Path(args.output)

    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    files = sorted(input_dir.glob(args.pattern))
    if not files:
        raise FileNotFoundError(
            f"No files found in {input_dir} with pattern '{args.pattern}'"
        )

    print(f"Found {len(files)} files")

    datasets: list[xr.Dataset] = []
    try:
        for f in files:
            datasets.append(xr.open_dataset(f))

        merged = xr.concat(datasets, dim="time", data_vars="all", coords="minimal")

        if "time" in merged.coords:
            merged = merged.sortby("time")
            merged = drop_duplicate_time(merged)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        merged.to_netcdf(output_path)
        print(f"Merged file written to: {output_path}")

        if "time" in merged.coords:
            print(f"Time steps: {merged.sizes.get('time', 0)}")

    finally:
        for ds in datasets:
            ds.close()


if __name__ == "__main__":
    main()
