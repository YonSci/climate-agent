"""
chirps_connector.py — Command builder for download_chirps.py.

Wraps the CLI of scripts/download_chirps.py so callers never construct
command strings manually. The script itself is treated as a black box.
"""

from __future__ import annotations
import sys
from pathlib import Path

from agent.artifact_manager import SCRIPTS_DIR, raw_chirps

# CHIRPS version string embedded in filenames
CHIRPS_VERSION = "v2.0"

# Resolution variant produced by the pipeline (0.25-degree daily)
CHIRPS_SUFFIX = "days_p25.nc"


def build_cmd(year: int) -> list[str]:
    """
    Return a subprocess command list to download one year of CHIRPS precipitation.

    Parameters
    ----------
    year : calendar year to download
    """
    out_dir = raw_chirps(year).parent
    return [
        sys.executable,
        str(SCRIPTS_DIR / "download_chirps.py"),
        "--year",   str(year),
        "--outdir", str(out_dir),
    ]


def expected_path(year: int) -> Path:
    """Return the path where download_chirps.py will write its output."""
    return raw_chirps(year)


def year_range_cmds(year_start: int, year_end: int) -> list[list[str]]:
    """Return one command list per year in [year_start, year_end]."""
    return [build_cmd(y) for y in range(year_start, year_end + 1)]
