"""
task_router.py — Maps validated requests to ordered workflow plans.

The TaskRouter is the Control Plane: it interprets a request dict, determines
which workflow path applies (historical / projection / future VPD), and returns
a WorkflowPlan whose stages the Orchestrator executes in order.

Each Stage carries expected_outputs — the list of ExpectedOutput objects that
the Orchestrator's ValidationEngine checks after the subprocess succeeds.
"""

from __future__ import annotations
from dataclasses import dataclass, field

from agent.policy import (
    validate_request,
    SHORT_TO_LONG,
    HIST_VAR_ALIAS,
    SCENARIO_TO_SCRIPT,
)


def _single_country_args(args: list[str], long_country: str) -> list[str]:
    """
    Return a copy of args with the --country values replaced by a single country
    and --max-workers reset to 1 (agent handles parallelism across countries).
    """
    result: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--country":
            result.append("--country")
            i += 1
            # skip all existing country values (runs until next --flag or end)
            while i < len(args) and not args[i].startswith("--"):
                i += 1
            result.append(long_country)
        elif args[i] == "--max-workers":
            result.extend(["--max-workers", "1"])
            i += 2
        else:
            result.append(args[i])
            i += 1
    return result
from agent.output_resolver import (
    ExpectedOutput,
    historical_outputs,
    projection_outputs,
    vpd_outputs,
)


@dataclass
class Stage:
    """One top-level workflow tool invocation."""
    name: str                               # manifest stage label
    script: str                             # filename inside scripts/
    args: list[str]                         # CLI arguments for the script
    expected_outputs: list[ExpectedOutput] = field(default_factory=list)


@dataclass
class WorkflowPlan:
    """Ordered list of stages produced by TaskRouter.route()."""
    run_type: str               # historical | projection | future_vpd | projection+vpd | diagnostics
    countries: list[str]        # short codes
    variables: list[str]
    scenario: str
    period: tuple[int, int]
    fast_mode: bool
    diagnostics: bool
    workers: int
    stages: list[Stage] = field(default_factory=list)
    diagnostics_only: bool = False  # skip pipeline stages; run diagnose_final_netcdf.py on existing outputs

    def split_by_country(self) -> "list[WorkflowPlan]":
        """
        Return one WorkflowPlan per country for parallel execution.

        Each sub-plan gets a single-country copy of every stage (args and
        expected_outputs filtered to that country). --max-workers is set to 1
        because the agent handles cross-country parallelism via ThreadPoolExecutor.

        Returns [self] unchanged when only one country is present.
        """
        if len(self.countries) <= 1:
            return [self]
        result: list[WorkflowPlan] = []
        for country in self.countries:
            long_name = SHORT_TO_LONG[country]
            country_stages = [
                Stage(
                    name=s.name,
                    script=s.script,
                    args=_single_country_args(s.args, long_name),
                    expected_outputs=[
                        o for o in s.expected_outputs
                        if f"/{country}/" in str(o.path).replace("\\", "/")
                    ],
                )
                for s in self.stages
            ]
            result.append(WorkflowPlan(
                run_type=self.run_type,
                countries=[country],
                variables=self.variables,
                scenario=self.scenario,
                period=self.period,
                fast_mode=self.fast_mode,
                diagnostics=self.diagnostics,
                workers=1,
                stages=country_stages,
            ))
        return result


class TaskRouter:
    """
    Maps a request dict to a WorkflowPlan.

    Request schema
    --------------
    {
        "countries":     list[str],   # short codes: eth, ken, som
        "variables":     list[str],   # tas, rh, vpd, pr
        "scenario":      str,         # historical | ssp245 | ssp585
        "period":        [int, int],  # [year_start, year_end]
        "quality_level": str,         # strict | fast  (default: strict)
        "diagnostics":   bool,        # (default: False)
        "workers":       int,         # (default: 1)
    }
    """

    def route(self, request: dict) -> WorkflowPlan:
        countries = list(request["countries"])
        variables = list(request["variables"])
        scenario  = request["scenario"]
        period    = (int(request["period"][0]), int(request["period"][1]))
        fast_mode = request.get("quality_level", "strict") == "fast"
        diag      = bool(request.get("diagnostics", False))
        workers   = int(request.get("workers", 1))

        validate_request(countries, variables, scenario, period)

        if request.get("diagnostics_only"):
            return self._diagnostics_only(countries, variables, scenario, period, workers)

        if scenario == "historical":
            return self._historical(countries, variables, period, fast_mode, diag, workers)

        # Projection path (ssp245 / ssp585)
        vpd_requested = "vpd" in variables
        proj_vars     = [v for v in variables if v != "vpd"]

        if not vpd_requested:
            return self._projection(countries, proj_vars, scenario, period,
                                    fast_mode, diag, workers)

        stages: list[Stage] = []
        run_type = "future_vpd"

        if proj_vars:
            run_type = "projection+vpd"
            proj_plan = self._projection(countries, proj_vars, scenario, period,
                                         fast_mode, False, workers)
            stages.extend(proj_plan.stages)

        vpd_plan = self._future_vpd(countries, scenario, period,
                                    fast_mode, diag, workers)
        stages.extend(vpd_plan.stages)

        return WorkflowPlan(
            run_type=run_type,
            countries=countries, variables=variables,
            scenario=scenario, period=period,
            fast_mode=fast_mode, diagnostics=diag,
            workers=workers, stages=stages,
        )

    # ── Private builders ──────────────────────────────────────────────────────

    def _historical(self, countries, variables, period, fast_mode, diag, workers) -> WorkflowPlan:
        from pathlib import Path as _Path
        from agent.artifact_manager import ROOT as _ROOT

        long_countries = [SHORT_TO_LONG[c] for c in countries]
        script_vars    = [HIST_VAR_ALIAS[v] for v in variables]

        args: list[str] = [
            "--country",     *long_countries,
            "--variable",    *script_vars,
            "--start-year",  str(period[0]),
            "--end-year",    str(period[1]),
            "--max-workers", str(workers),
        ]
        if fast_mode:
            args.append("--fast-mode")
        if diag:
            args.append("--run-diagnostics")

        # If merged intermediate files already exist for all non-pr variables,
        # skip the expensive per-day merge step (5000+ files per variable).
        _merged_dir = _ROOT / "data" / "merged_files"
        _period_label = f"{period[0]}_{period[1]}"
        _needs_merge = [v for v in variables if v != "pr"]
        if _needs_merge and all(
            (_merged_dir / f"{SHORT_TO_LONG[c]}_{HIST_VAR_ALIAS[v]}_{_period_label}.nc").exists()
            for c in countries for v in _needs_merge
        ):
            args.append("--skip-merge")

        return WorkflowPlan(
            run_type="historical",
            countries=countries, variables=variables,
            scenario="historical", period=period,
            fast_mode=fast_mode, diagnostics=diag,
            workers=workers,
            stages=[Stage(
                name="merge",
                script="run_historical_workflow.py",
                args=args,
                expected_outputs=historical_outputs(countries, variables, period),
            )],
        )

    def _projection(self, countries, variables, scenario, period,
                    fast_mode, diag, workers) -> WorkflowPlan:
        long_countries  = [SHORT_TO_LONG[c] for c in countries]
        script_scenario = SCENARIO_TO_SCRIPT[scenario]

        args: list[str] = [
            "--country",     *long_countries,
            "--scenario",    script_scenario,
            "--variable",    *variables,
            "--start-year",  str(period[0]),
            "--end-year",    str(period[1]),
            "--max-workers", str(workers),
        ]
        if fast_mode:
            args.append("--fast-mode")
        if diag:
            args.append("--run-diagnostics")

        return WorkflowPlan(
            run_type="projection",
            countries=countries, variables=variables,
            scenario=scenario, period=period,
            fast_mode=fast_mode, diagnostics=diag,
            workers=workers,
            stages=[Stage(
                name="regrid",
                script="run_projection_workflow.py",
                args=args,
                expected_outputs=projection_outputs(countries, variables, scenario, period),
            )],
        )

    def _diagnostics_only(self, countries, variables, scenario,
                          period, workers) -> WorkflowPlan:
        """
        Build a WorkflowPlan that locates existing final outputs and runs
        diagnose_final_netcdf.py on them without re-executing any pipeline stages.

        The stages list is populated with expected_outputs so the orchestrator
        can locate the files; the diagnostics_only flag tells run_agent to skip
        run_tool() and call run_diagnostics() directly.
        """
        if scenario == "historical":
            base = self._historical(countries, variables, period, False, True, workers)
        elif "vpd" in variables and scenario != "historical":
            vpd_countries = countries
            base = self._future_vpd(vpd_countries, scenario, period, False, True, workers)
        else:
            base = self._projection(countries, variables, scenario, period, False, True, workers)

        return WorkflowPlan(
            run_type="diagnostics",
            countries=countries,
            variables=variables,
            scenario=scenario,
            period=period,
            fast_mode=False,
            diagnostics=True,
            diagnostics_only=True,
            workers=workers,
            stages=base.stages,
        )

    def _future_vpd(self, countries, scenario, period,
                    fast_mode, diag, workers) -> WorkflowPlan:
        long_countries  = [SHORT_TO_LONG[c] for c in countries]
        script_scenario = SCENARIO_TO_SCRIPT[scenario]

        args: list[str] = [
            "--country",     *long_countries,
            "--scenario",    script_scenario,
            "--start-year",  str(period[0]),
            "--end-year",    str(period[1]),
            "--max-workers", str(workers),
        ]
        if fast_mode:
            args.append("--fast-mode")
        if diag:
            args.append("--run-diagnostics")

        return WorkflowPlan(
            run_type="future_vpd",
            countries=countries, variables=["vpd"],
            scenario=scenario, period=period,
            fast_mode=fast_mode, diagnostics=diag,
            workers=workers,
            stages=[Stage(
                name="vpd_compute",
                script="run_future_vpd_workflow.py",
                args=args,
                expected_outputs=vpd_outputs(countries, scenario, period),
            )],
        )
