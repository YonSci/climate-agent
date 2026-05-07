"""Tests for agent/policy.py — domain validation, compression, retry, mode,
legacy VPD fallbacks."""

from pathlib import Path
import pytest
from agent.policy import (
    validate_request,
    compression_opts,
    checks_to_skip,
    should_retry,
    retry_wait,
    legacy_vpd_fallbacks,
    SHORT_TO_LONG,
    LONG_TO_SHORT,
    HIST_VAR_ALIAS,
    SCENARIO_TO_SCRIPT,
)


# ── validate_request ──────────────────────────────────────────────────────────

class TestValidateRequest:
    def test_valid_historical(self):
        validate_request(["eth", "ken"], ["tas", "rh"], "historical", (2010, 2025))

    def test_valid_projection(self):
        validate_request(["som"], ["pr", "vpd"], "ssp245", (2040, 2070))

    def test_invalid_country_raises(self):
        with pytest.raises(ValueError, match="Unknown country"):
            validate_request(["xxx"], ["tas"], "historical", (2010, 2020))

    def test_invalid_variable_raises(self):
        with pytest.raises(ValueError, match="Unknown variable"):
            validate_request(["eth"], ["wind"], "historical", (2010, 2020))

    def test_invalid_scenario_raises(self):
        with pytest.raises(ValueError, match="Unknown scenario"):
            validate_request(["eth"], ["tas"], "rcp45", (2010, 2020))

    def test_inverted_period_raises(self):
        with pytest.raises(ValueError, match="period start"):
            validate_request(["eth"], ["tas"], "historical", (2025, 2010))

    def test_equal_period_ok(self):
        # Single-year period is valid
        validate_request(["eth"], ["pr"], "historical", (2010, 2010))

    def test_all_countries_accepted(self):
        validate_request(["eth", "ken", "som"], ["tas"], "ssp585", (2040, 2070))

    def test_all_variables_accepted(self):
        validate_request(["eth"], ["tas", "rh", "vpd", "pr"], "ssp245", (2040, 2070))


# ── compression_opts ──────────────────────────────────────────────────────────

class TestCompressionOpts:
    def test_intermediate_strict(self):
        opts = compression_opts("intermediate", fast_mode=False)
        assert opts["zlib"] is True
        assert isinstance(opts["complevel"], int)

    def test_final_strict_higher_than_intermediate(self):
        inter = compression_opts("intermediate", fast_mode=False)
        final = compression_opts("final",        fast_mode=False)
        assert final["complevel"] >= inter["complevel"]

    def test_fast_mode_final_low_compression(self):
        fast = compression_opts("final", fast_mode=True)
        strict = compression_opts("final", fast_mode=False)
        # fast mode must not exceed strict complevel
        assert fast["complevel"] <= strict["complevel"]


# ── checks_to_skip ────────────────────────────────────────────────────────────

class TestChecksToSkip:
    def test_strict_skips_nothing(self):
        assert checks_to_skip(False) == set()

    def test_fast_skips_grid_and_bounds(self):
        skipped = checks_to_skip(True)
        assert "grid_match"     in skipped
        assert "spatial_bounds" in skipped


# ── retry policy ─────────────────────────────────────────────────────────────

class TestRetryPolicy:
    def test_first_attempt_retryable(self):
        assert should_retry(exit_code=1, attempt=1) is True

    def test_third_attempt_no_retry(self):
        assert should_retry(exit_code=1, attempt=3) is False

    def test_exit_code_2_not_retryable(self):
        assert should_retry(exit_code=2, attempt=1) is False

    def test_backoff_increases(self):
        w1 = retry_wait(1)
        w2 = retry_wait(2)
        assert w2 >= w1


# ── name translation maps ─────────────────────────────────────────────────────

class TestNameMaps:
    def test_short_to_long_complete(self):
        assert SHORT_TO_LONG == {"eth": "ethiopia", "ken": "kenya", "som": "somalia"}

    def test_long_to_short_inverse(self):
        for short, long in SHORT_TO_LONG.items():
            assert LONG_TO_SHORT[long] == short

    def test_hist_var_alias_maps_tas(self):
        assert HIST_VAR_ALIAS["tas"] == "temp"

    def test_hist_var_alias_passthrough(self):
        for v in ("rh", "vpd", "pr"):
            assert HIST_VAR_ALIAS[v] == v

    def test_scenario_to_script_adds_underscore(self):
        assert SCENARIO_TO_SCRIPT["ssp245"] == "ssp_245"
        assert SCENARIO_TO_SCRIPT["ssp585"] == "ssp_585"
        assert SCENARIO_TO_SCRIPT["historical"] == "historical"


# ── legacy_vpd_fallbacks ──────────────────────────────────────────────────────

class TestLegacyVpdFallbacks:
    def test_returns_list_of_paths(self):
        result = legacy_vpd_fallbacks("eth", "ssp245", 2040, 2070)
        assert isinstance(result, list)
        assert len(result) >= 1
        assert all(isinstance(p, Path) for p in result)

    def test_first_path_contains_scenario(self):
        paths = legacy_vpd_fallbacks("eth", "ssp245", 2040, 2070)
        assert "ssp245" in str(paths[0])

    def test_second_path_omits_scenario(self):
        paths = legacy_vpd_fallbacks("eth", "ssp245", 2040, 2070)
        assert "ssp245" not in str(paths[1])

    def test_year_range_in_all_paths(self):
        paths = legacy_vpd_fallbacks("ken", "ssp585", 2031, 2060)
        for p in paths:
            assert "2031" in str(p) and "2060" in str(p)

    def test_country_code_in_all_paths(self):
        paths = legacy_vpd_fallbacks("som", "ssp245", 2040, 2070)
        assert all("som" in str(p) for p in paths)

    def test_all_paths_end_with_nc(self):
        paths = legacy_vpd_fallbacks("eth", "ssp585", 2020, 2050)
        assert all(str(p).endswith(".nc") for p in paths)

    def test_retry_wait_clamps_to_last_backoff(self):
        assert retry_wait(99) == retry_wait(3)

    def test_retry_wait_returns_float(self):
        assert isinstance(retry_wait(1), float)

    def test_should_retry_exit2_hard_failure(self):
        assert should_retry(exit_code=2, attempt=1) is False

    def test_should_retry_max_attempts_boundary(self):
        assert should_retry(exit_code=1, attempt=2) is True
        assert should_retry(exit_code=1, attempt=3) is False
