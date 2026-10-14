"""address pre-write policy for the pinned Tau2 retail simulator."""

from __future__ import annotations

import re
from typing import Any

from ai_workflow_assurance_mcp.tau2_prewrite_common import (
    _contains_all,
    _find_call_result,
    _get,
    _is_affirmative,
    _latest_blocked_write_result_index,
    _mentioned_order_ids,
    _messages,
    _order_snapshot_is_fresh,
    _tool_calls,
)


def _address_confirmation_references_consistent(
    text: str, order_id: Any, expected_zip: Any
) -> bool:
    """Reject explicit conflicting order IDs or postal codes in an address confirmation."""
    if not isinstance(order_id, str) or not order_id or not isinstance(expected_zip, str):
        return False
    folded = text.casefold()
    order_refs = _mentioned_order_ids(folded)
    expected_order_reference = order_id.casefold().lstrip("#")
    if any(reference != expected_order_reference for reference in order_refs):
        return False
    zip_refs = re.findall(
        r"\b(?:zip|postal(?:\s+code)?)\s*(?:is|:|#)?\s*([a-z0-9-]+)\b",
        folded,
    )
    return all(reference == expected_zip.casefold() for reference in zip_refs)


def evaluate_tau2_address_prewrite(trajectory: Any, tool_call: Any) -> dict[str, Any]:
    """Fail-closed preflight for pending-order shipping-address changes."""
    messages = _messages(trajectory)
    name = _get(tool_call, "name")
    arguments = _get(tool_call, "arguments", {})
    if name != "modify_pending_order_address" or not isinstance(arguments, dict):
        return {
            "decision": "NO_GO",
            "allowed": False,
            "blocking_checks": ["unsupported_or_malformed_tool_call"],
        }

    order_id = arguments.get("order_id")
    address_fields = {
        "address1": arguments.get("address1"),
        "address2": arguments.get("address2"),
        "city": arguments.get("city"),
        "state": arguments.get("state"),
        "country": arguments.get("country"),
        "zip": arguments.get("zip"),
    }
    required_fields_valid = all(
        isinstance(address_fields[field], str) and bool(address_fields[field].strip())
        for field in ("address1", "city", "state", "country", "zip")
    ) and isinstance(address_fields["address2"], str)

    order_args, order_before = _find_call_result(
        messages,
        {"get_order_details"},
        lambda call_args: call_args.get("order_id") == order_id,
    )
    order_is_object = isinstance(order_before, dict)
    snapshot_matches = order_is_object and order_before.get("order_id") == order_id
    order_status = order_before.get("status") if order_is_object else None
    owner_id = order_before.get("user_id") if order_is_object else None
    current_address = order_before.get("address") if order_is_object else None
    current_address_is_object = isinstance(current_address, dict)
    address_changes_state = (
        current_address_is_object
        and any(current_address.get(field) != value for field, value in address_fields.items())
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

    disclosed_values = [
        order_id,
        address_fields["address1"],
        address_fields["city"],
        address_fields["state"],
        address_fields["country"],
        address_fields["zip"],
    ]
    if address_fields["address2"]:
        disclosed_values.append(address_fields["address2"])
    address2_disclosed = bool(address_fields["address2"]) or any(
        phrase in last_assistant_text.casefold()
        for phrase in ("no secondary address line", "address2: none", "unit/apartment: none")
    )
    disclosure_valid = (
        required_fields_valid
        and all(isinstance(value, str) and value for value in disclosed_values)
        and last_assistant_text_index >= 0
        and _contains_all(last_assistant_text, disclosed_values)
        and "address" in last_assistant_text.casefold()
        and any(
            term in last_assistant_text.casefold()
            for term in ("update", "change")
        )
        and address2_disclosed
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
        prior_messages, order_id, "modify_pending_order_address"
    )
    reconfirmed_after_block = (
        latest_blocked_index < 0 or last_assistant_text_index > latest_blocked_index
    )
    confirmation_valid = (
        disclosure_valid
        and last_user_index > last_assistant_text_index
        and _is_affirmative(last_user_text)
        and _address_confirmation_references_consistent(
            last_user_text, order_id, address_fields["zip"]
        )
        and reconfirmed_after_block
        and last_user_index < current_message_index
    )
    snapshot_fresh = _order_snapshot_is_fresh(messages, order_id)

    checks = {
        "order_snapshot_matches_requested_order": snapshot_matches,
        "order_is_pending": order_status == "pending",
        "identity_and_order_ownership_verified": identity_valid,
        "new_address_fields_valid": required_fields_valid,
        "address_differs_from_current_order": address_changes_state,
        "exact_new_address_disclosed": disclosure_valid,
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
            "new_address": address_fields,
        },
    }
