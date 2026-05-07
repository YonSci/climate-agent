"""
connectors/ — Download command builders for AgERA5, CHIRPS, and ISIMIP.

These modules construct the subprocess command lists passed to orchestrator.py.
They do NOT check disk availability — that is handled by agent.connectors.

Modules
-------
agera5_connector  — build_cmd(), expected_path(), year_range_cmds() for AgERA5
chirps_connector  — build_cmd(), expected_path(), year_range_cmds() for CHIRPS
isimip_connector  — source_dir(), list_available_files(), check_availability() for ISIMIP
"""
