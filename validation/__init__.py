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
"""
