"""
Shared pytest fixtures for the climate agent test suite.

All file-backed fixtures call pytest.skip() when the real data file is absent
so the test suite remains runnable in environments without the full dataset.
"""

from __future__ import annotations
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR     = PROJECT_ROOT / "data"


def _require(path: Path) -> Path:
    """Skip the test if *path* does not exist on disk."""
    if not path.exists():
        pytest.skip(f"Test data file not found: {path}")
    return path


# ── CHIRPS files ──────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def chirps_eth_2010() -> Path:
    """Annual CHIRPS precipitation file for Ethiopia, 2010."""
    return _require(
        DATA_DIR / "ethiopia_chirips" / "chirps-v2.0.2010.days_p25.nc"
    )


@pytest.fixture(scope="session")
def chirps_eth_2011() -> Path:
    return _require(
        DATA_DIR / "ethiopia_chirips" / "chirps-v2.0.2011.days_p25.nc"
    )


# ── AgERA5 files ──────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def agera5_rh_eth_first() -> Path:
    """First daily AgERA5 relative-humidity file for Ethiopia."""
    d = DATA_DIR / "ethiopia_relative_humidity_mean" / "netcdf"
    if not d.exists():
        pytest.skip(f"AgERA5 RH directory not found: {d}")
    files = sorted(d.glob("*.nc"))
    if not files:
        pytest.skip("No AgERA5 RH files found")
    return files[0]


@pytest.fixture(scope="session")
def agera5_rh_eth_dir() -> Path:
    """Directory containing AgERA5 RH netcdf files for Ethiopia."""
    d = DATA_DIR / "ethiopia_relative_humidity_mean" / "netcdf"
    if not d.exists():
        pytest.skip(f"AgERA5 RH directory not found: {d}")
    return d


# ── ISIMIP projection files ───────────────────────────────────────────────────

@pytest.fixture(scope="session")
def isimip_eth_ssp245_hurs() -> Path:
    """ISIMIP daily hurs file for Ethiopia ssp245 2031-2040."""
    return _require(
        DATA_DIR
        / "projection_data"
        / "isimip-download-ethiopia"
        / "ssp_245"
        / "hurs"
        / "gfdl-esm4_r1i1p1f1_w5e5_ssp245_hurs_lon33.0to48.0lat3.0to15.0_daily_2031_2040.nc"
    )


@pytest.fixture(scope="session")
def isimip_eth_ssp245_tas() -> Path:
    """ISIMIP daily tas file for Ethiopia ssp245 2031-2040."""
    return _require(
        DATA_DIR
        / "projection_data"
        / "isimip-download-ethiopia"
        / "ssp_245"
        / "tas"
        / "gfdl-esm4_r1i1p1f1_w5e5_ssp245_tas_lon33.0to48.0lat3.0to15.0_daily_2031_2040.nc"
    )


@pytest.fixture(scope="session")
def isimip_eth_ssp245_dir() -> Path:
    """ISIMIP hurs source directory for Ethiopia ssp245."""
    d = DATA_DIR / "projection_data" / "isimip-download-ethiopia" / "ssp_245" / "hurs"
    if not d.exists():
        pytest.skip(f"ISIMIP directory not found: {d}")
    return d
