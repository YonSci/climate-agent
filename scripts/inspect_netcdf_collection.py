#!/usr/bin/env python3
"""Inspect NetCDF files for schema consistency, spatial resolution, and duplicates."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr


LAT_NAMES = ("lat", "latitude", "y")
LON_NAMES = ("lon", "longitude", "x")
TIME_NAMES = ("time", "valid_time")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect NetCDF files in one or more folders and report variables, "
            "coordinates, dimensions, spatial resolution, and duplicate values."
        )
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=["data"],
        help="Folders or files to inspect (default: data).",
    )
    parser.add_argument(
        "--pattern",
        default="*.nc",
        help="Glob pattern used when a path is a directory (default: *.nc).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Inspect at most this many matching files.",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        default=None,
        help="Optional path to write the full inspection report as JSON.",
    )
    parser.add_argument(
        "--fail-on-issues",
        action="store_true",
        help="Exit with code 1 if schema mismatches or duplicates are found.",
    )
    return parser.parse_args()


def find_files(paths: list[str], pattern: str, limit: int | None) -> list[Path]:
    matches: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_file() and path.suffix.lower() == ".nc":
            matches.append(path)
            continue

        if not path.exists():
            raise FileNotFoundError(f"Path not found: {path}")

        if path.is_dir():
            matches.extend(sorted(path.rglob(pattern)))
            continue

        raise FileNotFoundError(f"Unsupported path: {path}")

    unique_matches = sorted({file.resolve() for file in matches})
    if limit is not None:
        unique_matches = unique_matches[:limit]
    return unique_matches


def choose_coord_name(ds: xr.Dataset, candidates: tuple[str, ...]) -> str | None:
    for name in candidates:
        if name in ds.coords:
            return name
    return None


def summarize_variable_map(ds: xr.Dataset) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for name, var in ds.data_vars.items():
        unit = var.attrs.get("units") or var.attrs.get("unit")
        summary[name] = {
            "dims": list(var.dims),
            "dtype": str(var.dtype),
            "shape": [int(size) for size in var.shape],
            "unit": str(unit) if unit is not None else None,
        }
    return summary


def summarize_coord_map(ds: xr.Dataset) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for name, coord in ds.coords.items():
        summary[name] = {
            "dims": list(coord.dims),
            "dtype": str(coord.dtype),
            "shape": [int(size) for size in coord.shape],
        }
    return summary


def summarize_resolution(coord: xr.DataArray) -> dict[str, Any] | None:
    if coord.ndim != 1 or coord.size < 2:
        return None

    values = np.asarray(coord.values)
    if not np.issubdtype(values.dtype, np.number):
        return None

    diffs = np.diff(values.astype(float))
    diffs = diffs[~np.isnan(diffs)]
    if diffs.size == 0:
        return None

    rounded = np.round(diffs, 10)
    abs_rounded = np.abs(rounded)
    min_diff = float(np.min(abs_rounded))
    max_diff = float(np.max(abs_rounded))
    unique = np.unique(abs_rounded)
    direction = "ascending" if float(values[-1]) >= float(values[0]) else "descending"

    return {
        "count": int(values.size),
        "first": float(values[0]),
        "last": float(values[-1]),
        "min_step": min_diff,
        "max_step": max_diff,
        "direction": direction,
        "regular": bool(np.allclose(min_diff, max_diff)),
        "resolution": float(unique[0]) if len(unique) == 1 else None,
    }


def find_duplicate_values(coord: xr.DataArray) -> dict[str, Any] | None:
    if coord.ndim != 1:
        return None

    values = np.asarray(coord.values)
    as_strings = values.astype("U")
    counts = Counter(as_strings.tolist())
    duplicates = sorted(value for value, count in counts.items() if count > 1)
    if not duplicates:
        return None

    return {
        "count": len(duplicates),
        "examples": duplicates[:10],
    }


def extract_time_values(ds: xr.Dataset) -> list[str]:
    time_name = choose_coord_name(ds, TIME_NAMES)
    if time_name is None:
        return []

    coord = ds[time_name]
    if coord.ndim != 1:
        return []

    values = np.asarray(coord.values)
    return values.astype("datetime64[ns]").astype(str).tolist()


def summarize_time_range(ds: xr.Dataset, time_name: str | None) -> dict[str, Any] | None:
    if time_name is None:
        return None

    coord = ds[time_name]
    if coord.ndim != 1 or coord.size == 0:
        return None

    try:
        values = np.asarray(coord.values).astype("datetime64[ns]")
        start = str(values.min())
        end = str(values.max())
    except (TypeError, ValueError):
        values = np.asarray(coord.values)
        start = str(values[0])
        end = str(values[-1])

    return {
        "start": start,
        "end": end,
        "count": int(coord.size),
    }


def inspect_file(file_path: Path) -> dict[str, Any]:
    with xr.open_dataset(file_path) as ds:
        lat_name = choose_coord_name(ds, LAT_NAMES)
        lon_name = choose_coord_name(ds, LON_NAMES)
        time_name = choose_coord_name(ds, TIME_NAMES)

        duplicate_coords: dict[str, dict[str, Any]] = {}
        for coord_name in ds.coords:
            duplicate_summary = find_duplicate_values(ds[coord_name])
            if duplicate_summary is not None:
                duplicate_coords[coord_name] = duplicate_summary

        result = {
            "file": str(file_path),
            "dims": {name: int(size) for name, size in ds.sizes.items()},
            "coords": summarize_coord_map(ds),
            "data_vars": summarize_variable_map(ds),
            "coord_names": sorted(ds.coords),
            "var_names": sorted(ds.data_vars),
            "time_coord": time_name,
            "time_range": summarize_time_range(ds, time_name),
            "lat_coord": lat_name,
            "lon_coord": lon_name,
            "time_duplicates": duplicate_coords.get(time_name) if time_name else None,
            "duplicate_coords": duplicate_coords,
            "spatial_resolution": {
                "latitude": summarize_resolution(ds[lat_name]) if lat_name else None,
                "longitude": summarize_resolution(ds[lon_name]) if lon_name else None,
            },
            "time_values": extract_time_values(ds),
        }

    return result


def make_signature(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "dims": summary["dims"],
        "coord_names": summary["coord_names"],
        "var_names": summary["var_names"],
        "data_vars": summary["data_vars"],
        "coords": summary["coords"],
    }


def summarize_collection(file_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    if not file_summaries:
        raise ValueError("No file summaries available")

    reference = file_summaries[0]
    reference_signature = make_signature(reference)
    schema_mismatches: list[dict[str, Any]] = []
    duplicate_times_across_files: dict[str, list[str]] = defaultdict(list)

    for summary in file_summaries:
        signature = make_signature(summary)
        if signature != reference_signature:
            schema_mismatches.append(
                {
                    "file": summary["file"],
                    "reference_file": reference["file"],
                    "dims": summary["dims"],
                    "coord_names": summary["coord_names"],
                    "var_names": summary["var_names"],
                }
            )

        for time_value in summary["time_values"]:
            duplicate_times_across_files[time_value].append(summary["file"])

    duplicate_times_across_files = {
        time_value: files
        for time_value, files in duplicate_times_across_files.items()
        if len(files) > 1
    }

    per_file_issues: dict[str, list[str]] = {}
    for summary in file_summaries:
        issues: list[str] = []
        if summary["duplicate_coords"]:
            issues.append("duplicate coordinate values")
        lat_res = summary["spatial_resolution"]["latitude"]
        lon_res = summary["spatial_resolution"]["longitude"]
        if lat_res and not lat_res["regular"]:
            issues.append("irregular latitude spacing")
        if lon_res and not lon_res["regular"]:
            issues.append("irregular longitude spacing")
        if issues:
            per_file_issues[summary["file"]] = issues

    return {
        "file_count": len(file_summaries),
        "reference_file": reference["file"],
        "schema_mismatch_count": len(schema_mismatches),
        "schema_mismatches": schema_mismatches,
        "duplicate_time_values_across_files": duplicate_times_across_files,
        "per_file_issues": per_file_issues,
    }


def print_report(collection_summary: dict[str, Any], file_summaries: list[dict[str, Any]]) -> None:
    print(f"Inspected {collection_summary['file_count']} NetCDF files")
    print(f"Reference schema file: {collection_summary['reference_file']}")

    if collection_summary["schema_mismatch_count"]:
        print(f"Schema mismatches: {collection_summary['schema_mismatch_count']}")
    else:
        print("Schema mismatches: none")

    duplicate_count = len(collection_summary["duplicate_time_values_across_files"])
    if duplicate_count:
        print(f"Duplicate time values across files: {duplicate_count}")
        shown = 0
        for time_value, files in collection_summary["duplicate_time_values_across_files"].items():
            print(f"  {time_value}: {len(files)} file(s)")
            shown += 1
            if shown == 5:
                remaining = duplicate_count - shown
                if remaining > 0:
                    print(f"  ... {remaining} more duplicate time value(s)")
                break
    else:
        print("Duplicate time values across files: none")

    print("\nPer-file summary")
    for summary in file_summaries:
        print(f"- File: {summary['file']}")
        if summary["var_names"]:
            print("  Variables:")
            for var_name in summary["var_names"]:
                var_summary = summary["data_vars"][var_name]
                unit = var_summary.get("unit") or "unknown"
                print(f"    {var_name} (unit={unit})")
        else:
            print("  Variables: (none)")
        print(f"  Coordinates: {', '.join(summary['coord_names']) or '(none)'}")
        print(f"  Dimensions: {summary['dims']}")

        time_range = summary.get("time_range")
        if time_range is not None:
            print(
                f"  Date range: {time_range['start']} to {time_range['end']} "
                f"({time_range['count']} records)"
            )
        elif summary.get("time_coord"):
            print(f"  Date range: unavailable for coordinate '{summary['time_coord']}'")
        else:
            print("  Date range: none (no time coordinate)")

        lat_res = summary["spatial_resolution"]["latitude"]
        lon_res = summary["spatial_resolution"]["longitude"]
        if lat_res or lon_res:
            print("  Spatial resolution:")
            if lat_res:
                lat_text = lat_res["resolution"] if lat_res["resolution"] is not None else "irregular"
                print(
                    f"    latitude: {lat_text} ({lat_res['direction']}, "
                    f"first={lat_res['first']}, last={lat_res['last']})"
                )
            if lon_res:
                lon_text = lon_res["resolution"] if lon_res["resolution"] is not None else "irregular"
                print(
                    f"    longitude: {lon_text} ({lon_res['direction']}, "
                    f"first={lon_res['first']}, last={lon_res['last']})"
                )

        if summary["duplicate_coords"]:
            print("  Duplicate coordinates:")
            for coord_name, duplicate_info in summary["duplicate_coords"].items():
                print(
                    f"    {coord_name}: {duplicate_info['count']} duplicate value(s), "
                    f"examples={duplicate_info['examples']}"
                )
        else:
            print("  Duplicate coordinates: none")


def main() -> None:
    args = parse_args()
    files = find_files(args.paths, args.pattern, args.limit)
    if not files:
        raise FileNotFoundError("No NetCDF files found for the provided paths and pattern")

    file_summaries = [inspect_file(file_path) for file_path in files]
    collection_summary = summarize_collection(file_summaries)
    report = {
        "collection": collection_summary,
        "files": file_summaries,
    }

    print_report(collection_summary, file_summaries)

    if args.json_output:
        output_path = Path(args.json_output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nJSON report written to: {output_path}")

    has_issues = bool(
        collection_summary["schema_mismatches"]
        or collection_summary["duplicate_time_values_across_files"]
        or collection_summary["per_file_issues"]
    )
    if args.fail_on_issues and has_issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()