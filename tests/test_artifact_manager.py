"""Tests for agent/artifact_manager.py — path resolution."""

from pathlib import Path
import pytest

from agent.artifact_manager import (
    ROOT,
    RAW_DIR,
    INTER_DIR,
    FINAL_DIR,
    DIAG_DIR,
    MANIFESTS_DIR,
    LOGS_DIR,
    SCRIPTS_DIR,
    raw_agera5,
    raw_chirps,
    raw_isimip,
    intermediate_merged,
    final_output,
    diagnostics_dir,
    diagnostics_qa_plot,
    run_report,
    manifest_path,
    log_path,
    boundary_file,
    shapefile,
    reference_grid_path,
    script,
    ensure_dirs_for,
)


# ── Root / base directory sanity ─────────────────────────────────────────────

class TestBaseDirectories:
    def test_root_is_absolute(self):
        assert ROOT.is_absolute()

    def test_scripts_dir_points_to_scripts_folder(self):
        assert SCRIPTS_DIR.name == "scripts"
        assert SCRIPTS_DIR.parent == ROOT

    def test_raw_dir_under_data(self):
        assert "data" in str(RAW_DIR)

    def test_config_found_at_root(self):
        assert (ROOT / "agent_config.yaml").exists()


# ── raw_* path resolvers ──────────────────────────────────────────────────────

class TestRawPaths:
    def test_raw_agera5_structure(self):
        p = raw_agera5("tas", 2015)
        assert p.parent.name == "tas"
        assert "agera5" in str(p)
        assert "2015" in p.name

    def test_raw_chirps_structure(self):
        p = raw_chirps(2012)
        assert "chirps" in str(p).lower()
        assert "2012" in p.name

    def test_raw_isimip_structure(self):
        p = raw_isimip("gfdl-esm4", "ssp245", "hurs", 2050)
        assert "isimip" in str(p)
        assert "ssp245" in str(p)
        assert "hurs" in str(p)
        assert "2050" in p.name


# ── intermediate_merged ────────────────────────────────────────────────────────

class TestIntermediateMerged:
    def test_historical_uses_agera5_source(self):
        p = intermediate_merged("eth", "rh", "historical", 2010, 2025)
        assert "agera5" in p.name

    def test_projection_uses_isimip_source(self):
        p = intermediate_merged("ken", "tas", "ssp245", 2040, 2070)
        assert "isimip" in p.name
        assert "ssp245" in p.name

    def test_intermediate_is_under_inter_dir(self):
        p = intermediate_merged("eth", "tas", "historical", 2010, 2025)
        assert str(INTER_DIR) in str(p)


# ── final_output ──────────────────────────────────────────────────────────────

class TestFinalOutput:
    def test_final_contains_0p25deg(self):
        p = final_output("eth", "rh", "historical", 2010, 2025)
        assert "0p25deg" in p.name

    def test_final_under_final_dir(self):
        p = final_output("ken", "pr", "ssp245", 2040, 2070)
        assert str(FINAL_DIR) in str(p)

    def test_final_path_contains_all_components(self):
        p = final_output("som", "vpd", "ssp585", 2040, 2070)
        assert "som" in str(p)
        assert "vpd" in str(p)
        assert "ssp585" in str(p)


# ── shapefile ─────────────────────────────────────────────────────────────────

class TestShapefile:
    def test_shapefile_eth_resolves(self):
        p = shapefile("eth")
        assert p.suffix == ".geojson"
        assert "ethiopia" in str(p).lower()

    def test_shapefile_ken_resolves(self):
        p = shapefile("ken")
        assert "kenya" in str(p).lower()

    def test_shapefile_som_resolves(self):
        p = shapefile("som")
        assert "somalia" in str(p).lower()

    def test_unknown_country_raises(self):
        with pytest.raises(ValueError, match="Unknown country code"):
            shapefile("xyz")


# ── script helper ─────────────────────────────────────────────────────────────

class TestScriptHelper:
    def test_script_returns_path_in_scripts_dir(self):
        p = script("run_historical_workflow.py")
        assert p.parent == SCRIPTS_DIR
        assert p.name == "run_historical_workflow.py"


# ── boundary_file (new function name) ────────────────────────────────────────

class TestBoundaryFile:
    def test_eth_resolves_to_geojson(self):
        p = boundary_file("eth")
        assert p.suffix == ".geojson"
        assert "ethiopia" in str(p).lower()

    def test_ken_resolves_to_geojson(self):
        p = boundary_file("ken")
        assert p.suffix == ".geojson"
        assert "kenya" in str(p).lower()

    def test_som_resolves_to_geojson(self):
        p = boundary_file("som")
        assert p.suffix == ".geojson"
        assert "somalia" in str(p).lower()

    def test_unknown_country_raises(self):
        with pytest.raises(ValueError, match="Unknown country code"):
            boundary_file("xyz")

    def test_shapefile_alias_matches_boundary_file(self):
        # shapefile is a backward-compatible alias — both must return identical paths
        assert shapefile("eth") == boundary_file("eth")
        assert shapefile("ken") == boundary_file("ken")
        assert shapefile("som") == boundary_file("som")

    def test_path_is_absolute(self):
        assert boundary_file("eth").is_absolute()


# ── reference_grid_path ───────────────────────────────────────────────────────

class TestReferenceGridPath:
    def test_returns_path_object(self):
        p = reference_grid_path()
        assert isinstance(p, Path)

    def test_path_is_absolute(self):
        assert reference_grid_path().is_absolute()

    def test_path_is_under_project_root(self):
        assert str(ROOT) in str(reference_grid_path())

    def test_path_is_nc_and_exists(self):
        p = reference_grid_path()
        assert p.suffix == ".nc"
        assert p.exists(), f"Reference grid not found: {p}"

    def test_path_is_nc_file(self):
        assert reference_grid_path().suffix == ".nc"


# ── ensure_dirs_for ───────────────────────────────────────────────────────────

class TestEnsureDirsFor:
    def test_creates_parent_and_returns_path(self, tmp_path):
        target = tmp_path / "nested" / "dir" / "file.nc"
        result = ensure_dirs_for(target)
        assert result == target
        assert (tmp_path / "nested" / "dir").is_dir()
