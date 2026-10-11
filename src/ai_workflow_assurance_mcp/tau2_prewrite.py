"""Build a fail-closed preflight decision from Tau2's in-memory trajectory.

This adapter is designed for the pinned Tau2 retail simulator. Trajectory values
are simulator observations, not cryptographically authenticated production evidence.
"""
from __future__ import annotations

import json
import re
from typing import Any

from ai_workflow_assurance_mcp.prewrite_guard import evaluate_prewrite


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _messages(trajectory: Any) -> list[Any]:
    return list(trajectory) if isinstance(trajectory, (list, tuple)) else []


def _tool_calls(message: Any) -> list[Any]:
    calls = _get(message, "tool_calls", []) or []
    return list(calls) if isinstance(calls, (list, tuple)) else []


def _decode_tool_result(messages: list[Any], call_id: str) -> Any:
    for message in messages:
        if _get(message, "role") != "tool" or _get(message, "id") != call_id:
            continue
        content = _get(message, "content")
        if not isinstance(content, str):
            return None
        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return content
    return None


def _find_call_result(messages: list[Any], tool_names: set[str], predicate: Any) -> tuple[Any, Any]:
    for message in reversed(messages):
        for call in reversed(_tool_calls(message)):
            if _get(call, "name") not in tool_names:
                continue
            arguments = _get(call, "arguments", {})
            if not isinstance(arguments, dict) or not predicate(arguments):
                continue
            result = _decode_tool_result(messages, str(_get(call, "id", "")))
            if result is not None:
                return arguments, result
    return {}, None


def _contains_all(text: str, values: list[str]) -> bool:
    return all(value in text for value in values)


def _is_affirmative(text: str) -> bool:
    normalized = re.sub(r"[^a-z0-9' ]+", " ", text.casefold())
    # A positive token is not sufficient when the reply also qualifies or changes
    # the requested action. Prefer a false block over treating mixed intent as consent.
    if re.search(
        r"\b(no|don't|do not|not yet|stop|wait|change|incorrect|instead|cancel|"
        r"but|however|except|different|another|rather|unless|maybe|not that)\b",
        normalized,
    ):
        return False
    return bool(
        re.search(
            r"\b(yes|confirm|confirmed|go ahead|proceed|that's right|that is right|"
            r"sounds good|correct|exactly right|please do|do it)\b",
            normalized,
        )
    )


def evaluate_tau2_prewrite(trajectory: Any, tool_call: Any) -> dict[str, Any]:
    """Evaluate a Tau2 exchange tool call immediately before its execution."""
    messages = _messages(trajectory)
    name = _get(tool_call, "name")
    arguments = _get(tool_call, "arguments", {})
    if name != "exchange_delivered_order_items" or not isinstance(arguments, dict):
        return {
            "decision": "NO_GO",
            "allowed": False,
            "blocking_checks": ["unsupported_or_malformed_tool_call"],
        }

    order_id = arguments.get("order_id")
    old_items = arguments.get("item_ids")
    new_items = arguments.get("new_item_ids")
    payment_id = arguments.get("payment_method_id")
    action = {
        "order_id": order_id,
        "old_item_ids": old_items,
        "new_item_ids": new_items,
        "payment_method_id": payment_id,
    }

    order_args, order_before = _find_call_result(
        messages,
        {"get_order_details"},
        lambda call_args: call_args.get("order_id") == order_id,
    )
    order_is_object = isinstance(order_before, dict)
    owner_id = order_before.get("user_id") if order_is_object else None
    order_status = order_before.get("status") if order_is_object else None

    _, identity_result = _find_call_result(
        messages,
        {"find_user_id_by_name_zip", "find_user_id_by_email"},
        lambda _: True,
    )
    identity_id = identity_result.strip() if isinstance(identity_result, str) else None
    identity_valid = bool(identity_id and owner_id and identity_id == owner_id and order_args)

    # The current assistant tool-call message is already in the trajectory.
    current_message_index = len(messages) - 1
    prior_messages = messages[:-1] if messages and _tool_calls(messages[-1]) else messages

    last_assistant_text_index = -1
    last_assistant_text = ""
    for index, message in enumerate(prior_messages):
        if _get(message, "role") == "assistant" and not _tool_calls(message):
            text = _get(message, "content")
            if isinstance(text, str) and text.strip():
                last_assistant_text_index = index
                last_assistant_text = text

    identifiers = [order_id, *(old_items if isinstance(old_items, list) else []),
                   *(new_items if isinstance(new_items, list) else []), payment_id]
    identifiers_are_strings = all(isinstance(item, str) and item for item in identifiers)
    disclosure_valid = (
        identifiers_are_strings
        and last_assistant_text_index >= 0
        and _contains_all(last_assistant_text, identifiers)
    )

    last_user_index = -1
    last_user_text = ""
    for index, message in enumerate(prior_messages):
        if index > last_assistant_text_index and _get(message, "role") == "user":
            text = _get(message, "content")
            if isinstance(text, str):
                last_user_index = index
                last_user_text = text
    confirmation_valid = (
        disclosure_valid
        and last_user_index > last_assistant_text_index
        and _is_affirmative(last_user_text)
        and last_user_index < current_message_index
    )

    evidence = {
        "identity_verified": identity_valid,
        "verified_user_id": identity_id,
        "order_owner_id": owner_id,
        "order_id": order_id if order_is_object else None,
        "order_status": order_status,
        "confirmation": {
            "confirmed": confirmation_valid,
            "order_id": order_id,
            "old_item_ids": old_items,
            "new_item_ids": new_items,
            "payment_method_id": payment_id,
            "confirmation_id": f"tau2-turn-{last_user_index + 1}" if confirmation_valid else "",
        },
        "customer_facing_confirmation": {
            "order_id": order_id,
            "old_item_ids": old_items,
            "new_item_ids": new_items,
            "payment_method_id": payment_id,
            "payment_method_disclosed": disclosure_valid,
        },
        "confirmation_event_sequence": last_user_index + 1 if confirmation_valid else None,
        "proposed_write_sequence": current_message_index + 1,
    }
    result = evaluate_prewrite(action, evidence)
    result["scope"] = "pinned_tau2_simulator_trajectory_not_production_identity_evidence"
    result["evidence_summary"] = {
        "identity_matches_order_owner": identity_valid,
        "order_status": order_status,
        "assistant_disclosed_exact_order_items_and_payment": disclosure_valid,
        "user_affirmed_after_disclosure": confirmation_valid,
    }
    return result
