"""
spatial_checks.py — Grid match, spatial bounds, and cross-file grid consistency.
"""

from __future__ import annotations
import logging
from pathlib import Path

import numpy as np
import xarray as xr

logger = logging.getLogger(__name__)

_LAT_CANDIDATES = ("lat", "latitude")
_LON_CANDIDATES = ("lon", "longitude")


def _detect_dim(ds: xr.Dataset, candidates: tuple[str, ...]) -> str | None:
    for name in candidates:
        if name in ds.coords or name in ds.dims:
            return name
    return None


def check_grid_match(ds: xr.Dataset, target_path: Path) -> str:
    """Return 'OK' if *ds* lat/lon arrays match those in *target_path*."""
    try:
        with xr.open_dataset(target_path) as tgt:
            out_lat = _detect_dim(ds,  _LAT_CANDIDATES)
            out_lon = _detect_dim(ds,  _LON_CANDIDATES)
            tgt_lat = _detect_dim(tgt, _LAT_CANDIDATES)
            tgt_lon = _detect_dim(tgt, _LON_CANDIDATES)
            if not all([out_lat, out_lon, tgt_lat, tgt_lon]):
                return "FAIL"
            if (ds.sizes[out_lat] != tgt.sizes[tgt_lat] or
                    ds.sizes[out_lon] != tgt.sizes[tgt_lon]):
                return "FAIL"
            if not np.allclose(ds[out_lat].values, tgt[tgt_lat].values):
                return "FAIL"
            if not np.allclose(ds[out_lon].values, tgt[tgt_lon].values):
                return "FAIL"
        return "OK"
    except Exception:
        return "FAIL"


def check_spatial_bounds(ds: xr.Dataset, target_path: Path) -> str:
    """Return 'OK' if *ds* spatial extent is within *target_path*'s extent."""
    try:
        with xr.open_dataset(target_path) as tgt:
            out_lat = _detect_dim(ds,  _LAT_CANDIDATES)
            out_lon = _detect_dim(ds,  _LON_CANDIDATES)
            tgt_lat = _detect_dim(tgt, _LAT_CANDIDATES)
            tgt_lon = _detect_dim(tgt, _LON_CANDIDATES)
            if not all([out_lat, out_lon, tgt_lat, tgt_lon]):
                return "FAIL"
            lat_vals = np.asarray(ds[out_lat].values,  dtype=float)
            lon_vals = np.asarray(ds[out_lon].values,  dtype=float)
            t_lat    = np.asarray(tgt[tgt_lat].values, dtype=float)
            t_lon    = np.asarray(tgt[tgt_lon].values, dtype=float)
            if (ds.sizes[out_lat] > tgt.sizes[tgt_lat] or
                    ds.sizes[out_lon] > tgt.sizes[tgt_lon]):
                return "FAIL"
            if lat_vals.min() < t_lat.min() or lat_vals.max() > t_lat.max():
                return "FAIL"
            if lon_vals.min() < t_lon.min() or lon_vals.max() > t_lon.max():
                return "FAIL"
        return "OK"
    except Exception:
        return "FAIL"


def check_grid_consistency(paths_and_vars: list[tuple[Path, str]]) -> dict[str, str]:
    """Check that all files in *paths_and_vars* share the same lat/lon grid.

    The first existing file is used as the reference. Returns a dict mapping
    filename → 'OK' | 'FAIL' | 'SKIP' | 'MISSING', plus an 'overall' key.
    """
    results: dict[str, str] = {}
    found_reference = False
    ref_lat_vals = ref_lon_vals = None
    ref_file = None

    present = [(p, v) for p, v in paths_and_vars if p.exists()]
    if len(present) < 2:
        for p, _ in paths_and_vars:
            results[p.name] = "MISSING" if not p.exists() else "SKIP"
        results["overall"] = "SKIP"
        return results

    for path, _var in present:
        try:
            with xr.open_dataset(path) as ds:
                lat = _detect_dim(ds, _LAT_CANDIDATES)
                lon = _detect_dim(ds, _LON_CANDIDATES)
                if not lat or not lon:
                    results[path.name] = "FAIL"
                    continue
                if not found_reference:
                    ref_lat_vals = ds[lat].values.copy()
                    ref_lon_vals = ds[lon].values.copy()
                    ref_file = path.name
                    found_reference = True
                    results[path.name] = "OK"
                    continue
                if (ds.sizes[lat] != len(ref_lat_vals) or
                        ds.sizes[lon] != len(ref_lon_vals)):
                    results[path.name] = "FAIL"
                    logger.warning(
                        f"Grid consistency FAIL: {path.name} grid shape "
                        f"({ds.sizes[lat]}×{ds.sizes[lon]}) differs from "
                        f"reference {ref_file} "
                        f"({len(ref_lat_vals)}×{len(ref_lon_vals)})"
                    )
                elif (not np.allclose(ds[lat].values, ref_lat_vals) or
                      not np.allclose(ds[lon].values, ref_lon_vals)):
                    results[path.name] = "FAIL"
                    logger.warning(
                        f"Grid consistency FAIL: {path.name} lat/lon values "
                        f"differ from reference {ref_file}"
                    )
                else:
                    results[path.name] = "OK"
        except Exception as exc:
            logger.warning(f"Grid consistency error on {path.name}: {exc}")
            results[path.name] = "FAIL"

    for path, _ in paths_and_vars:
        if path.name not in results:
            results[path.name] = "MISSING"

    results["overall"] = "FAIL" if any(v == "FAIL" for v in results.values()) else "OK"
    return results
