#!/usr/bin/env python3
"""
merge_chirps_country.py — Merge yearly CHIRPS p25 files for one country into
a single NetCDF in data/merged_files/, ready for run_historical_workflow.py.

Yearly source files are expected in data/{country}_chirips/ under the naming
convention chirps-v2.0.{YYYY}.days_p25.nc (as downloaded by download_chirps.py).

Usage
-----
    python scripts/merge_chirps_country.py --country kenya --start 2010 --end 2025
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import xarray as xr

_ROOT = Path(__file__).resolve().parents[1]

_CHIRPS_DIR = {
    "ethiopia": _ROOT / "data" / "ethiopia_chirips",
    "kenya":    _ROOT / "data" / "kenya_chirips",
    "somalia":  _ROOT / "data" / "somalia_chirips",
}

_MERGED_DIR = _ROOT / "data" / "merged_files"


def _standardize(ds: xr.Dataset) -> xr.Dataset:
    ren = {}
    if "latitude" in ds.dims:
        ren["latitude"] = "lat"
    if "longitude" in ds.dims:
        ren["longitude"] = "lon"
    if ren:
        ds = ds.rename(ren)
    try:
        lat = ds["lat"]
        if float(lat[0]) > float(lat[-1]):
            ds = ds.reindex(lat=list(reversed(lat.values)))
    except Exception:
        pass
    return ds


def merge(country: str, start: int, end: int) -> Path:
    src_dir = _CHIRPS_DIR[country]
    out = _MERGED_DIR / f"{country}_pr_{start}_{end}.nc"

    if out.exists():
        print(f"[skip] {out.name} already exists")
        return out

    # Use the country-clipped (_clip) files — these are much smaller than
    # the global p25 downloads and are what run_historical_workflow.py expects
    # as the target grid (matching Ethiopia's ethiopia_pr_*.nc at ~20 MB).
    files = sorted(src_dir.glob("chirps-v2.0.????.days_p25_clip.nc"))
    files = [f for f in files if start <= int(f.name.split(".")[2]) <= end]

    if not files:
        raise FileNotFoundError(
            f"No yearly CHIRPS files found in {src_dir} for {start}–{end}.\n"
            "Run download_chirps.py first to download the source data."
        )

    print(f"[merge] {len(files)} files -> {out.name}")
    ds = xr.open_mfdataset(files, combine="by_coords", preprocess=_standardize)
    _MERGED_DIR.mkdir(parents=True, exist_ok=True)
    enc = {v: {"zlib": True, "complevel": 1} for v in ds.data_vars}
    ds.to_netcdf(out, encoding=enc)
    ds.close()
    print(f"[ok] {out}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--country", required=True,
                    choices=list(_CHIRPS_DIR), help="Country long name")
    ap.add_argument("--start", type=int, required=True, help="Start year")
    ap.add_argument("--end",   type=int, required=True, help="End year")
    args = ap.parse_args()

    try:
        merge(args.country, args.start, args.end)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
