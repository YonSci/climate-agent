"""
planner.py — DAG validation and annotation for WorkflowPlans.

The Planner sits between the TaskRouter (which produces a WorkflowPlan) and
the Orchestrator (which executes it). Its job is to catch plan-level problems
before any subprocess is launched:

  1. VPD dependency check — a vpd stage must be preceded by tas AND rh stages
     in the same plan; if they are absent the VPD compute will fail at runtime.

  2. Output path uniqueness — two stages must not write to the same output file
     (would cause a silent overwrite race).

  3. Country/variable coverage — every (country, variable) pair in the request
     has at least one stage that produces an output for it.

Usage
-----
    from agent.router import TaskRouter
    from agent.planner import Planner

    plan   = TaskRouter().route(request)
    issues = Planner().validate(plan)
    if issues:
        for msg in issues:
            logger.warning(f"Plan issue: {msg}")
    plan   = Planner().annotate(plan)  # adds dependency metadata (informational)
"""

from __future__ import annotations
import logging
from pathlib import Path

from agent.task_router import WorkflowPlan, Stage

logger = logging.getLogger(__name__)


class Planner:
    """Validates and annotates a WorkflowPlan before the Orchestrator runs it."""

    def validate(self, plan: WorkflowPlan) -> list[str]:
        """
        Run all consistency checks on *plan*.

        Returns a (possibly empty) list of human-readable warning strings.
        An empty list means the plan is internally consistent.
        No exceptions are raised — all issues are returned as strings so the
        caller can decide whether to abort or proceed with warnings.
        """
        issues: list[str] = []
        issues.extend(self._check_vpd_dependencies(plan))
        issues.extend(self._check_output_uniqueness(plan))
        issues.extend(self._check_coverage(plan))
        return issues

    def annotate(self, plan: WorkflowPlan) -> WorkflowPlan:
        """
        Return the plan unchanged (future: attach dependency edges to stages).

        Currently a pass-through; the hook exists so callers don't need to
        change their call sites when richer DAG metadata is added later.
        """
        return plan

    # ── Internal checks ───────────────────────────────────────────────────────

    def _check_vpd_dependencies(self, plan: WorkflowPlan) -> list[str]:
        """
        VPD stages require tas and rh outputs to already exist or be produced earlier.

        Checks two things:
        1. If this is a vpd-only plan, tas and rh are not in plan.variables — warn
           that they must be pre-existing on disk.
        2. If the plan has multiple stages, the vpd stage must not appear first
           (something must precede it to produce tas/rh inputs).
        """
        issues: list[str] = []
        if "vpd" not in plan.variables:
            return issues

        vpd_stage_idx = next(
            (i for i, s in enumerate(plan.stages) if "vpd" in s.name.lower()), None
        )
        if vpd_stage_idx is None:
            return issues

        plan_vars = set(plan.variables)
        missing_inputs = {"tas", "rh"} - plan_vars
        if missing_inputs:
            issues.append(
                f"VPD compute stage detected but "
                f"{', '.join(sorted(missing_inputs))} not in plan variables. "
                "For a VPD-only run, ensure those outputs are already on disk "
                "or add them to the --variables request."
            )

        # For multi-stage plans, verify VPD stage is not ordered before its inputs.
        if len(plan.stages) > 1 and vpd_stage_idx == 0:
            issues.append(
                "VPD compute stage is first in the plan — projection/merge stages "
                "that produce tas and rh must be ordered before the VPD stage."
            )

        return issues

    def _check_output_uniqueness(self, plan: WorkflowPlan) -> list[str]:
        """Two stages must not write to the same output path."""
        seen: dict[Path, str] = {}
        issues: list[str] = []
        for stage in plan.stages:
            for exp in stage.expected_outputs:
                key = exp.path.resolve()
                if key in seen:
                    issues.append(
                        f"Output path collision: {exp.path.name!r} is expected "
                        f"by both stage '{seen[key]}' and stage '{stage.name}'."
                    )
                else:
                    seen[key] = stage.name
        return issues

    def _check_coverage(self, plan: WorkflowPlan) -> list[str]:
        """Every requested (country, variable) pair should have at least one output."""
        issues: list[str] = []
        from agent.policy import SHORT_TO_LONG

        all_output_paths = [
            str(exp.path) for s in plan.stages for exp in s.expected_outputs
        ]

        for country in plan.countries:
            long = SHORT_TO_LONG.get(country, country)
            for variable in plan.variables:
                if variable == "vpd":
                    # VPD is always derived — its coverage is implied by tas+rh
                    continue
                covered = any(
                    (long in p or country in p)
                    for p in all_output_paths
                )
                if not covered:
                    issues.append(
                        f"No expected output found for country='{country}' "
                        f"variable='{variable}' in any stage. "
                        f"The plan may be incomplete."
                    )
        return issues
