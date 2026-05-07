"""
isimip.py — ISIMIP projection source connector.

Checks the presence of ISIMIP multi-model projection files for a given
country / scenario / variable combination.

Source layout (matches run_projection_workflow.py):
  data/projection_data/isimip-download-{country}/{scenario}/{source_var}/*.nc

Canonical variable → ISIMIP source variable mapping:
  rh  → hurs
  pr  → pr
  tas → tas
"""

from __future__ import annotations
import logging
from pathlib import Path

from agent.artifact_manager import ROOT
from agent.policy import SHORT_TO_LONG, SCENARIO_TO_SCRIPT

logger = logging.getLogger(__name__)

_DATA_ROOT = ROOT / "data" / "projection_data"

# Canonical agent variable → ISIMIP source variable name (directory/filename)
SOURCE_VAR = {"rh": "hurs", "pr": "pr", "tas": "tas"}


def source_dir(country: str, scenario: str, variable: str) -> Path:
    """
    Resolve the ISIMIP source directory.

    Parameters
    ----------
    country  : short code (eth, ken, som)
    scenario : canonical scenario (ssp245, ssp585)
    variable : canonical variable (rh, pr, tas)
    """
    if variable not in SOURCE_VAR:
        raise ValueError(
            f"ISIMIP connector does not handle variable {variable!r}. "
            f"Valid: {list(SOURCE_VAR)}"
        )
    long            = SHORT_TO_LONG[country]
    script_scenario = SCENARIO_TO_SCRIPT[scenario]
    src_var         = SOURCE_VAR[variable]
    return _DATA_ROOT / f"isimip-download-{long}" / script_scenario / src_var


def files_present(country: str, scenario: str, variable: str) -> list[Path]:
    """Return sorted list of ISIMIP .nc files for the given slice."""
    d = source_dir(country, scenario, variable)
    if not d.exists():
        return []
    return sorted(d.glob("*.nc"))


def is_source_available(country: str, scenario: str, variable: str) -> bool:
    """Return True if at least one ISIMIP source file exists."""
    return len(files_present(country, scenario, variable)) > 0


def year_ranges_present(country: str, scenario: str,
                         variable: str) -> list[tuple[int, int]]:
    """
    Parse year ranges from ISIMIP filenames.

    ISIMIP files follow the convention: ..._{start}_{end}.nc
    Returns sorted list of (start_year, end_year) tuples.
    """
    ranges: list[tuple[int, int]] = []
    for f in files_present(country, scenario, variable):
        stem_parts = f.stem.rsplit("_", 2)
        if len(stem_parts) >= 3:
            try:
                y1, y2 = int(stem_parts[-2]), int(stem_parts[-1])
                if 1900 < y1 < 2200 and 1900 < y2 < 2200:
                    ranges.append((y1, y2))
            except ValueError:
                pass
    return sorted(ranges)


def covers_period(country: str, scenario: str, variable: str,
                  year_start: int, year_end: int) -> bool:
    """
    Return True if the available ISIMIP files span the full requested period.
    Checks by union of year ranges, not by individual year.
    """
    covered: set[int] = set()
    for y1, y2 in year_ranges_present(country, scenario, variable):
        covered.update(range(y1, y2 + 1))
    return all(y in covered for y in range(year_start, year_end + 1))
