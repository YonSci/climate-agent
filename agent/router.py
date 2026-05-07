"""
router.py — Control Plane: maps a validated request dict to a WorkflowPlan.

The TaskRouter inspects the request's scenario and variable list to determine
which workflow template applies:

  historical          → run_historical_workflow.py
  ssp245 / ssp585     → run_projection_workflow.py
  ssp245 + vpd        → run_projection_workflow.py THEN run_future_vpd_workflow.py
  ssp585 + vpd        → same, ssp585 variant

The router validates the request keys before building the plan; invalid
country codes, variable names, or scenario strings raise ValueError immediately
so the error surface for the user is at the top of the call stack.

Relationship to planner.py
---------------------------
The router chooses *which* plan to build; the Planner in planner.py validates
that the plan's internal stage dependencies are consistent before execution.
"""

from __future__ import annotations

# Re-export the implementation from task_router so callers that import from
# agent.router get the same objects as callers that import from agent.task_router.
from agent.task_router import (        # noqa: F401  (public re-exports)
    TaskRouter,
    WorkflowPlan,
    Stage,
    _single_country_args,
)

__all__ = ["TaskRouter", "WorkflowPlan", "Stage"]
