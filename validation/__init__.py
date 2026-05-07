"""
validation/ — Quality Plane check functions for the Climate Data Processing Agent.

Submodules:
  schema_checks  — variable presence, units, non-NaN coverage
  time_checks    — time coverage, daily axis
  spatial_checks — grid match, spatial bounds, grid consistency
  anomaly_checks — outlier detection, distribution shape

The orchestrating ValidationEngine class lives in agent.validation_engine and
imports from these submodules. Do not import agent.validation_engine here —
that would create a circular dependency.

All public check functions are re-exported here so callers can use either:
    from validation import check_variable_present
    from validation.schema_checks import check_variable_present   # also works
"""

from validation.schema_checks import (
    check_variable_present,
    check_units,
    check_non_nan_coverage,
)
from validation.time_checks import (
    check_time_coverage,
    check_daily_axis,
)
from validation.spatial_checks import (
    check_grid_match,
    check_spatial_bounds,
    check_grid_consistency,
)
from validation.anomaly_checks import (
    check_anomaly,
    check_distribution,
)

__all__ = [
    "check_variable_present",
    "check_units",
    "check_non_nan_coverage",
    "check_time_coverage",
    "check_daily_axis",
    "check_grid_match",
    "check_spatial_bounds",
    "check_grid_consistency",
    "check_anomaly",
    "check_distribution",
]
