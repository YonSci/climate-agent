#!/usr/bin/env python3
"""Clip NetCDF data to a time range by year."""

from __future__ import annotations

import argparse
from pathlib import Path

import xarray as xr


TIME_NAMES = ("time", "valid_time")


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
            "Clip NetCDF dataset(s) to a year range. Supports a single input file "
            "or a directory of .nc files."
        )
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Input NetCDF file or folder containing NetCDF files.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help=(
            "Output NetCDF path (when --input is a file) or output folder "
            "(when --input is a directory)."
        ),
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=2040,
        help="Start year (inclusive). Default: 2040.",
    )
    parser.add_argument(
        "--end-year",
        type=int,
        default=2070,
        help="End year (inclusive). Default: 2070.",
    )
    parser.add_argument(
        "--time-name",
        default=None,
        help="Time coordinate name (auto-detected if not provided).",
    )
    parser.add_argument(
        "--pattern",
        default="*.nc",
        help="Glob pattern used when input is a directory. Default: *.nc.",
    )
    parser.add_argument(
        "--suffix",
        default="_2040_2070",
        help=(
            "Filename suffix used for directory mode before .nc extension. "
            "Default: _2040_2070."
        ),
    )
    return parser.parse_args()


def detect_time_coord(ds: xr.Dataset, preferred: str | None = None) -> str:
    if preferred:
        if preferred in ds.coords:
            return preferred
        raise ValueError(f"Time coordinate '{preferred}' not found. Found: {list(ds.coords)}")

    for name in TIME_NAMES:
        if name in ds.coords:
            return name

    raise ValueError(f"Could not detect time coordinate. Found coordinates: {list(ds.coords)}")


def clip_dataset_by_year(ds: xr.Dataset, time_name: str, start_year: int, end_year: int) -> xr.Dataset:
    years = ds[time_name].dt.year
    mask = (years >= start_year) & (years <= end_year)
    clipped = ds.where(mask, drop=True)

    if clipped.sizes.get(time_name, 0) == 0:
        raise ValueError(
            f"No time values found between {start_year} and {end_year} in coordinate '{time_name}'."
        )

    return clipped


def clip_file(
    input_file: Path,
    output_file: Path,
    start_year: int,
    end_year: int,
    time_name: str | None,
) -> None:
    with xr.open_dataset(input_file) as ds:
        chosen_time = detect_time_coord(ds, time_name)
        clipped = clip_dataset_by_year(ds, chosen_time, start_year, end_year)

        output_file.parent.mkdir(parents=True, exist_ok=True)
        write_netcdf(clipped, output_file)

        print(
            f"Input: {input_file} | Time coord: {chosen_time} | "
            f"Records: {ds.sizes.get(chosen_time, 0)} -> {clipped.sizes.get(chosen_time, 0)}"
        )
        print(f"Output: {output_file}")


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)

    if args.start_year > args.end_year:
        raise ValueError("--start-year must be less than or equal to --end-year")

    if not input_path.exists():
        raise FileNotFoundError(f"Input path not found: {input_path}")

    if input_path.is_file():
        clip_file(
            input_file=input_path,
            output_file=output_path,
            start_year=args.start_year,
            end_year=args.end_year,
            time_name=args.time_name,
        )
        return

    if input_path.is_dir():
        nc_files = sorted(input_path.rglob(args.pattern))
        nc_files = [path for path in nc_files if path.is_file() and path.suffix.lower() == ".nc"]
        if not nc_files:
            raise FileNotFoundError(
                f"No NetCDF files found in directory '{input_path}' with pattern '{args.pattern}'"
            )

        output_path.mkdir(parents=True, exist_ok=True)
        print(f"Found {len(nc_files)} files to process")

        for source_file in nc_files:
            out_name = f"{source_file.stem}{args.suffix}.nc"
            target_file = output_path / out_name
            clip_file(
                input_file=source_file,
                output_file=target_file,
                start_year=args.start_year,
                end_year=args.end_year,
                time_name=args.time_name,
            )
        return

    raise FileNotFoundError(f"Unsupported input path: {input_path}")


if __name__ == "__main__":
    main()
