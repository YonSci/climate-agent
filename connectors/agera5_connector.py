"""
agera5_connector.py — Command builder for agera5_download.py.

Wraps the CLI of scripts/agera5_download.py so callers never construct
command strings manually. The script itself is treated as a black box.
"""

from __future__ import annotations
import sys
from pathlib import Path

from agent.artifact_manager import SCRIPTS_DIR, raw_agera5

# AgERA5 variables supported by the download script
SUPPORTED_VARIABLES = frozenset({"tas", "rh", "vpd"})


def build_cmd(variable: str, year: int) -> list[str]:
    """
    Return a subprocess command list to download one AgERA5 variable-year slice.

    Parameters
    ----------
    variable : canonical agent variable name (tas | rh | vpd)
    year     : calendar year to download
    """
    if variable not in SUPPORTED_VARIABLES:
        raise ValueError(
            f"AgERA5 connector: unsupported variable {variable!r}. "
            f"Supported: {sorted(SUPPORTED_VARIABLES)}"
        )
    out_dir = raw_agera5(variable, year).parent
    return [
        sys.executable,
        str(SCRIPTS_DIR / "agera5_download.py"),
        "--variable", variable,
        "--year",     str(year),
        "--outdir",   str(out_dir),
    ]


def expected_path(variable: str, year: int) -> Path:
    """Return the path where agera5_download.py will write its output."""
    return raw_agera5(variable, year)


def year_range_cmds(variable: str, year_start: int, year_end: int) -> list[list[str]]:
    """Return one command list per year in [year_start, year_end]."""
    return [build_cmd(variable, y) for y in range(year_start, year_end + 1)]
