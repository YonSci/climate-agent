"""
artifact_manager.py — Centralized file path resolver for all pipeline artifacts.

ALL code in this project must call these functions to resolve paths.
Never construct file paths manually outside this module.
"""

from __future__ import annotations
from pathlib import Path
import yaml

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_CONFIG_PATH  = _PROJECT_ROOT / "agent_config.yaml"


def _load_config() -> dict:
    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f)


_cfg = _load_config()
_p   = _cfg["paths"]


# ── Base directories ──────────────────────────────────────────────────────────

ROOT           = _PROJECT_ROOT
RAW_DIR        = ROOT / _p["data_raw"]
INTER_DIR      = ROOT / _p["data_intermediate"]
FINAL_DIR      = ROOT / _p["data_final"]
DIAG_DIR       = ROOT / _p["data_diagnostics"]
MANIFESTS_DIR  = ROOT / _p["runs_manifests"]
LOGS_DIR       = ROOT / _p["runs_logs"]
SCRIPTS_DIR    = ROOT / _p["scripts"]
BOUNDARIES_DIR = ROOT / _p["boundaries"]


# ── Path resolvers ────────────────────────────────────────────────────────────

def raw_agera5(variable: str, year: int) -> Path:
    """data/raw/agera5/{variable}/{variable}_agera5_{YYYY}.nc"""
    return RAW_DIR / "agera5" / variable / f"{variable}_agera5_{year}.nc"


def raw_chirps(year: int) -> Path:
    """data/raw/chirps/chirps_v2.0_{YYYY}.days_p05.nc"""
    return RAW_DIR / "chirps" / f"chirps_v2.0_{year}.days_p05.nc"


def raw_isimip(model: str, scenario: str, variable: str, year: int) -> Path:
    """data/raw/isimip/{model}/{scenario}/{variable}/{variable}_{model}_{scenario}_{YYYY}.nc"""
    return RAW_DIR / "isimip" / model / scenario / variable / \
           f"{variable}_{model}_{scenario}_{year}.nc"


def intermediate_merged(country: str, variable: str, scenario: str,
                         year_start: int, year_end: int) -> Path:
    """data/intermediate/{country}/{variable}/{variable}_{country}_{source}_merged_{ys}-{ye}.nc"""
    source = "agera5" if scenario == "historical" else f"isimip_{scenario}"
    return INTER_DIR / country / variable / \
           f"{variable}_{country}_{source}_merged_{year_start}-{year_end}.nc"


def final_output(country: str, variable: str, scenario: str,
                 year_start: int, year_end: int) -> Path:
    """data/final/{country}/{scenario}/{variable}/{variable}_{country}_{scenario}_{ys}-{ye}_0p25deg.nc"""
    return FINAL_DIR / country / scenario / variable / \
           f"{variable}_{country}_{scenario}_{year_start}-{year_end}_0p25deg.nc"


def diagnostics_dir(run_id: str) -> Path:
    """data/diagnostics/{run_id}/"""
    d = DIAG_DIR / run_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def diagnostics_qa_plot(run_id: str, country: str, scenario: str, variable: str) -> Path:
    """data/diagnostics/{run_id}/{country}_{scenario}_{variable}_qa.png"""
    return diagnostics_dir(run_id) / f"{country}_{scenario}_{variable}_qa.png"


def run_report(run_id: str) -> Path:
    """data/diagnostics/{run_id}/run_report.json"""
    return diagnostics_dir(run_id) / "run_report.json"


def manifest_path(run_id: str) -> Path:
    """runs/manifests/{run_id}.json"""
    MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)
    return MANIFESTS_DIR / f"{run_id}.json"


def log_path(run_id: str) -> Path:
    """runs/logs/{run_id}.log"""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    return LOGS_DIR / f"{run_id}.log"


def boundary_file(country: str) -> Path:
    """Resolve boundary GeoJSON path for a country by its short code (eth, ken, som)."""
    country_cfg = next(
        (c for c in _cfg["countries"] if c["code"] == country), None
    )
    if country_cfg is None:
        raise ValueError(f"Unknown country code: {country!r}")
    return ROOT / country_cfg["shapefile"]


# Backward-compatible alias
shapefile = boundary_file


def reference_grid_path() -> Path:
    """CHIRPS 0.05-degree reference grid used as the regridding target."""
    return ROOT / _cfg["reference_grid"]["chirps_005deg"]


def script(name: str) -> Path:
    """scripts/{name}"""
    return SCRIPTS_DIR / name


# ── Ensure output directories exist ──────────────────────────────────────────

def ensure_dirs_for(path: Path) -> Path:
    """Create parent directories for a given output path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
