"""user address pre-write policy for the pinned Tau2 retail simulator."""

from __future__ import annotations

import re
from typing import Any

from ai_workflow_assurance_mcp.tau2_prewrite_common import (
    _contains_all,
    _decode_tool_result,
    _find_call_result,
    _get,
    _is_affirmative,
    _messages,
    _tool_calls,
)


def _user_snapshot_is_fresh(messages: list[Any], user_id: Any) -> bool:
    """Require the latest user-details read to match and have no later user-address write."""
    if not isinstance(user_id, str) or not user_id:
        return False
    read_index = -1
    latest_read_matches = False
    for index, message in enumerate(messages):
        for call in _tool_calls(message):
            arguments = _get(call, "arguments", {})
            if (
                _get(call, "name") == "get_user_details"
                and isinstance(arguments, dict)
                and arguments.get("user_id") == user_id
            ):
                read_index = index
                snapshot = _decode_tool_result(messages, str(_get(call, "id", "")))
                latest_read_matches = (
                    isinstance(snapshot, dict) and snapshot.get("user_id") == user_id
                )
    if read_index < 0 or not latest_read_matches:
        return False
    for message in messages[read_index + 1 : -1]:
        for call in _tool_calls(message):
            arguments = _get(call, "arguments", {})
            if (
                _get(call, "name") == "modify_user_address"
                and isinstance(arguments, dict)
                and arguments.get("user_id") == user_id
            ):
                result_message = next(
                    (
                        candidate for candidate in messages
                        if _get(candidate, "role") == "tool"
                        and str(_get(candidate, "id", "")) == str(_get(call, "id", ""))
                    ),
                    None,
                )
                content = _get(result_message, "content", "") if result_message is not None else ""
                if not isinstance(content, str) or "AWA_PREWRITE_NO_GO" not in content:
                    return False
    return True


def _latest_blocked_user_write_result_index(
    messages: list[Any], user_id: Any, tool_name: str
) -> int:
    """Find the latest AWA-blocked write against the specified user."""
    latest_index = -1
    for message in messages:
        for call in _tool_calls(message):
            arguments = _get(call, "arguments", {})
            call_id = str(_get(call, "id", ""))
            if (
                _get(call, "name") != tool_name
                or not isinstance(arguments, dict)
                or arguments.get("user_id") != user_id
            ):
                continue
            for index, candidate in enumerate(messages):
                if (
                    _get(candidate, "role") == "tool"
                    and str(_get(candidate, "id", "")) == call_id
                ):
                    content = _get(candidate, "content", "")
                    if isinstance(content, str) and "AWA_PREWRITE_NO_GO" in content:
                        latest_index = max(latest_index, index)
                    break
    return latest_index


def evaluate_tau2_user_address_prewrite(trajectory: Any, tool_call: Any) -> dict[str, Any]:
    """Fail-closed preflight for changing a user's default address."""
    messages = _messages(trajectory)
    name = _get(tool_call, "name")
    arguments = _get(tool_call, "arguments", {})
    if name != "modify_user_address" or not isinstance(arguments, dict):
        return {
            "decision": "NO_GO",
            "allowed": False,
            "blocking_checks": ["unsupported_or_malformed_tool_call"],
        }

    user_id = arguments.get("user_id")
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

    user_args, user_before = _find_call_result(
        messages,
        {"get_user_details"},
        lambda call_args: call_args.get("user_id") == user_id,
    )
    user_is_object = isinstance(user_before, dict)
    snapshot_matches = user_is_object and user_before.get("user_id") == user_id
    current_address = user_before.get("address") if user_is_object else None
    current_address_is_object = isinstance(current_address, dict)
    address_changes_state = (
        current_address_is_object
        and any(current_address.get(field) != value for field, value in address_fields.items())
    )
    display_name = user_before.get("name") if user_is_object else None
    email = user_before.get("email") if user_is_object else None
    customer_identifier = display_name if isinstance(display_name, str) and display_name else (
        email if isinstance(email, str) and email else None
    )

    _, identity_result = _find_call_result(
        messages,
        {"find_user_id_by_name_zip", "find_user_id_by_email"},
        lambda _: True,
    )
    identity_id = identity_result.strip() if isinstance(identity_result, str) else None
    identity_valid = bool(
        identity_id and user_id and identity_id == user_id and user_args and snapshot_matches
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
        customer_identifier,
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
        all(isinstance(value, str) and value for value in disclosed_values)
        and last_assistant_text_index >= 0
        and _contains_all(last_assistant_text, disclosed_values)
        and "default address" in last_assistant_text.casefold()
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
    zip_refs = re.findall(
        r"\b(?:zip|postal(?:\s+code)?)\s*(?:is|:|#)?\s*([a-z0-9-]+)\b",
        last_user_text.casefold(),
    )
    postal_code_consistent = all(
        reference == address_fields["zip"].casefold() for reference in zip_refs
    ) if isinstance(address_fields["zip"], str) else False
    latest_blocked_index = _latest_blocked_user_write_result_index(
        prior_messages, user_id, "modify_user_address"
    )
    reconfirmed_after_block = (
        latest_blocked_index < 0 or last_assistant_text_index > latest_blocked_index
    )
    confirmation_valid = (
        disclosure_valid
        and last_user_index > last_assistant_text_index
        and _is_affirmative(last_user_text)
        and postal_code_consistent
        and reconfirmed_after_block
        and last_user_index < current_message_index
    )
    snapshot_fresh = _user_snapshot_is_fresh(messages, user_id)

    checks = {
        "user_snapshot_matches_requested_user": snapshot_matches,
        "identity_matches_user_details": identity_valid,
        "new_address_fields_valid": required_fields_valid,
        "address_differs_from_current_user_address": address_changes_state,
        "exact_new_address_and_customer_disclosed": disclosure_valid,
        "user_confirmed_after_disclosure": confirmation_valid,
        "user_reconfirmed_after_latest_blocked_attempt": reconfirmed_after_block,
        "user_snapshot_fresh": snapshot_fresh,
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
            "user_id": user_id if snapshot_matches else None,
            "customer_identifier": customer_identifier,
            "new_address": address_fields,
        },
    }
