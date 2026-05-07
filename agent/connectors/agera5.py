"""
agera5.py — AgERA5 source connector.

Checks what daily AgERA5 files are present for a given country and variable,
and triggers downloads via agera5_download.py when files are missing.

Source layout (matches existing workflow scripts):
  data/{country}_{variable_dir}/netcdf/*.nc
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

# Maps canonical agent variable name → source directory suffix
_VAR_TO_DIR = {
    "rh":  "{country}_relative_humidity_mean",
    "tas": "{country}_temperature",
    "vpd": "{country}_vapour_pressure_deficit",
}


def source_dir(country: str, variable: str) -> Path:
    """
    Resolve the AgERA5 source directory for a country/variable combination.

    Parameters
    ----------
    country  : short code (eth, ken, som)
    variable : canonical variable name (rh, tas, vpd)
    """
    if variable not in _VAR_TO_DIR:
        raise ValueError(
            f"AgERA5 connector does not handle variable {variable!r}. "
            f"Valid: {list(_VAR_TO_DIR)}"
        )
    long = SHORT_TO_LONG[country]
    return _DATA_ROOT / _VAR_TO_DIR[variable].format(country=long) / "netcdf"


def files_present(country: str, variable: str) -> list[Path]:
    """Return sorted list of .nc files in the AgERA5 source directory."""
    d = source_dir(country, variable)
    if not d.exists():
        return []
    return sorted(d.glob("*.nc"))


def is_source_available(country: str, variable: str) -> bool:
    """Return True if at least one source file exists."""
    return len(files_present(country, variable)) > 0


def year_coverage(country: str, variable: str) -> set[int]:
    """Return the set of years represented by AgERA5 files (parsed from filenames)."""
    years: set[int] = set()
    for f in files_present(country, variable):
        # Filename contains YYYYMMDD; extract YYYY
        for part in f.stem.split("_"):
            if len(part) == 8 and part.isdigit():
                years.add(int(part[:4]))
    return years


def download(country: str, variable: str, year_start: int, year_end: int,
             dry_run: bool = False) -> bool:
    """
    Download AgERA5 files for missing years by calling agera5_download.py.

    Returns True on success, False on failure.
    """
    script = SCRIPTS_DIR / "agera5_download.py"
    if not script.exists():
        logger.error(f"Download script not found: {script}")
        return False

    long = SHORT_TO_LONG[country]
    cmd = [
        sys.executable, str(script),
        "--country", long,
        "--variable", variable,
        "--start-year", str(year_start),
        "--end-year",   str(year_end),
    ]
    logger.info(f"AgERA5 download: {' '.join(cmd)}")
    if dry_run:
        return True

    result = subprocess.run(cmd, cwd=str(ROOT))
    return result.returncode == 0
