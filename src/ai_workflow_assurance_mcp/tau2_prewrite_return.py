"""return pre-write policy for the pinned Tau2 retail simulator."""

from __future__ import annotations

from collections import Counter
from typing import Any

from ai_workflow_assurance_mcp.tau2_prewrite_common import (
    _confirmation_references_consistent,
    _contains_all,
    _find_call_result,
    _get,
    _is_affirmative,
    _latest_blocked_write_result_index,
    _messages,
    _order_snapshot_is_fresh,
    _tool_calls,
)


def evaluate_tau2_return_prewrite(trajectory: Any, tool_call: Any) -> dict[str, Any]:
    """Fail-closed preflight for requesting a return of delivered order items."""
    messages = _messages(trajectory)
    name = _get(tool_call, "name")
    arguments = _get(tool_call, "arguments", {})
    if name != "return_delivered_order_items" or not isinstance(arguments, dict):
        return {
            "decision": "NO_GO",
            "allowed": False,
            "blocking_checks": ["unsupported_or_malformed_tool_call"],
        }

    order_id = arguments.get("order_id")
    item_ids = arguments.get("item_ids")
    payment_id = arguments.get("payment_method_id")
    order_args, order_before = _find_call_result(
        messages,
        {"get_order_details"},
        lambda call_args: call_args.get("order_id") == order_id,
    )
    order_is_object = isinstance(order_before, dict)
    snapshot_matches = order_is_object and order_before.get("order_id") == order_id
    order_status = order_before.get("status") if order_is_object else None
    owner_id = order_before.get("user_id") if order_is_object else None
    order_items = order_before.get("items") if order_is_object else None
    order_item_ids = [
        item.get("item_id")
        for item in order_items
        if isinstance(item, dict) and isinstance(item.get("item_id"), str)
    ] if isinstance(order_items, list) else []
    item_ids_valid = isinstance(item_ids, list) and all(
        isinstance(item_id, str) and item_id for item_id in item_ids
    )
    items_belong_to_order = (
        snapshot_matches
        and item_ids_valid
        and bool(item_ids)
        and Counter(item_ids) <= Counter(order_item_ids)
    )

    payment_history = order_before.get("payment_history") if order_is_object else None
    payment_history_valid = (
        isinstance(payment_history, list)
        and bool(payment_history)
        and isinstance(payment_history[0], dict)
        and payment_history[0].get("transaction_type") == "payment"
        and isinstance(payment_history[0].get("payment_method_id"), str)
    )
    original_payment_id = (
        payment_history[0].get("payment_method_id") if payment_history_valid else None
    )

    _, identity_result = _find_call_result(
        messages,
        {"find_user_id_by_name_zip", "find_user_id_by_email"},
        lambda _: True,
    )
    identity_id = identity_result.strip() if isinstance(identity_result, str) else None
    identity_valid = bool(
        identity_id and owner_id and identity_id == owner_id and order_args and snapshot_matches
    )

    user_args, user_details = _find_call_result(
        messages,
        {"get_user_details"},
        lambda call_args: call_args.get("user_id") == owner_id,
    )
    user_details_valid = (
        isinstance(user_details, dict)
        and user_details.get("user_id") == owner_id
        and bool(user_args)
    )
    payment_methods = user_details.get("payment_methods") if user_details_valid else None
    payment_method = (
        payment_methods.get(payment_id)
        if isinstance(payment_methods, dict) and isinstance(payment_id, str)
        else None
    )
    payment_method_details_valid = (
        isinstance(payment_method, dict)
        and payment_method.get("id") == payment_id
        and payment_method.get("source") in {"credit_card", "gift_card", "paypal"}
    )
    payment_method_authorized = (
        payment_method_details_valid
        and (
            payment_id == original_payment_id
            or payment_method.get("source") == "gift_card"
        )
    )
    method_details = []
    if payment_method_details_valid:
        source = payment_method.get("source")
        if isinstance(source, str):
            method_details.append(source.replace("_", " "))
        for field in ("brand", "last_four"):
            value = payment_method.get(field)
            if isinstance(value, str) and value:
                method_details.append(value)

    current_message_index = len(messages) - 1
    prior_messages = messages[:-1] if messages and _tool_calls(messages[-1]) else messages
    last_assistant_text_index = -1
    last_assistant_text = ""
    for index, message in enumerate(prior_messages):
        if _get(message, "role") == "assistant" and not _tool_calls(message):
            content = _get(message, "content")
            if isinstance(content, str) and content.strip():
                last_assistant_text_index = index
                last_assistant_text = content
    disclosure_values = [order_id, *(item_ids if isinstance(item_ids, list) else []), payment_id, *method_details]
    disclosure_valid = (
        all(isinstance(value, str) and value for value in disclosure_values)
        and payment_method_authorized
        and last_assistant_text_index >= 0
        and _contains_all(last_assistant_text, disclosure_values)
        and "return request" in last_assistant_text.casefold()
        and "follow-up email" in last_assistant_text.casefold()
    )

    last_user_index = -1
    last_user_text = ""
    for index, message in enumerate(prior_messages):
        if index > last_assistant_text_index and _get(message, "role") == "user":
            content = _get(message, "content")
            if isinstance(content, str):
                last_user_index = index
                last_user_text = content
    latest_blocked_index = _latest_blocked_write_result_index(
        prior_messages, order_id, "return_delivered_order_items"
    )
    reconfirmed_after_block = (
        latest_blocked_index < 0 or last_assistant_text_index > latest_blocked_index
    )
    confirmation_valid = (
        disclosure_valid
        and last_user_index > last_assistant_text_index
        and _is_affirmative(last_user_text)
        and _confirmation_references_consistent(
            last_user_text, order_id, item_ids, [], payment_id
        )
        and reconfirmed_after_block
        and last_user_index < current_message_index
    )
    snapshot_fresh = _order_snapshot_is_fresh(messages, order_id)

    checks = {
        "order_snapshot_matches_requested_order": snapshot_matches,
        "order_is_delivered": order_status == "delivered",
        "identity_and_order_ownership_verified": identity_valid,
        "requested_items_belong_to_order_quantity": items_belong_to_order,
        "payment_history_has_original_payment": payment_history_valid,
        "payment_method_is_original_or_verified_gift_card": payment_method_authorized,
        "return_and_payment_details_disclosed": disclosure_valid,
        "user_confirmed_after_disclosure": confirmation_valid,
        "user_reconfirmed_after_latest_blocked_attempt": reconfirmed_after_block,
        "order_snapshot_fresh": snapshot_fresh,
    }
    blocking = [check for check, passed in checks.items() if not passed]
    return {
        "decision": "GO" if not blocking else "NO_GO",
        "allowed": not blocking,
        "blocking_checks": blocking,
        "checked": checks,
        "scope": "pinned_tau2_simulator_trajectory_not_production_identity_evidence",
        "evidence_summary": {
            **checks,
            "order_id": order_id if snapshot_matches else None,
            "order_status": order_status,
            "return_item_ids": item_ids,
            "return_payment_method_id": payment_id,
        },
    }
