#!/usr/bin/env python3
"""Inspect a final NetCDF file and create diagnostic QA plots plus a QC JSON sidecar."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import xarray as xr


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect a NetCDF file and generate diagnostic plots to verify grid, "
            "values, and temporal behavior."
        )
    )
    parser.add_argument(
        "--file",
        default="data/merged_files/ethiopia_rh_2010_2025_025deg.nc",
        help="Path to NetCDF file to inspect.",
    )
    parser.add_argument(
        "--var",
        default=None,
        help="Variable name to plot. If omitted, first data variable is used.",
    )
    parser.add_argument(
        "--out-dir",
        default="data/merged_files/diagnostics",
        help="Output directory for diagnostic plot.",
    )
    parser.add_argument(
        "--time-index",
        type=int,
        default=0,
        help="Time index for the map panel (default: 0).",
    )
    return parser.parse_args()


def coord_name(ds: xr.Dataset, names: tuple[str, ...]) -> str:
    for name in names:
        if name in ds.coords:
            return name
    raise ValueError(f"Missing expected coordinate. Tried {names}, found {list(ds.coords)}")


def grid_resolution(coord: xr.DataArray) -> tuple[float | None, str | None]:
    if coord.ndim != 1 or coord.size < 2:
        return None, None
    values = np.asarray(coord.values, dtype=float)
    step = float(np.abs(values[1] - values[0]))
    direction = "ascending" if values[-1] >= values[0] else "descending"
    return step, direction


def _time_gap_years(time_values: np.ndarray) -> list[int]:
    """Return sorted list of calendar years absent from the time axis."""
    try:
        import pandas as pd
        idx = pd.DatetimeIndex(time_values)
        years_present = set(idx.year.tolist())
        if not years_present:
            return []
        full_range = set(range(min(years_present), max(years_present) + 1))
        return sorted(full_range - years_present)
    except Exception:
        return []


def build_qc_stats(
    ds: xr.Dataset, var_name: str,
    lat_name: str, lon_name: str, time_name: str,
) -> dict:
    """
    Compute detailed QC statistics for *var_name* and return a structured dict.
    All float values are rounded to 4 decimal places for readability.
    """
    data = ds[var_name]
    values = np.asarray(data.values, dtype=float)
    finite_mask = np.isfinite(values)
    finite_vals = values[finite_mask]

    lat_step, lat_dir = grid_resolution(ds[lat_name])
    lon_step, lon_dir = grid_resolution(ds[lon_name])
    time_values = np.asarray(ds[time_name].values)
    unique_time = np.unique(time_values)
    duplicate_count = int(time_values.size - unique_time.size)
    missing_years = _time_gap_years(time_values)

    stats: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "file_variable": var_name,
        "units": str(data.attrs.get("units", "")),
        "dims": dict(ds.sizes),
        "grid": {
            "lat_step_deg":  round(lat_step, 6) if lat_step is not None else None,
            "lon_step_deg":  round(lon_step, 6) if lon_step is not None else None,
            "lat_direction": lat_dir,
            "lon_direction": lon_dir,
            "lat_min": round(float(ds[lat_name].values.min()), 4),
            "lat_max": round(float(ds[lat_name].values.max()), 4),
            "lon_min": round(float(ds[lon_name].values.min()), 4),
            "lon_max": round(float(ds[lon_name].values.max()), 4),
        },
        "time": {
            "n_timesteps":      int(time_values.size),
            "n_unique":         int(unique_time.size),
            "duplicate_count":  duplicate_count,
            "missing_years":    missing_years,
            "n_missing_years":  len(missing_years),
        },
        "coverage": {
            "total_pixels":  int(values.size),
            "finite_pixels": int(finite_mask.sum()),
            "nan_pixels":    int(values.size - finite_mask.sum()),
            "finite_ratio":  round(float(finite_mask.sum()) / max(values.size, 1), 4),
        },
        "value_stats": {},
    }

    if finite_vals.size > 0:
        percentiles = np.percentile(finite_vals, [1, 5, 25, 50, 75, 95, 99])
        stats["value_stats"] = {
            "min":    round(float(finite_vals.min()), 4),
            "p01":    round(float(percentiles[0]), 4),
            "p05":    round(float(percentiles[1]), 4),
            "p25":    round(float(percentiles[2]), 4),
            "median": round(float(percentiles[3]), 4),
            "p75":    round(float(percentiles[4]), 4),
            "p95":    round(float(percentiles[5]), 4),
            "p99":    round(float(percentiles[6]), 4),
            "max":    round(float(finite_vals.max()), 4),
            "mean":   round(float(finite_vals.mean()), 4),
            "std":    round(float(finite_vals.std()), 4),
        }

    # Per-timestep missing fraction (useful for spotting data drop-outs)
    missing_by_time = (
        data.isnull().mean(dim=[lat_name, lon_name]).values.tolist()
        if lat_name in data.dims and lon_name in data.dims else []
    )
    stats["missing_fraction_by_timestep"] = {
        "min":  round(float(np.min(missing_by_time)), 4) if missing_by_time else None,
        "max":  round(float(np.max(missing_by_time)), 4) if missing_by_time else None,
        "mean": round(float(np.mean(missing_by_time)), 4) if missing_by_time else None,
        "n_timesteps_above_20pct": int(sum(1 for v in missing_by_time if v > 0.20)),
        "n_timesteps_above_50pct": int(sum(1 for v in missing_by_time if v > 0.50)),
    }

    return stats


def inspect_dataset(ds: xr.Dataset, var_name: str, lat_name: str, lon_name: str, time_name: str) -> None:
    data = ds[var_name]
    lat_step, lat_dir = grid_resolution(ds[lat_name])
    lon_step, lon_dir = grid_resolution(ds[lon_name])

    print("Dataset diagnostics")
    print(f"- Variable: {var_name}")
    print(f"- Dims: {dict(ds.sizes)}")
    print(f"- Coordinates: {list(ds.coords)}")
    print(f"- Data variables: {list(ds.data_vars)}")
    print(f"- Latitude step: {lat_step} ({lat_dir})")
    print(f"- Longitude step: {lon_step} ({lon_dir})")

    time_values = np.asarray(ds[time_name].values)
    unique_time = np.unique(time_values)
    duplicate_count = int(time_values.size - unique_time.size)
    missing_years = _time_gap_years(time_values)
    print(f"- Time length: {time_values.size}")
    print(f"- Duplicate time values: {duplicate_count}")
    if missing_years:
        print(f"- Missing years in range: {missing_years}")

    values = np.asarray(data.values, dtype=float)
    finite = np.isfinite(values)
    finite_ratio = float(finite.sum() / finite.size)
    finite_vals = values[finite]
    print(f"- Finite ratio: {finite_ratio:.4f}")
    if finite.any():
        percentiles = np.percentile(finite_vals, [5, 25, 50, 75, 95])
        print(f"- Value min: {float(finite_vals.min()):.4f}")
        print(f"- Value p05/p25/median/p75/p95: "
              f"{percentiles[0]:.4f} / {percentiles[1]:.4f} / {percentiles[2]:.4f} / "
              f"{percentiles[3]:.4f} / {percentiles[4]:.4f}")
        print(f"- Value max: {float(finite_vals.max()):.4f}")
        print(f"- Value mean ± std: {float(finite_vals.mean()):.4f} ± {float(finite_vals.std()):.4f}")


def make_plot(
    ds: xr.Dataset,
    var_name: str,
    lat_name: str,
    lon_name: str,
    time_name: str,
    time_index: int,
    output_png: Path,
) -> None:
    data = ds[var_name]
    n_time = int(ds.sizes.get(time_name, 1))
    if n_time == 0:
        raise ValueError("Time dimension has zero length")

    if time_index < 0 or time_index >= n_time:
        raise IndexError(f"time-index {time_index} out of range [0, {n_time - 1}]")

    map_slice = data.isel({time_name: time_index}) if time_name in data.dims else data
    spatial_mean = data.mean(dim=[lat_name, lon_name], skipna=True)
    flat_values = data.values.ravel()
    flat_values = flat_values[np.isfinite(flat_values)]

    t_label = str(ds[time_name].values[time_index]) if time_name in ds.coords else str(time_index)

    fig, axes = plt.subplots(2, 2, figsize=(13, 9), constrained_layout=True)

    ax = axes[0, 0]
    mesh = ax.pcolormesh(ds[lon_name], ds[lat_name], map_slice, shading="auto")
    fig.colorbar(mesh, ax=ax, orientation="vertical", label=var_name)
    ax.set_title(f"Map at {t_label}")
    ax.set_xlabel(lon_name)
    ax.set_ylabel(lat_name)

    ax = axes[0, 1]
    if time_name in spatial_mean.dims:
        ax.plot(ds[time_name].values, spatial_mean.values, lw=1.2)
        ax.set_xlabel(time_name)
    else:
        ax.plot(spatial_mean.values, lw=1.2)
        ax.set_xlabel("index")
    ax.set_title("Spatial mean over time")
    ax.set_ylabel(var_name)

    ax = axes[1, 0]
    ax.hist(flat_values, bins=50)
    ax.set_title("Value distribution")
    ax.set_xlabel(var_name)
    ax.set_ylabel("count")

    ax = axes[1, 1]
    missing_by_time = data.isnull().mean(dim=[lat_name, lon_name])
    if time_name in missing_by_time.dims:
        ax.plot(ds[time_name].values, missing_by_time.values, lw=1.2)
        ax.set_xlabel(time_name)
    else:
        ax.plot(missing_by_time.values, lw=1.2)
        ax.set_xlabel("index")
    ax.set_title("Missing fraction over time")
    ax.set_ylabel("fraction missing")
    ax.set_ylim(0.0, 1.0)

    fig.suptitle(f"NetCDF diagnostics: {output_png.stem}")
    output_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_png, dpi=160)
    plt.close(fig)


def main() -> None:
    args = parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    out_dir = Path(args.out_dir)
    out_png  = out_dir / f"{file_path.stem}_diagnostic.png"
    out_json = out_dir / f"{file_path.stem}_qc.json"

    with xr.open_dataset(file_path) as ds:
        var_name = args.var or next(iter(ds.data_vars), None)
        if var_name is None:
            raise ValueError("No data variables found in dataset")
        if var_name not in ds.data_vars:
            raise ValueError(f"Variable '{var_name}' not found. Available: {list(ds.data_vars)}")

        lat_name  = coord_name(ds, ("lat", "latitude"))
        lon_name  = coord_name(ds, ("lon", "longitude"))
        time_name = coord_name(ds, ("time", "valid_time"))

        inspect_dataset(ds, var_name, lat_name, lon_name, time_name)
        make_plot(ds, var_name, lat_name, lon_name, time_name, args.time_index, out_png)

        qc = build_qc_stats(ds, var_name, lat_name, lon_name, time_name)
        qc["source_file"] = str(file_path)

    out_json.parent.mkdir(parents=True, exist_ok=True)
    with open(out_json, "w") as f:
        json.dump(qc, f, indent=2)

    print(f"- Diagnostic plot written to: {out_png}")
    print(f"- QC JSON sidecar written to: {out_json}")


if __name__ == "__main__":
    main()