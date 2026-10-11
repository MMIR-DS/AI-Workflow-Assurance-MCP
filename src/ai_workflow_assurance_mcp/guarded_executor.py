"""Application-side execution seam that enforces the pre-write decision.

The executor is intentionally callback-based so a host application can place the
check immediately before its own write operation. It is not a Tau2 integration
until the host's actual write path calls this function exclusively.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from ai_workflow_assurance_mcp.prewrite_guard import evaluate_prewrite


def execute_if_prewrite_allowed(
    action: Any,
    evidence: Any,
    write_operation: Callable[[dict[str, Any]], Any],
) -> dict[str, Any]:
    """Run the supplied write callback only when the preflight returns GO.

    Inputs are copied before evaluation and before handing the action to the
    callback. A denied action never invokes the callback. Exceptions from an
    allowed write operation propagate to the host unchanged.
    """
    if not callable(write_operation):
        return {
            "decision": "NO_GO",
            "executed": False,
            "blocking_checks": ["write_operation_not_callable"],
            "scope": "application_side_guarded_executor_not_tau2_integration",
        }

    action_snapshot = deepcopy(action)
    evidence_snapshot = deepcopy(evidence)
    preflight = evaluate_prewrite(action_snapshot, evidence_snapshot)
    if preflight["decision"] != "GO":
        return {
            "decision": "NO_GO",
            "executed": False,
            "blocking_checks": preflight["blocking_checks"],
            "preflight": preflight,
            "scope": "application_side_guarded_executor_not_tau2_integration",
        }

    # Only this branch may cross the callback boundary. The host must route all
    # sensitive writes through this function to make the control mandatory.
    result = write_operation(deepcopy(action_snapshot))
    return {
        "decision": "GO",
        "executed": True,
        "blocking_checks": [],
        "write_result": result,
        "preflight": preflight,
        "scope": "application_side_guarded_executor_not_tau2_integration",
    }
