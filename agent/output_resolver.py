"""
output_resolver.py — Resolves the expected output files for each workflow stage.

Path conventions here mirror the workflow scripts exactly.
- run_historical_workflow.py  → historical_outputs()
- run_projection_workflow.py  → projection_outputs()
- run_future_vpd_workflow.py  → vpd_outputs()

run_historical_workflow.py now uses dynamic period labels derived from --start-year
and --end-year, so output filenames reflect the actual requested period.  The
legacy_path fallback (_HIST_LEGACY_PERIOD = 2010_2025) handles files produced by
older versions of the script that had a hardcoded period label; the orchestrator
renames them automatically if the primary path is absent and the legacy path exists.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from agent.artifact_manager import ROOT, reference_grid_path
from agent.policy import SHORT_TO_LONG, SCENARIO_TO_SCRIPT

# Matches MERGED_DIR in all three workflow scripts
_MERGED_DIR = ROOT / "data" / "merged_files"

# ── Historical conventions (from run_historical_workflow.py VARIABLE_CONFIG) ──

# Script variable name used in the output filename (pr, rh, temp, vpd)
_HIST_SCRIPT_VAR: dict[str, str] = {
    "pr": "pr", "rh": "rh", "tas": "temp", "vpd": "vpd",
}
# NetCDF data variable name inside the file
_HIST_FINAL_VAR: dict[str, str] = {
    "pr": "precip", "rh": "rh", "tas": "t2m", "vpd": "vpd",
}
_HIST_UNITS: dict[str, Optional[str]] = {
    "pr": "mm/day", "rh": None, "tas": None, "vpd": "hPa",
}

# ── Projection conventions (from run_projection_workflow.py VARIABLE_CONFIG) ─

_PROJ_VAR_NAME: dict[str, str] = {"rh": "rh", "pr": "pr", "tas": "tas"}
_PROJ_UNITS: dict[str, Optional[str]] = {
    "rh": None, "pr": "mm/day", "tas": "degC",
}

# ── Valid data ranges by internal variable name (for anomaly detection) ────────
# tas/t2m excluded: range depends on units (K for historical, degC for projection)
_VALID_RANGE: dict[str, tuple[float, float]] = {
    "precip": (0.0, 500.0),
    "pr":     (0.0, 500.0),
    "rh":     (0.0, 100.0),
    "vpd":    (0.0, 80.0),
}


@dataclass
class ExpectedOutput:
    """One NetCDF file the agent expects a workflow stage to produce."""
    path: Path
    variable: str                             # NetCDF data variable name inside the file
    expected_units: Optional[str]             # None → skip units check
    period: tuple[int, int]
    require_daily_axis: bool = True           # all final outputs should be daily
    target_grid_path: Optional[Path] = None  # reference grid for grid_match / spatial_bounds
    valid_range: Optional[tuple[float, float]] = None  # for anomaly detection
    legacy_path: Optional[Path] = None       # hardcoded-period fallback (historical only)
    is_clipped: bool = False                  # True for country-masked outputs; non-NaN
                                              # coverage measured vs land pixels, not bbox


_HIST_LEGACY_PERIOD = (2010, 2025)  # files produced before dynamic period labelling


def historical_outputs(
    countries: list[str],
    variables: list[str],
    period: tuple[int, int],
) -> list[ExpectedOutput]:
    """
    Expected clipped outputs from run_historical_workflow.py.

    run_historical_workflow.py uses dynamic period labels, so output filenames
    reflect the actual requested period.  legacy_path points to the '2010_2025'
    variant for backwards compatibility with files produced by older script versions;
    the orchestrator renames them automatically when the primary path is absent.
    """
    period_label = f"{period[0]}_{period[1]}"
    legacy_label = f"{_HIST_LEGACY_PERIOD[0]}_{_HIST_LEGACY_PERIOD[1]}"
    outputs: list[ExpectedOutput] = []
    for country in countries:
        long = SHORT_TO_LONG[country]
        # Per-country reference grid: the clipped pr output shares the same
        # lat/lon as all other clipped outputs for that country.
        # Falls back to None when the pr file hasn't been produced yet.
        pr_ref = _MERGED_DIR / f"{long}_pr_{period_label}_025deg_clipped.nc"
        ref = pr_ref if pr_ref.exists() else None
        for var in variables:
            script_var = _HIST_SCRIPT_VAR[var]
            final_var  = _HIST_FINAL_VAR[var]
            path = _MERGED_DIR / f"{long}_{script_var}_{period_label}_025deg_clipped.nc"
            # Legacy fallback: files produced before dynamic period labelling used 2010_2025.
            # Only set legacy_path when it would differ from the primary path.
            legacy: Optional[Path] = None
            if period != _HIST_LEGACY_PERIOD:
                legacy = _MERGED_DIR / f"{long}_{script_var}_{legacy_label}_025deg_clipped.nc"
            outputs.append(ExpectedOutput(
                path=path,
                variable=final_var,
                expected_units=_HIST_UNITS[var],
                period=period,
                require_daily_axis=True,
                target_grid_path=ref,
                valid_range=_VALID_RANGE.get(final_var),
                legacy_path=legacy,
                is_clipped=True,
            ))
    return outputs


def projection_outputs(
    countries: list[str],
    variables: list[str],
    scenario: str,
    period: tuple[int, int],
) -> list[ExpectedOutput]:
    """Expected clipped outputs from run_projection_workflow.py."""
    script_scenario = SCENARIO_TO_SCRIPT[scenario]       # ssp_245 | ssp_585
    scenario_label  = script_scenario.replace("_", "")   # ssp245  | ssp585
    span = f"{period[0]}_{period[1]}"
    outputs: list[ExpectedOutput] = []
    for country in countries:
        long = SHORT_TO_LONG[country]
        for var in variables:
            var_name = _PROJ_VAR_NAME[var]
            prefix   = f"{long}_{var}_{scenario_label}"
            # ssp_585 precipitation uses a different suffix (daily_clipped)
            if script_scenario == "ssp_585" and var == "pr":
                path = _MERGED_DIR / f"{prefix}_{span}_daily_clipped.nc"
            else:
                path = _MERGED_DIR / f"{prefix}_{span}_025deg_clipped.nc"
            outputs.append(ExpectedOutput(
                path=path,
                variable=var_name,
                expected_units=_PROJ_UNITS[var],
                period=period,
                require_daily_axis=True,
                target_grid_path=None,  # projection outputs use a different reference
                valid_range=_VALID_RANGE.get(var_name),
                is_clipped=True,
            ))
    return outputs


def vpd_outputs(
    countries: list[str],
    scenario: str,
    period: tuple[int, int],
) -> list[ExpectedOutput]:
    """Expected outputs from run_future_vpd_workflow.py."""
    script_scenario = SCENARIO_TO_SCRIPT[scenario]
    scenario_label  = script_scenario.replace("_", "")
    span = f"{period[0]}_{period[1]}"
    outputs: list[ExpectedOutput] = []
    for country in countries:
        long = SHORT_TO_LONG[country]
        if script_scenario == "ssp_245":
            path = _MERGED_DIR / f"{long}_vpd_{scenario_label}_{span}_025deg_clipped.nc"
        else:
            path = _MERGED_DIR / f"{long}_vpd_{scenario_label}_{span}_daily.nc"
        outputs.append(ExpectedOutput(
            path=path,
            variable="vpd",
            expected_units="hPa",
            period=period,
            require_daily_axis=True,
            target_grid_path=None,
            valid_range=_VALID_RANGE.get("vpd"),
            is_clipped=True,
        ))
    return outputs
