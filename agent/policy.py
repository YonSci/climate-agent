"""
policy.py — Naming governance, compression, retry, and fast-mode policies.

Loaded once at agent startup. All pipeline decisions involving naming rules,
compression levels, retry behaviour, or mode selection go through this module.
"""

from __future__ import annotations
import yaml
import time
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_CONFIG_PATH  = _PROJECT_ROOT / "agent_config.yaml"

VALID_COUNTRIES = {"eth", "ken", "som"}
VALID_SCENARIOS = {"historical", "ssp245", "ssp585"}
VALID_VARIABLES = {"tas", "rh", "vpd", "pr"}
VALID_MODES     = {"strict", "fast"}

# Country name translations: short code ↔ full name used by workflow scripts
SHORT_TO_LONG = {"eth": "ethiopia", "ken": "kenya", "som": "somalia"}
LONG_TO_SHORT = {v: k for k, v in SHORT_TO_LONG.items()}

# Historical workflow uses "temp" for temperature; all other workflows use "tas"
HIST_VAR_ALIAS = {"tas": "temp", "rh": "rh", "vpd": "vpd", "pr": "pr"}

# Scenario format used by projection/VPD script CLI flags (adds underscore)
SCENARIO_TO_SCRIPT = {"ssp245": "ssp_245", "ssp585": "ssp_585", "historical": "historical"}


def _load_config() -> dict:
    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f)


_cfg = _load_config()


# ── Domain validation ─────────────────────────────────────────────────────────

def validate_request(countries: list[str], variables: list[str],
                     scenario: str, period: tuple[int, int]) -> None:
    """Raise ValueError with actionable message on any invalid request field."""
    bad_c = set(countries) - VALID_COUNTRIES
    if bad_c:
        raise ValueError(
            f"Unknown country code(s): {bad_c}. Valid: {VALID_COUNTRIES}")

    bad_v = set(variables) - VALID_VARIABLES
    if bad_v:
        raise ValueError(
            f"Unknown variable(s): {bad_v}. Valid: {VALID_VARIABLES}")

    if scenario not in VALID_SCENARIOS:
        raise ValueError(
            f"Unknown scenario: {scenario!r}. Valid: {VALID_SCENARIOS}")

    if period[0] > period[1]:
        raise ValueError(f"period start {period[0]} > end {period[1]}")


# ── Compression policy ────────────────────────────────────────────────────────

def compression_opts(artifact_type: str, fast_mode: bool = False) -> dict:
    """
    Return xarray encoding compression kwargs for a given artifact type.
    artifact_type: 'intermediate' | 'final'
    """
    comp_cfg = _cfg["compression"]
    if fast_mode and artifact_type == "final":
        c = comp_cfg["fast_mode_override"]
    else:
        c = comp_cfg.get(artifact_type, comp_cfg["intermediate"])
    return {"zlib": c.get("zlib", True), "complevel": c.get("complevel", 1)}


# ── Validation mode ───────────────────────────────────────────────────────────

def checks_to_skip(fast_mode: bool) -> set[str]:
    """Return the set of validation check names to skip in the current mode."""
    if not fast_mode:
        return set()
    return set(_cfg["validation"].get("fast_mode_skip", []))


# ── Retry policy ──────────────────────────────────────────────────────────────

def should_retry(exit_code: int, attempt: int) -> bool:
    retry_cfg = _cfg["retry"]
    retryable = set(retry_cfg.get("retryable_exit_codes", [1]))
    max_attempts = retry_cfg.get("max_attempts", 3)
    return exit_code in retryable and attempt < max_attempts


def retry_wait(attempt: int) -> float:
    """Return seconds to wait before attempt N (1-indexed)."""
    backoffs = _cfg["retry"].get("backoff_seconds", [30, 60, 120])
    idx = min(attempt - 1, len(backoffs) - 1)
    return float(backoffs[idx])


def wait_before_retry(attempt: int) -> None:
    wait = retry_wait(attempt)
    logger.info(f"Retrying in {wait:.0f}s (attempt {attempt})…")
    time.sleep(wait)


# ── Legacy filename fallbacks ─────────────────────────────────────────────────

def legacy_vpd_fallbacks(country: str, scenario: str,
                          year_start: int, year_end: int) -> list[Path]:
    """
    Return ordered list of legacy file path patterns to try when the canonical
    0.25-degree clipped VPD input is not found.
    """
    from agent.artifact_manager import INTER_DIR
    return [
        INTER_DIR / country / "vpd" /
            f"vpd_{country}_{scenario}_daily_{year_start}-{year_end}.nc",
        INTER_DIR / country / "vpd" /
            f"vpd_{country}_daily_{year_start}-{year_end}.nc",
    ]
