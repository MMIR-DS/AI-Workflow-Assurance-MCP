"""items pre-write policy for the pinned Tau2 retail simulator."""

from __future__ import annotations

from typing import Any

from ai_workflow_assurance_mcp.tau2_prewrite_exchange import evaluate_tau2_prewrite
from ai_workflow_assurance_mcp.tau2_prewrite_common import (
    _get,
    _messages,
    _tool_calls,
)


def _has_prior_attempt_not_blocked_by_awa(
    messages: list[Any], tool_name: str, order_id: Any, current_call_id: str
) -> bool:
    """Treat any prior non-AWA-blocked call as an attempt for one-shot operations."""
    for message in messages:
        for call in _tool_calls(message):
            arguments = _get(call, "arguments", {})
            call_id = str(_get(call, "id", ""))
            if (
                call_id == current_call_id
                or _get(call, "name") != tool_name
                or not isinstance(arguments, dict)
                or arguments.get("order_id") != order_id
            ):
                continue
            result_message = next(
                (
                    candidate for candidate in messages
                    if _get(candidate, "role") == "tool"
                    and str(_get(candidate, "id", "")) == call_id
                ),
                None,
            )
            if result_message is None:
                return True
            content = _get(result_message, "content", "")
            if not isinstance(content, str) or "AWA_PREWRITE_NO_GO" not in content:
                return True
    return False


def evaluate_tau2_pending_items_prewrite(trajectory: Any, tool_call: Any) -> dict[str, Any]:
    """Preflight one-item pending-order changes; multi-item mutation is not authorized."""
    arguments = _get(tool_call, "arguments", {})
    old_items = arguments.get("item_ids") if isinstance(arguments, dict) else None
    new_items = arguments.get("new_item_ids") if isinstance(arguments, dict) else None
    if not (
        isinstance(old_items, list) and len(old_items) == 1
        and isinstance(new_items, list) and len(new_items) == 1
        and isinstance(old_items[0], str) and old_items[0]
        and isinstance(new_items[0], str) and new_items[0]
        and old_items[0] != new_items[0]
    ):
        return {
            "decision": "NO_GO",
            "allowed": False,
            "blocking_checks": ["single_item_modification_only"],
            "checked": {"single_item_modification_only": False},
            "evidence_summary": {"single_item_modification_only": False},
            "scope": "pinned_tau2_simulator_single_item_policy_not_production_authorization",
        }

    result = evaluate_tau2_prewrite(
        trajectory,
        tool_call,
        expected_tool_name="modify_pending_order_items",
        expected_order_status="pending",
    )
    messages = _messages(trajectory)
    arguments = _get(tool_call, "arguments", {})
    order_id = arguments.get("order_id") if isinstance(arguments, dict) else None
    current_call_id = str(_get(tool_call, "id", ""))
    prior_attempt = _has_prior_attempt_not_blocked_by_awa(
        messages, "modify_pending_order_items", order_id, current_call_id
    )
    result.setdefault("checked", {})["pending_order_item_modification_not_previously_attempted"] = (
        not prior_attempt
    )
    result.setdefault("evidence_summary", {})[
        "pending_order_item_modification_not_previously_attempted"
    ] = not prior_attempt
    if prior_attempt:
        result["blocking_checks"] = list(dict.fromkeys([
            *result.get("blocking_checks", []),
            "pending_order_item_modification_already_attempted",
        ]))
        result["decision"] = "NO_GO"
        result["allowed"] = False
    return result
