"""
Tests for agent/task_router.py — request routing and workflow plan generation.
"""

import pytest
from agent.task_router import TaskRouter, WorkflowPlan, Stage


@pytest.fixture
def router():
    return TaskRouter()


# ── historical routing ────────────────────────────────────────────────────────

class TestHistoricalRouting:
    def test_historical_plan_type(self, router):
        plan = router.route({
            "countries": ["eth"], "variables": ["tas", "rh"],
            "scenario": "historical", "period": [2010, 2025],
        })
        assert plan.run_type == "historical"

    def test_historical_single_stage(self, router):
        plan = router.route({
            "countries": ["eth"], "variables": ["pr"],
            "scenario": "historical", "period": [2010, 2025],
        })
        assert len(plan.stages) == 1
        assert plan.stages[0].name == "merge"
        assert plan.stages[0].script == "run_historical_workflow.py"

    def test_historical_translates_tas_to_temp(self, router):
        plan = router.route({
            "countries": ["eth"], "variables": ["tas"],
            "scenario": "historical", "period": [2010, 2025],
        })
        args = plan.stages[0].args
        assert "temp" in args
        assert "tas" not in args

    def test_historical_translates_country_to_long_name(self, router):
        plan = router.route({
            "countries": ["eth", "ken"],
            "variables": ["rh"],
            "scenario": "historical",
            "period": [2010, 2025],
        })
        args = plan.stages[0].args
        assert "ethiopia" in args
        assert "kenya" in args
        assert "eth" not in args

    def test_historical_fast_mode_flag(self, router):
        plan = router.route({
            "countries": ["eth"], "variables": ["pr"],
            "scenario": "historical", "period": [2010, 2025],
            "quality_level": "fast",
        })
        assert "--fast-mode" in plan.stages[0].args

    def test_historical_no_fast_mode_by_default(self, router):
        plan = router.route({
            "countries": ["eth"], "variables": ["pr"],
            "scenario": "historical", "period": [2010, 2025],
        })
        assert "--fast-mode" not in plan.stages[0].args

    def test_historical_diagnostics_flag(self, router):
        plan = router.route({
            "countries": ["eth"], "variables": ["pr"],
            "scenario": "historical", "period": [2010, 2025],
            "diagnostics": True,
        })
        assert "--run-diagnostics" in plan.stages[0].args

    def test_historical_period_in_args(self, router):
        plan = router.route({
            "countries": ["eth"], "variables": ["rh"],
            "scenario": "historical", "period": [2015, 2020],
        })
        args = plan.stages[0].args
        assert "--start-year" in args
        idx = args.index("--start-year")
        assert args[idx + 1] == "2015"


# ── projection routing ────────────────────────────────────────────────────────

class TestProjectionRouting:
    def test_projection_plan_type(self, router):
        plan = router.route({
            "countries": ["eth"], "variables": ["rh", "pr"],
            "scenario": "ssp245", "period": [2040, 2070],
        })
        assert plan.run_type == "projection"

    def test_projection_single_stage(self, router):
        plan = router.route({
            "countries": ["eth"], "variables": ["tas"],
            "scenario": "ssp585", "period": [2040, 2070],
        })
        assert len(plan.stages) == 1
        assert plan.stages[0].script == "run_projection_workflow.py"

    def test_projection_scenario_translated(self, router):
        plan = router.route({
            "countries": ["eth"], "variables": ["pr"],
            "scenario": "ssp245", "period": [2040, 2070],
        })
        args = plan.stages[0].args
        assert "ssp_245" in args
        assert "ssp245" not in args

    def test_projection_tas_not_translated(self, router):
        plan = router.route({
            "countries": ["eth"], "variables": ["tas"],
            "scenario": "ssp245", "period": [2040, 2070],
        })
        args = plan.stages[0].args
        assert "tas" in args
        # "temp" alias only applies to historical
        assert "temp" not in args


# ── future VPD routing ────────────────────────────────────────────────────────

class TestFutureVPDRouting:
    def test_vpd_only_single_stage(self, router):
        plan = router.route({
            "countries": ["eth"], "variables": ["vpd"],
            "scenario": "ssp245", "period": [2040, 2070],
        })
        assert plan.run_type == "future_vpd"
        assert len(plan.stages) == 1
        assert plan.stages[0].script == "run_future_vpd_workflow.py"

    def test_vpd_plus_projection_vars_two_stages(self, router):
        plan = router.route({
            "countries": ["eth"],
            "variables": ["rh", "tas", "vpd"],
            "scenario": "ssp245",
            "period": [2040, 2070],
        })
        assert plan.run_type == "projection+vpd"
        assert len(plan.stages) == 2
        assert plan.stages[0].name == "regrid"
        assert plan.stages[1].name == "vpd_compute"

    def test_vpd_stage_script_name(self, router):
        plan = router.route({
            "countries": ["eth"], "variables": ["vpd"],
            "scenario": "ssp585", "period": [2040, 2070],
        })
        assert plan.stages[0].script == "run_future_vpd_workflow.py"

    def test_vpd_scenario_translated(self, router):
        plan = router.route({
            "countries": ["eth"], "variables": ["vpd"],
            "scenario": "ssp585", "period": [2040, 2070],
        })
        args = plan.stages[0].args
        assert "ssp_585" in args


# ── validation in router ──────────────────────────────────────────────────────

class TestRouterValidation:
    def test_invalid_country_raises(self, router):
        with pytest.raises(ValueError):
            router.route({
                "countries": ["zzz"], "variables": ["tas"],
                "scenario": "historical", "period": [2010, 2020],
            })

    def test_invalid_variable_raises(self, router):
        with pytest.raises(ValueError):
            router.route({
                "countries": ["eth"], "variables": ["wind"],
                "scenario": "historical", "period": [2010, 2020],
            })

    def test_inverted_period_raises(self, router):
        with pytest.raises(ValueError):
            router.route({
                "countries": ["eth"], "variables": ["pr"],
                "scenario": "historical", "period": [2025, 2010],
            })


# ── workers propagated ────────────────────────────────────────────────────────

class TestWorkersArg:
    def test_workers_in_historical_args(self, router):
        plan = router.route({
            "countries": ["eth"], "variables": ["pr"],
            "scenario": "historical", "period": [2010, 2025],
            "workers": 4,
        })
        args = plan.stages[0].args
        idx = args.index("--max-workers")
        assert args[idx + 1] == "4"

    def test_default_workers_is_one(self, router):
        plan = router.route({
            "countries": ["eth"], "variables": ["pr"],
            "scenario": "historical", "period": [2010, 2025],
        })
        args = plan.stages[0].args
        idx = args.index("--max-workers")
        assert args[idx + 1] == "1"


# ── split_by_country ──────────────────────────────────────────────────────────

class TestSplitByCountry:
    def test_single_country_returns_self(self, router):
        plan = router.route({
            "countries": ["eth"], "variables": ["pr"],
            "scenario": "historical", "period": [2010, 2025],
        })
        sub_plans = plan.split_by_country()
        assert len(sub_plans) == 1
        assert sub_plans[0] is plan

    def test_three_countries_returns_three_plans(self, router):
        plan = router.route({
            "countries": ["eth", "ken", "som"], "variables": ["pr"],
            "scenario": "historical", "period": [2010, 2025],
        })
        sub_plans = plan.split_by_country()
        assert len(sub_plans) == 3

    def test_each_sub_plan_has_one_country(self, router):
        plan = router.route({
            "countries": ["eth", "ken"], "variables": ["tas"],
            "scenario": "historical", "period": [2010, 2025],
        })
        for sub in plan.split_by_country():
            assert len(sub.countries) == 1

    def test_sub_plan_countries_cover_all_original(self, router):
        plan = router.route({
            "countries": ["eth", "ken", "som"], "variables": ["pr"],
            "scenario": "historical", "period": [2010, 2025],
        })
        countries = {sub.countries[0] for sub in plan.split_by_country()}
        assert countries == {"eth", "ken", "som"}

    def test_sub_plan_args_contain_only_own_country(self, router):
        plan = router.route({
            "countries": ["eth", "ken"], "variables": ["tas"],
            "scenario": "historical", "period": [2010, 2025],
        })
        subs = plan.split_by_country()
        eth_sub = next(s for s in subs if s.countries[0] == "eth")
        ken_sub = next(s for s in subs if s.countries[0] == "ken")
        eth_args = eth_sub.stages[0].args
        ken_args = ken_sub.stages[0].args
        assert "ethiopia" in eth_args and "kenya" not in eth_args
        assert "kenya" in ken_args and "ethiopia" not in ken_args

    def test_sub_plan_max_workers_reset_to_one(self, router):
        plan = router.route({
            "countries": ["eth", "ken"], "variables": ["pr"],
            "scenario": "historical", "period": [2010, 2025],
            "workers": 4,
        })
        for sub in plan.split_by_country():
            args = sub.stages[0].args
            idx = args.index("--max-workers")
            assert args[idx + 1] == "1"

    def test_sub_plan_preserves_variables(self, router):
        plan = router.route({
            "countries": ["eth", "ken"], "variables": ["tas", "rh"],
            "scenario": "historical", "period": [2010, 2025],
        })
        for sub in plan.split_by_country():
            assert sub.variables == ["tas", "rh"]

    def test_sub_plan_preserves_scenario(self, router):
        plan = router.route({
            "countries": ["eth", "ken"], "variables": ["pr"],
            "scenario": "ssp245", "period": [2040, 2070],
        })
        for sub in plan.split_by_country():
            assert sub.scenario == "ssp245"

    def test_sub_plan_preserves_period(self, router):
        plan = router.route({
            "countries": ["eth", "ken"], "variables": ["pr"],
            "scenario": "historical", "period": [2015, 2022],
        })
        for sub in plan.split_by_country():
            assert sub.period == (2015, 2022)

    def test_sub_plan_preserves_run_type(self, router):
        plan = router.route({
            "countries": ["eth", "ken"], "variables": ["pr"],
            "scenario": "historical", "period": [2010, 2025],
        })
        for sub in plan.split_by_country():
            assert sub.run_type == "historical"
