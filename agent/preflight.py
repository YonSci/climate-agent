"""
preflight.py — Pre-execution environment and data availability checks.

run_preflight() must pass before any pipeline stage is launched.
All failures are collected and reported together so the user can fix
all issues in one pass rather than one at a time.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from pathlib import Path

from agent.artifact_manager import ROOT, SCRIPTS_DIR, BOUNDARIES_DIR
from agent.policy import (
    SHORT_TO_LONG, SCENARIO_TO_SCRIPT,
    HIST_SOURCE_DIRS, ISIMIP_SOURCE_DIR, ISIMIP_SOURCE_VAR,
)

logger = logging.getLogger(__name__)

_REQUIRED_PACKAGES = [
    "xarray", "numpy", "pandas", "scipy",
    "geopandas", "rioxarray", "pyproj", "shapely", "fiona",
    "netCDF4", "h5netcdf", "dask",
    "cdsapi", "matplotlib",
    # cartopy omitted: requires system-level GEOS/PROJ libs and is
    # checked separately in environments where it is expected.
]


@dataclass
class PreflightReport:
    errors:   list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    def __str__(self) -> str:
        lines: list[str] = []
        for e in self.errors:
            lines.append(f"  ERROR   {e}")
        for w in self.warnings:
            lines.append(f"  WARNING {w}")
        return "\n".join(lines) if lines else "  All checks passed."


def check_dependencies() -> dict[str, str]:
    """Return {package: version_or_error_string} for all required packages."""
    import importlib.metadata
    results: dict[str, str] = {}
    for pkg in _REQUIRED_PACKAGES:
        try:
            results[pkg] = importlib.metadata.version(pkg)
        except Exception as exc:
            results[pkg] = f"MISSING ({exc})"
    return results


def check_boundaries(countries: list[str]) -> dict[str, str]:
    """Return {country_code: 'OK'|'MISSING'} for each requested country."""
    from agent.artifact_manager import shapefile as resolve_shp
    results: dict[str, str] = {}
    for code in countries:
        try:
            p = resolve_shp(code)
            results[code] = "OK" if p.exists() else f"MISSING: {p}"
        except ValueError as exc:
            results[code] = f"ERROR: {exc}"
    return results


def check_scripts() -> dict[str, str]:
    """Verify that the key workflow scripts are present in scripts/."""
    required = [
        "run_historical_workflow.py",
        "run_projection_workflow.py",
        "run_future_vpd_workflow.py",
    ]
    return {
        s: "OK" if (SCRIPTS_DIR / s).exists() else f"MISSING: {SCRIPTS_DIR / s}"
        for s in required
    }


def check_source_dirs(request: dict) -> dict[str, str]:
    """
    Verify that source data directories exist for the requested
    country/variable/scenario combinations.
    """
    countries  = request["countries"]
    variables  = request["variables"]
    scenario   = request["scenario"]
    data_root  = ROOT / "data"
    results: dict[str, str] = {}

    for country in countries:
        long = SHORT_TO_LONG[country]

        if scenario == "historical":
            for var in variables:
                src_template = HIST_SOURCE_DIRS.get(var)
                if src_template is None:
                    continue
                d = data_root / src_template.format(country=long)
                key = f"{country}/{var}/{'chirps' if var == 'pr' else 'agera5'}"
                results[key] = "OK" if d.exists() else f"MISSING: {d}"
        else:
            script_scenario = SCENARIO_TO_SCRIPT[scenario]
            for var in variables:
                if var == "vpd":
                    continue  # VPD is derived; its inputs (rh, tas) are checked separately
                src_var = ISIMIP_SOURCE_VAR.get(var, var)
                d = data_root / ISIMIP_SOURCE_DIR.format(
                    country=long, scenario=script_scenario, source_var=src_var
                )
                key = f"{country}/{var}/isimip/{scenario}"
                results[key] = "OK" if d.exists() else f"MISSING: {d}"

    return results


def run_preflight(request: dict) -> PreflightReport:
    """
    Run all preflight checks and return a PreflightReport.

    Checks performed:
    1. Python package dependencies
    2. Workflow scripts present
    3. Country boundary files
    4. Source data directories
    """
    report = PreflightReport()

    # 1 — dependencies
    deps = check_dependencies()
    for pkg, status in deps.items():
        if status.startswith("MISSING"):
            report.errors.append(f"Missing package '{pkg}': {status}")
        else:
            logger.debug(f"  {pkg} {status}")

    # 2 — workflow scripts
    scripts = check_scripts()
    for name, status in scripts.items():
        if status != "OK":
            report.errors.append(f"Workflow script {status}")

    # 3 — boundaries
    boundaries = check_boundaries(request["countries"])
    for code, status in boundaries.items():
        if status != "OK":
            report.warnings.append(f"Boundary file for '{code}': {status}")

    # 4 — source data dirs
    sources = check_source_dirs(request)
    for key, status in sources.items():
        if status != "OK":
            report.errors.append(
                f"Source data missing [{key}]: {status}. "
                "Run the appropriate download script or place source files manually."
            )

    if report.has_errors:
        logger.error(f"Preflight failed:\n{report}")
    elif report.warnings:
        logger.warning(f"Preflight warnings:\n{report}")
    else:
        logger.info("Preflight passed.")

    return report
