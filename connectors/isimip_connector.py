"""
isimip_connector.py — Path resolver and command builder for ISIMIP projection data.

ISIMIP files are not downloaded via a script — they are obtained from the ISIMIP
data portal and placed manually into the expected directory layout. This connector
provides path resolution and availability checks so the orchestrator can verify
source data before launching projection workflows.

Directory layout expected on disk:
  data/projection_data/isimip-download-{country}/{scenario}/{source_var}/
      {model}_{variant}_{bias}_{scenario}_{source_var}_lon{w}to{e}lat{s}to{n}_daily_{ys}_{ye}.nc

Source variable mapping (ISIMIP name → agent canonical name):
  hurs → rh
  tas  → tas
  pr   → pr
"""

from __future__ import annotations
from pathlib import Path

from agent.artifact_manager import ROOT
from agent.policy import SHORT_TO_LONG, SCENARIO_TO_SCRIPT

# Maps agent variable → ISIMIP source variable name
AGENT_TO_ISIMIP: dict[str, str] = {
    "rh":  "hurs",
    "tas": "tas",
    "pr":  "pr",
}

# Maps agent variable → ISIMIP source variable name (reverse)
ISIMIP_TO_AGENT: dict[str, str] = {v: k for k, v in AGENT_TO_ISIMIP.items()}


def _isimip_source_dir(country: str, scenario: str, variable: str) -> Path:
    """
    Return the directory where ISIMIP files for country/scenario/variable reside.

    Parameters
    ----------
    country  : short code (eth | ken | som)
    scenario : agent scenario string (ssp245 | ssp585)
    variable : agent canonical variable (rh | tas | pr)
    """
    long_country   = SHORT_TO_LONG[country]
    script_scenario = SCENARIO_TO_SCRIPT[scenario]   # ssp_245 | ssp_585
    source_var     = AGENT_TO_ISIMIP[variable]
    return (
        ROOT / "data" / "projection_data"
        / f"isimip-download-{long_country}"
        / script_scenario
        / source_var
    )


def source_dir(country: str, scenario: str, variable: str) -> Path:
    """Public accessor for the ISIMIP source directory."""
    return _isimip_source_dir(country, scenario, variable)


def list_available_files(country: str, scenario: str, variable: str) -> list[Path]:
    """
    Return all NetCDF files present in the ISIMIP source directory,
    sorted by filename (which encodes the year span).
    """
    d = _isimip_source_dir(country, scenario, variable)
    if not d.exists():
        return []
    return sorted(d.glob("*.nc"))


def check_availability(
    countries: list[str],
    scenarios: list[str],
    variables: list[str],
) -> dict[str, str]:
    """
    Return {key: "OK"|"MISSING: <path>"} for every country/scenario/variable
    combination, where key = "{country}/{scenario}/{variable}".

    Raises ValueError for unsupported variable codes.
    """
    results: dict[str, str] = {}
    for country in countries:
        for scenario in scenarios:
            for variable in variables:
                if variable not in AGENT_TO_ISIMIP:
                    results[f"{country}/{scenario}/{variable}"] = (
                        f"ERROR: variable {variable!r} not supported by ISIMIP connector "
                        f"(supported: {sorted(AGENT_TO_ISIMIP)})"
                    )
                    continue
                d = _isimip_source_dir(country, scenario, variable)
                files = list_available_files(country, scenario, variable)
                key = f"{country}/{scenario}/{variable}"
                if not d.exists():
                    results[key] = f"MISSING: {d}"
                elif not files:
                    results[key] = f"MISSING: no *.nc files in {d}"
                else:
                    results[key] = f"OK ({len(files)} file(s))"
    return results
