#!/usr/bin/env python3
"""Clip NetCDF files by a country boundary vector file."""

from __future__ import annotations

import argparse
from pathlib import Path
import time
from uuid import uuid4

import geopandas as gpd
import rioxarray  # noqa: F401  # Needed to activate the .rio accessor on xarray objects.
import xarray as xr


CLIP_CHUNK_LENGTH = 720


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Clip a NetCDF dataset to polygons from a shapefile/GeoJSON/GPKG boundary file."
        )
    )
    parser.add_argument("--input", required=True, help="Input NetCDF file path.")
    parser.add_argument(
        "--boundary",
        required=True,
        help="Boundary vector file (.shp, .geojson, .gpkg, etc.).",
    )
    parser.add_argument("--output", required=True, help="Output clipped NetCDF file path.")
    parser.add_argument(
        "--lat-name",
        default=None,
        help="Latitude coordinate name (auto-detected if not provided).",
    )
    parser.add_argument(
        "--lon-name",
        default=None,
        help="Longitude coordinate name (auto-detected if not provided).",
    )
    parser.add_argument(
        "--where-field",
        default=None,
        help="Optional attribute field used to subset the boundary layer.",
    )
    parser.add_argument(
        "--where-value",
        default=None,
        help="Optional attribute value used with --where-field to subset the boundary layer.",
    )
    parser.add_argument(
        "--all-touched",
        action="store_true",
        help="If set, include all cells touched by polygon edges.",
    )
    parser.add_argument(
        "--compression-level",
        type=int,
        default=4,
        choices=range(0, 10),
        help="NetCDF compression level from 0 (off) to 9. Default: 4.",
    )
    return parser.parse_args()


def auto_coord_name(ds: xr.Dataset, candidates: tuple[str, ...]) -> str:
    for name in candidates:
        if name in ds.coords:
            return name
    raise ValueError(f"Could not detect coordinate from {candidates}. Found: {list(ds.coords)}")


def chunk_for_clip(ds: xr.Dataset, spatial_dims: set[str]) -> xr.Dataset:
    chunk_sizes: dict[str, int] = {}
    for dim_name, dim_size in ds.sizes.items():
        if dim_name in spatial_dims:
            continue
        if dim_size > CLIP_CHUNK_LENGTH:
            chunk_sizes[dim_name] = CLIP_CHUNK_LENGTH

    if not chunk_sizes:
        return ds

    return ds.chunk(chunk_sizes)


def main() -> None:
    args = parse_args()

    input_path = Path(args.input)
    boundary_path = Path(args.boundary)
    output_path = Path(args.output)

    if not input_path.exists():
        raise FileNotFoundError(f"Input NetCDF not found: {input_path}")
    if not boundary_path.exists():
        raise FileNotFoundError(f"Boundary file not found: {boundary_path}")

    boundaries = gpd.read_file(boundary_path)
    if boundaries.empty:
        raise ValueError(f"Boundary file has no features: {boundary_path}")

    if args.where_field and args.where_value is not None:
        if args.where_field not in boundaries.columns:
            raise ValueError(
                f"Field '{args.where_field}' not found in boundary columns: {list(boundaries.columns)}"
            )
        boundaries = boundaries[boundaries[args.where_field].astype(str) == str(args.where_value)]
        if boundaries.empty:
            raise ValueError(
                f"No boundary features matched {args.where_field} == {args.where_value!r}"
            )

    with xr.open_dataset(input_path) as ds:
        lat_name = args.lat_name or auto_coord_name(ds, ("lat", "latitude", "y"))
        lon_name = args.lon_name or auto_coord_name(ds, ("lon", "longitude", "x"))
        ds = chunk_for_clip(ds, {lat_name, lon_name})

        # Tell rioxarray which dimensions are spatial.
        ds = ds.rio.set_spatial_dims(x_dim=lon_name, y_dim=lat_name)

        # Most climate grids in this workflow are lon/lat in WGS84.
        if ds.rio.crs is None:
            ds = ds.rio.write_crs("EPSG:4326")

        # Reproject boundaries to dataset CRS before clipping.
        boundaries = boundaries.to_crs(ds.rio.crs)
        clipped = ds.rio.clip(
            boundaries.geometry,
            boundaries.crs,
            drop=True,
            all_touched=args.all_touched,
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
    write_netcdf(clipped, output_path, args.compression_level)

    print(f"Input: {input_path}")
    print(f"Boundary: {boundary_path}")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()