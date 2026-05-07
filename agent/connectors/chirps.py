"""
chirps.py — CHIRPS precipitation source connector.

Checks what annual CHIRPS files are present for a given country,
and triggers downloads via download_chirps.py when files are missing.

Source layout (matches existing workflow scripts):
  data/{country}_chirips/chirps-v2.0.{YYYY}.days_p25.nc
"""

from __future__ import annotations
import logging
import subprocess
import sys
from pathlib import Path

from agent.artifact_manager import ROOT, SCRIPTS_DIR
from agent.policy import SHORT_TO_LONG

logger = logging.getLogger(__name__)

_DATA_ROOT = ROOT / "data"


def source_dir(country: str) -> Path:
    """Resolve the CHIRPS source directory for a country."""
    long = SHORT_TO_LONG[country]
    return _DATA_ROOT / f"{long}_chirips"


def files_present(country: str) -> list[Path]:
    """Return sorted list of annual CHIRPS .nc files."""
    d = source_dir(country)
    if not d.exists():
        return []
    return sorted(d.glob("chirps-v2.0.*.days_p25.nc"))


def is_source_available(country: str, year_start: int, year_end: int) -> bool:
    """Return True if all years in [year_start, year_end] are present."""
    present_years = year_coverage(country)
    return all(y in present_years for y in range(year_start, year_end + 1))


def year_coverage(country: str) -> set[int]:
    """Return the set of years for which CHIRPS files exist."""
    years: set[int] = set()
    for f in files_present(country):
        # chirps-v2.0.{YYYY}.days_p25.nc
        parts = f.stem.split(".")
        for part in parts:
            if len(part) == 4 and part.isdigit():
                years.add(int(part))
    return years


def missing_years(country: str, year_start: int, year_end: int) -> list[int]:
    """Return years in [year_start, year_end] that have no CHIRPS file."""
    present = year_coverage(country)
    return [y for y in range(year_start, year_end + 1) if y not in present]


def download(country: str, year_start: int, year_end: int,
             dry_run: bool = False) -> bool:
    """
    Download CHIRPS files for the requested year range via download_chirps.py.

    Returns True on success, False on failure.
    """
    script = SCRIPTS_DIR / "download_chirps.py"
    if not script.exists():
        logger.error(f"Download script not found: {script}")
        return False

    long = SHORT_TO_LONG[country]
    cmd = [
        sys.executable, str(script),
        "--country", long,
        "--start-year", str(year_start),
        "--end-year",   str(year_end),
    ]
    logger.info(f"CHIRPS download: {' '.join(cmd)}")
    if dry_run:
        return True

    result = subprocess.run(cmd, cwd=str(ROOT))
    return result.returncode == 0
