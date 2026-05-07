"""
Tests for agent/planner.py — DAG validation and WorkflowPlan consistency checks.
"""

from __future__ import annotations
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.planner import Planner
from agent.task_router import WorkflowPlan, Stage
from agent.output_resolver import ExpectedOutput


# ── helpers ───────────────────────────────────────────────────────────────────

def _exp(path: str, variable: str = "rh") -> ExpectedOutput:
    return ExpectedOutput(
        path=Path(path),
        variable=variable,
        expected_units=None,
        period=(2010, 2025),
    )


def _plan(
    run_type: str = "historical",
    countries: list[str] | None = None,
    variables: list[str] | None = None,
    stages: list[Stage] | None = None,
) -> WorkflowPlan:
    return WorkflowPlan(
        run_type=run_type,
        countries=["eth"] if countries is None else countries,
        variables=["rh"] if variables is None else variables,
        scenario="historical",
        period=(2010, 2025),
        fast_mode=False,
        diagnostics=False,
        workers=1,
        stages=stages or [],
    )


# ── Planner.validate ──────────────────────────────────────────────────────────

class TestPlannerValidate:
    def test_empty_plan_no_issues(self):
        # Empty stages with no variables → nothing to check → no issues
        plan = _plan(variables=[], stages=[])
        issues = Planner().validate(plan)
        assert issues == []

    def test_single_stage_no_issues(self):
        stage = Stage(
            name="historical",
            script="run_historical_workflow.py",
            args=["--country", "ethiopia"],
            expected_outputs=[_exp("data/merged_files/ethiopia_rh_2010_2025_025deg_clipped.nc")],
        )
        issues = Planner().validate(_plan(stages=[stage]))
        assert issues == []

    def test_output_path_collision_detected(self):
        path = "data/merged_files/ethiopia_rh_2010_2025_025deg_clipped.nc"
        s1 = Stage("stage_a", "script_a.py", [], [_exp(path)])
        s2 = Stage("stage_b", "script_b.py", [], [_exp(path)])
        issues = Planner().validate(_plan(stages=[s1, s2]))
        assert any("collision" in msg.lower() for msg in issues)

    def test_no_collision_for_different_paths(self):
        s1 = Stage("s1", "a.py", [], [_exp("data/a.nc")])
        s2 = Stage("s2", "b.py", [], [_exp("data/b.nc")])
        issues = Planner().validate(_plan(stages=[s1, s2]))
        assert not any("collision" in msg.lower() for msg in issues)

    def test_vpd_stage_without_tas_rh_warns(self):
        stage = Stage(
            name="future_vpd",
            script="run_future_vpd_workflow.py",
            args=[],
            expected_outputs=[_exp("data/vpd_out.nc", variable="vpd")],
        )
        plan = _plan(variables=["vpd"], stages=[stage])
        issues = Planner().validate(plan)
        assert any("vpd" in msg.lower() for msg in issues)

    def test_no_vpd_issue_when_vpd_not_in_variables(self):
        stage = Stage("historical", "run_historical_workflow.py", [],
                      [_exp("data/eth_rh.nc")])
        plan = _plan(variables=["rh"], stages=[stage])
        issues = Planner().validate(plan)
        assert not any("vpd" in msg.lower() for msg in issues)

    def test_multiple_issues_all_reported(self):
        # Collision + vpd missing deps
        path = "data/same.nc"
        s1 = Stage("a", "a.py", [], [_exp(path)])
        s2 = Stage("b_vpd", "run_future_vpd_workflow.py", [], [_exp(path, "vpd")])
        plan = _plan(variables=["vpd"], stages=[s1, s2])
        issues = Planner().validate(plan)
        assert len(issues) >= 2

    def test_validate_returns_list(self):
        result = Planner().validate(_plan())
        assert isinstance(result, list)

    def test_coverage_gap_reported_for_missing_output(self):
        # Plan says countries=[eth,ken] but stages only have eth outputs
        stage = Stage(
            name="historical",
            script="run_historical_workflow.py",
            args=[],
            expected_outputs=[
                _exp("data/merged_files/ethiopia_rh_2010_2025.nc"),
            ],
        )
        plan = _plan(countries=["eth", "ken"], variables=["rh"], stages=[stage])
        issues = Planner().validate(plan)
        assert any("ken" in msg.lower() or "kenya" in msg.lower() or "coverage" in msg.lower()
                   for msg in issues)

    def test_no_coverage_gap_when_all_countries_present(self):
        stage = Stage(
            name="historical",
            script="run_historical_workflow.py",
            args=[],
            expected_outputs=[
                _exp("data/merged_files/ethiopia_rh_2010_2025.nc"),
                _exp("data/merged_files/kenya_rh_2010_2025.nc"),
            ],
        )
        plan = _plan(countries=["eth", "ken"], variables=["rh"], stages=[stage])
        issues = Planner().validate(plan)
        assert not any("kenya" in msg.lower() and "no expected output" in msg.lower()
                       for msg in issues)


# ── Planner.annotate ──────────────────────────────────────────────────────────

class TestPlannerAnnotate:
    def test_annotate_returns_workflow_plan(self):
        plan = _plan()
        result = Planner().annotate(plan)
        assert isinstance(result, WorkflowPlan)

    def test_annotate_does_not_mutate_stages(self):
        stage = Stage("s", "s.py", [], [])
        plan = _plan(stages=[stage])
        result = Planner().annotate(plan)
        assert result.stages == plan.stages

    def test_annotate_preserves_countries(self):
        plan = _plan(countries=["eth", "ken"])
        assert Planner().annotate(plan).countries == ["eth", "ken"]
