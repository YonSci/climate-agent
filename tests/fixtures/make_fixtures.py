#!/usr/bin/env python3
"""
make_fixtures.py — Generate small synthetic NetCDF fixtures for the test suite.

Run once to populate tests/fixtures/ with deterministic files that validation
checks can operate on without needing real downloaded data:

    python tests/fixtures/make_fixtures.py

Files produced (all covering 2010-01-01 … 2011-12-31, 5×5 grid ~Ethiopia bbox):
    tas_eth_historical_2010-2011_0p25deg.nc   — temperature in K
    rh_eth_historical_2010-2011_0p25deg.nc    — relative humidity in %
    vpd_eth_historical_2010-2011_0p25deg.nc   — vapour pressure deficit in hPa
    pr_eth_historical_2010-2011_0p25deg.nc    — precipitation in mm/day
    reference_grid.nc                          — minimal CHIRPS-like reference grid
"""

from __future__ import annotations
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

OUT_DIR = Path(__file__).parent

# Small Ethiopia-like bounding box, 0.25° spacing
LAT = np.array([3.0, 5.5, 8.0, 10.5, 13.0], dtype="float32")
LON = np.array([33.0, 35.75, 38.5, 41.25, 44.0], dtype="float32")
TIMES = pd.date_range("2010-01-01", "2011-12-31", freq="D")

RNG = np.random.default_rng(42)


def _make_ds(var: str, data: np.ndarray, units: str, long_name: str) -> xr.Dataset:
    da = xr.DataArray(
        data.astype("float32"),
        dims=["time", "lat", "lon"],
        coords={"time": TIMES, "lat": LAT, "lon": LON},
        name=var,
        attrs={"units": units, "long_name": long_name},
    )
    return da.to_dataset()


def make_tas() -> None:
    shape = (len(TIMES), len(LAT), len(LON))
    data = 295.0 + RNG.normal(0, 5, shape).astype("float32")
    ds = _make_ds("tas", data, "K", "Near-surface air temperature")
    path = OUT_DIR / "tas_eth_historical_2010-2011_0p25deg.nc"
    ds.to_netcdf(path, encoding={"tas": {"zlib": True, "complevel": 1}})
    print(f"  wrote {path.name}")


def make_rh() -> None:
    shape = (len(TIMES), len(LAT), len(LON))
    data = np.clip(60.0 + RNG.normal(0, 15, shape), 5, 100).astype("float32")
    ds = _make_ds("rh", data, "%", "Near-surface relative humidity")
    path = OUT_DIR / "rh_eth_historical_2010-2011_0p25deg.nc"
    ds.to_netcdf(path, encoding={"rh": {"zlib": True, "complevel": 1}})
    print(f"  wrote {path.name}")


def make_vpd() -> None:
    shape = (len(TIMES), len(LAT), len(LON))
    data = np.abs(5.0 + RNG.normal(0, 3, shape)).astype("float32")
    ds = _make_ds("vpd", data, "hPa", "Vapour pressure deficit")
    path = OUT_DIR / "vpd_eth_historical_2010-2011_0p25deg.nc"
    ds.to_netcdf(path, encoding={"vpd": {"zlib": True, "complevel": 1}})
    print(f"  wrote {path.name}")


def make_pr() -> None:
    shape = (len(TIMES), len(LAT), len(LON))
    data = np.abs(RNG.exponential(3.0, shape)).astype("float32")
    ds = _make_ds("pr", data, "mm/day", "Precipitation")
    path = OUT_DIR / "pr_eth_historical_2010-2011_0p25deg.nc"
    ds.to_netcdf(path, encoding={"pr": {"zlib": True, "complevel": 1}})
    print(f"  wrote {path.name}")


def make_reference_grid() -> None:
    """Minimal reference grid file (lat/lon coords only, no data variable)."""
    ds = xr.Dataset(
        {"reference": xr.DataArray(np.zeros((len(LAT), len(LON)), dtype="float32"),
                                   dims=["lat", "lon"],
                                   coords={"lat": LAT, "lon": LON})},
    )
    path = OUT_DIR / "reference_grid.nc"
    ds.to_netcdf(path)
    print(f"  wrote {path.name}")


if __name__ == "__main__":
    print(f"Generating synthetic fixtures in {OUT_DIR}/")
    make_tas()
    make_rh()
    make_vpd()
    make_pr()
    make_reference_grid()
    print("Done.")
