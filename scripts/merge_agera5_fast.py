#!/usr/bin/env python3
"""
merge_agera5_fast.py — Memory-efficient merge of per-day AgERA5 NetCDF files.

Replaces the per-file xr.open_dataset() loop in the country-specific merge
scripts with a year-by-year load strategy.

Old approach  : opens 5844 datasets into a Python list, then xr.concat loads
                everything into RAM at once.  Peak RAM ~17 GB, time 2-4 hours.
This approach : loads one year (~365 files, ~11 MB) at a time into RAM,
                concatenates in memory, writes once as pure numpy arrays.
                Peak RAM ~200-400 MB, time ~5 minutes.
                Avoids HDF5 filter pipeline failures caused by keeping 5844
                compressed source files open simultaneously on Windows.

Usage
-----
    python scripts/merge_agera5_fast.py --country kenya --variable rh
    python scripts/merge_agera5_fast.py --country somalia --variable temp --start 2010 --end 2025
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import xarray as xr

_ROOT = Path(__file__).resolve().parents[1]
_MERGED_DIR = _ROOT / "data" / "merged_files"

_SOURCE_SUBDIR = {
    "temp": "temperature",
    "rh":   "relative_humidity_mean",
    "vpd":  "vapour_pressure_deficit",
}
_COUNTRIES = ("ethiopia", "kenya", "somalia")
_VARIABLES = tuple(_SOURCE_SUBDIR)

_YEAR_RE = re.compile(r"AgERA5_(\d{4})\d{4}")


def _group_by_year(files: list[Path]) -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = {}
    for f in files:
        m = _YEAR_RE.search(f.name)
        year = m.group(1) if m else "0000"
        groups.setdefault(year, []).append(f)
    return dict(sorted(groups.items()))


def merge(country: str, variable: str, start: int, end: int) -> Path:
    out = _MERGED_DIR / f"{country}_{variable}_{start}_{end}.nc"
    if out.exists():
        print(f"[skip] {out.name} already exists")
        return out

    src_dir = _ROOT / "data" / f"{country}_{_SOURCE_SUBDIR[variable]}" / "netcdf"
    if not src_dir.exists():
        raise FileNotFoundError(f"Source directory not found: {src_dir}")

    files = sorted(src_dir.glob("*.nc"))
    if not files:
        raise FileNotFoundError(f"No .nc files in {src_dir}")

    print(f"[merge] {len(files)} files -> {out.name}")

    year_groups = _group_by_year(files)

    # Load one year at a time so we never hold more than ~365 file handles open
    # simultaneously. .load() materialises the lazy arrays into numpy and closes
    # the source handles before we move on to the next year.
    yearly: list[xr.Dataset] = []
    for year, yfiles in year_groups.items():
        print(f"  [year] {year}: {len(yfiles)} files ...", end=" ", flush=True)
        ds_y = xr.open_mfdataset(
            sorted(yfiles),
            combine="nested",
            concat_dim="time",
            data_vars="minimal",
            coords="minimal",
            compat="override",
            engine="netcdf4",
        ).load()
        print(f"{ds_y.nbytes / 1e6:.1f} MB")
        yearly.append(ds_y)

    print(f"[concat] {len(yearly)} years ...")
    ds = xr.concat(yearly, dim="time")
    for ds_y in yearly:
        ds_y.close()

    # Sort time axis and drop duplicates (occasional AgERA5 overlap)
    ds = ds.sortby("time")
    _, keep = np.unique(ds["time"].values, return_index=True)
    if len(keep) < ds.sizes["time"]:
        ds = ds.isel(time=keep)

    _MERGED_DIR.mkdir(parents=True, exist_ok=True)
    enc = {v: {"zlib": True, "complevel": 1} for v in ds.data_vars}
    print(f"[write] {ds.sizes['time']} time steps ...")
    tmp_out = out.with_suffix(".tmp.nc")
    try:
        ds.to_netcdf(tmp_out, encoding=enc)
        tmp_out.replace(out)  # atomic rename; no corrupt partial at the target path
    except Exception:
        if tmp_out.exists():
            tmp_out.unlink(missing_ok=True)
        ds.close()
        raise
    ds.close()
    print(f"[ok] {out}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--country",  required=True, choices=_COUNTRIES)
    ap.add_argument("--variable", required=True, choices=_VARIABLES)
    ap.add_argument("--start", type=int, default=2010)
    ap.add_argument("--end",   type=int, default=2025)
    args = ap.parse_args()

    try:
        merge(args.country, args.variable, args.start, args.end)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
