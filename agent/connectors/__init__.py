"""
agent/connectors/ — Source availability checkers (higher-level than connectors/).

These modules check whether source data is present on disk and expose
availability metadata (year coverage, missing years, etc.). They delegate
download command construction to the top-level connectors/ package.

Import guide
------------
- To BUILD subprocess commands for downloads  → use connectors.agera5_connector etc.
- To CHECK source data availability on disk   → use agent.connectors.agera5 etc.

Both packages are kept separate so the availability checks (which import
agent.artifact_manager) stay independent of the command-builders (which only
need the path helpers). This prevents circular imports in the orchestrator.
"""

from agent.connectors import agera5, chirps, isimip

__all__ = ["agera5", "chirps", "isimip"]
