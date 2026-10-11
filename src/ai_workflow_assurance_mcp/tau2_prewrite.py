"""Build a fail-closed preflight decision from Tau2's in-memory trajectory.

This adapter is designed for the pinned Tau2 retail simulator. Trajectory values
are simulator observations, not cryptographically authenticated production evidence.
"""
from __future__ import annotations

import json
import re
from collections import Counter
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


def _order_snapshot_is_fresh(messages: list[Any], order_id: Any) -> bool:
    """Require the latest matching order read to return that exact order, with no later write."""
    if not isinstance(order_id, str) or not order_id:
        return False
    write_tools = {
        "cancel_pending_order",
        "exchange_delivered_order_items",
        "modify_pending_order_address",
        "modify_pending_order_items",
        "modify_pending_order_payment",
        "modify_user_address",
        "return_delivered_order_items",
    }
    read_index = -1
    latest_read_matches = False
    for index, message in enumerate(messages):
        for call in _tool_calls(message):
            call_args = _get(call, "arguments", {})
            if (
                _get(call, "name") == "get_order_details"
                and isinstance(call_args, dict)
                and call_args.get("order_id") == order_id
            ):
                read_index = index
                snapshot = _decode_tool_result(messages, str(_get(call, "id", "")))
                latest_read_matches = (
                    isinstance(snapshot, dict) and snapshot.get("order_id") == order_id
                )
    if read_index < 0 or not latest_read_matches:
        return False

    # A write that the AWA dispatcher explicitly blocked never reached the environment.
    # Other write attempts (including tool errors) conservatively require a fresh read.
    for message in messages[read_index + 1 : -1]:
        for call in _tool_calls(message):
            call_args = _get(call, "arguments", {})
            if not (
                _get(call, "name") in write_tools
                and isinstance(call_args, dict)
                and call_args.get("order_id") == order_id
            ):
                continue
            call_id = str(_get(call, "id", ""))
            result_message = next(
                (
                    item for item in messages
                    if _get(item, "role") == "tool" and str(_get(item, "id", "")) == call_id
                ),
                None,
            )
            result_content = _get(result_message, "content", "") if result_message is not None else ""
            if isinstance(result_content, str) and "AWA_PREWRITE_NO_GO" in result_content:
                continue
            return False
    return True




def _variant_details(messages: list[Any]) -> dict[str, dict[str, Any]]:
    """Collect variant details from each product's latest read only."""
    latest_results: dict[str, Any] = {}
    for message in messages:
        for call in _tool_calls(message):
            if _get(call, "name") != "get_product_details":
                continue
            arguments = _get(call, "arguments", {})
            if not isinstance(arguments, dict):
                continue
            product_id = arguments.get("product_id")
            if not isinstance(product_id, str) or not product_id:
                continue
            result = _decode_tool_result(messages, str(_get(call, "id", "")))
            # A later failed/mismatched read supersedes an earlier snapshot; do not
            # retain stale availability from an older successful response.
            latest_results[product_id] = (
                result
                if isinstance(result, dict) and result.get("product_id") == product_id
                else None
            )

    details: dict[str, dict[str, Any]] = {}
    for product_id, result in latest_results.items():
        if not isinstance(result, dict):
            continue
        variants = result.get("variants")
        if not isinstance(variants, dict):
            continue
        for variant_id, variant in variants.items():
            if (
                isinstance(variant_id, str)
                and isinstance(variant, dict)
                and variant.get("item_id") == variant_id
            ):
                details[variant_id] = {
                    "product_id": product_id,
                    "price": variant.get("price"),
                    "available": variant.get("available") is True,
                }
    return details


def _exchange_price_difference(
    order_items: Any,
    old_items: Any,
    new_items: Any,
    variants: dict[str, dict[str, Any]],
) -> float | None:
    """Compute the same rounded total delta as the pinned Tau2 exchange tool."""
    if not isinstance(order_items, list) or not isinstance(old_items, list):
        return None
    if not isinstance(new_items, list) or len(old_items) != len(new_items):
        return None
    total = 0.0
    for old_item_id, new_item_id in zip(old_items, new_items, strict=True):
        old_item = next(
            (
                item for item in order_items
                if isinstance(item, dict) and item.get("item_id") == old_item_id
            ),
            None,
        )
        variant = variants.get(new_item_id) if isinstance(new_item_id, str) else None
        if not isinstance(old_item, dict) or not isinstance(variant, dict):
            return None
        old_price = old_item.get("price")
        new_price = variant.get("price")
        if (
            not isinstance(old_price, (int, float))
            or isinstance(old_price, bool)
            or not isinstance(new_price, (int, float))
            or isinstance(new_price, bool)
        ):
            return None
        total += float(new_price) - float(old_price)
    return round(total, 2)


def _price_difference_disclosed(text: str, price_difference: float | None) -> bool:
    """Require the amount and direction (charge/refund/no delta) in assistant disclosure."""
    if price_difference is None or f"{abs(price_difference):.2f}" not in text:
        return False
    folded = text.casefold()
    if price_difference > 0:
        return any(term in folded for term in ("charge", "pay an additional", "additional payment"))
    if price_difference < 0:
        return any(term in folded for term in ("refund", "credit"))
    return "no price difference" in folded or "no additional charge" in folded


def _confirmation_references_consistent(
    text: str,
    expected_order_id: Any,
    expected_old_items: Any,
    expected_new_items: Any,
    expected_payment_id: Any,
) -> bool:
    """Reject explicit order, item, or payment identifiers that conflict with the action."""
    if not all(
        isinstance(value, str) and value
        for value in [expected_order_id, expected_payment_id]
    ):
        return False
    if not isinstance(expected_old_items, list) or not isinstance(expected_new_items, list):
        return False

    folded = text.casefold()
    payment_refs = re.findall(r"\b(?:credit_card|payment_method)[_-][a-z0-9_-]+\b", folded)
    if any(reference != expected_payment_id.casefold() for reference in payment_refs):
        return False

    # Order IDs in Tau2 use an alphabetic prefix (e.g. W2378156). Only compare
    # explicit order/hash references; ordinary prose is not interpreted as an ID.
    order_pattern = r"([a-z][a-z0-9_-]*\d[a-z0-9_-]*)"
    order_refs = re.findall(r"\border\s*#?\s*" + order_pattern + r"\b", folded)
    order_refs += re.findall(r"#" + order_pattern + r"\b", folded)
    expected_order_reference = expected_order_id.casefold().lstrip("#")
    if any(reference != expected_order_reference for reference in order_refs):
        return False

    expected_items = {str(item) for item in [*expected_old_items, *expected_new_items]}
    mentioned_numeric_ids = re.findall(r"\b\d{8,}\b", folded)
    if any(reference not in expected_items for reference in mentioned_numeric_ids):
        return False
    return True


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


def _latest_blocked_write_result_index(
    messages: list[Any], order_id: Any, tool_name: str
) -> int:
    """Find the latest preflight-blocked attempt for this order and write tool."""
    latest_index = -1
    for message in messages:
        for call in _tool_calls(message):
            arguments = _get(call, "arguments", {})
            if (
                _get(call, "name") != tool_name
                or not isinstance(arguments, dict)
                or arguments.get("order_id") != order_id
            ):
                continue
            call_id = str(_get(call, "id", ""))
            for index, candidate in enumerate(messages):
                if _get(candidate, "role") != "tool" or str(_get(candidate, "id", "")) != call_id:
                    continue
                content = _get(candidate, "content", "")
                if isinstance(content, str) and "AWA_PREWRITE_NO_GO" in content:
                    latest_index = max(latest_index, index)
                break
    return latest_index


def evaluate_tau2_prewrite(
    trajectory: Any,
    tool_call: Any,
    *,
    expected_tool_name: str = "exchange_delivered_order_items",
    expected_order_status: str = "delivered",
) -> dict[str, Any]:
    """Evaluate an item exchange/modification immediately before its execution."""
    messages = _messages(trajectory)
    name = _get(tool_call, "name")
    arguments = _get(tool_call, "arguments", {})
    if name != expected_tool_name or not isinstance(arguments, dict):
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
    order_snapshot_matches_request = (
        order_is_object and order_before.get("order_id") == order_id
    )
    owner_id = order_before.get("user_id") if order_is_object else None
    order_status = order_before.get("status") if order_is_object else None

    order_items = order_before.get("items") if order_is_object else None
    order_item_ids = [
        item.get("item_id")
        for item in order_items
        if isinstance(item, dict) and isinstance(item.get("item_id"), str)
    ] if isinstance(order_items, list) else []
    old_items_are_strings = (
        isinstance(old_items, list) and all(isinstance(item, str) and item for item in old_items)
    )
    new_items_are_strings = (
        isinstance(new_items, list) and all(isinstance(item, str) and item for item in new_items)
    )
    old_items_belong_to_order = (
        order_snapshot_matches_request
        and old_items_are_strings
        and Counter(old_items) <= Counter(order_item_ids)
    )
    variants = _variant_details(messages)
    new_items_verified_available = (
        new_items_are_strings
        and all(
            item_id in variants and variants[item_id]["available"] is True
            for item_id in new_items
        )
    )
    new_items_match_old_product_types = (
        isinstance(order_items, list)
        and old_items_are_strings
        and new_items_are_strings
        and len(old_items) == len(new_items)
        and all(
            (old_item := next(
                (
                    item for item in order_items
                    if isinstance(item, dict) and item.get("item_id") == old_item_id
                ),
                None,
            )) is not None
            and new_item_id in variants
            and old_item.get("product_id") == variants[new_item_id].get("product_id")
            for old_item_id, new_item_id in zip(old_items, new_items, strict=True)
        )
    )
    price_difference = _exchange_price_difference(order_items, old_items, new_items, variants)
    payment_history = order_before.get("payment_history") if order_is_object else None
    payment_method_belongs_to_order = (
        isinstance(payment_id, str)
        and isinstance(payment_history, list)
        and any(
            isinstance(payment, dict)
            and payment.get("transaction_type") == "payment"
            and payment.get("payment_method_id") == payment_id
            for payment in payment_history
        )
    )

    _, identity_result = _find_call_result(
        messages,
        {"find_user_id_by_name_zip", "find_user_id_by_email"},
        lambda _: True,
    )
    identity_id = identity_result.strip() if isinstance(identity_result, str) else None
    identity_valid = bool(
        identity_id and owner_id and identity_id == owner_id and order_args
        and order_snapshot_matches_request
    )

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

    price_difference_disclosed = _price_difference_disclosed(last_assistant_text, price_difference)
    latest_blocked_attempt_index = _latest_blocked_write_result_index(
        prior_messages, order_id, expected_tool_name
    )
    reconfirmed_after_block = (
        latest_blocked_attempt_index < 0
        or last_assistant_text_index > latest_blocked_attempt_index
    )

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
        and _confirmation_references_consistent(
            last_user_text, order_id, old_items, new_items, payment_id
        )
        and reconfirmed_after_block
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
    result = evaluate_prewrite(action, evidence, expected_order_status=expected_order_status)
    order_snapshot_fresh = _order_snapshot_is_fresh(messages, order_id)
    extra_checks = {
        "order_snapshot_matches_requested_order": order_snapshot_matches_request,
        "order_status_matches_required_state": order_status == expected_order_status,
        "old_item_multiplicity_does_not_exceed_order_quantity": old_items_belong_to_order,
        "new_items_are_verified_available_variants": new_items_verified_available,
        "new_items_match_the_corresponding_old_product_types": new_items_match_old_product_types,
        "payment_method_belongs_to_order": payment_method_belongs_to_order,
        "exact_price_difference_and_direction_disclosed": price_difference_disclosed,
    }
    for check_name, passed in extra_checks.items():
        result.setdefault("checked", {})[check_name] = passed
        if not passed:
            result["blocking_checks"] = list(dict.fromkeys([
                *result.get("blocking_checks", []), check_name,
            ]))
    if not order_snapshot_fresh:
        result["blocking_checks"] = list(dict.fromkeys([
            *result.get("blocking_checks", []),
            "order_snapshot_stale_after_prior_write_attempt",
        ]))
        result.setdefault("checked", {})["order_snapshot_fresh"] = False
    else:
        result.setdefault("checked", {})["order_snapshot_fresh"] = True
    if result.get("blocking_checks"):
        result["decision"] = "NO_GO"
        result["allowed"] = False
    result["scope"] = "pinned_tau2_simulator_trajectory_not_production_identity_evidence"
    result["evidence_summary"] = {
        "identity_matches_order_owner": identity_valid,
        "order_status": order_status,
        "order_snapshot_matches_requested_order": order_snapshot_matches_request,
        "old_item_multiplicity_does_not_exceed_order_quantity": old_items_belong_to_order,
        "new_items_are_verified_available_variants": new_items_verified_available,
        "new_items_match_the_corresponding_old_product_types": new_items_match_old_product_types,
        "payment_method_belongs_to_order": payment_method_belongs_to_order,
        "price_difference": price_difference,
        "exact_price_difference_and_direction_disclosed": price_difference_disclosed,
        "order_snapshot_fresh": order_snapshot_fresh,
        "assistant_disclosed_exact_order_items_and_payment": disclosure_valid,
        "user_affirmed_after_disclosure": confirmation_valid,
        "user_reconfirmed_after_latest_blocked_attempt": reconfirmed_after_block,
    }
    return result


def _cancel_confirmation_references_consistent(
    text: str, order_id: Any, reason: Any, payment_ids: list[str]
) -> bool:
    """Reject explicit order, cancellation-reason, or payment references that conflict."""
    if not isinstance(order_id, str) or not order_id or not isinstance(reason, str):
        return False
    folded = text.casefold()
    order_pattern = r"([a-z][a-z0-9_-]*\d[a-z0-9_-]*)"
    order_refs = re.findall(r"\border\s*#?\s*" + order_pattern + r"\b", folded)
    order_refs += re.findall(r"#" + order_pattern + r"\b", folded)
    expected_order_reference = order_id.casefold().lstrip("#")
    if any(reference != expected_order_reference for reference in order_refs):
        return False
    payment_refs = re.findall(
        r"\b(?:credit_card|gift_card|paypal|payment_method)[_-][a-z0-9_-]+\b",
        folded,
    )
    if any(reference not in {item.casefold() for item in payment_ids} for reference in payment_refs):
        return False
    known_reasons = {"no longer needed", "ordered by mistake"}
    mentioned_reasons = {candidate for candidate in known_reasons if candidate in folded}
    if any(candidate != reason.casefold() for candidate in mentioned_reasons):
        return False
    return True


def evaluate_tau2_cancel_prewrite(trajectory: Any, tool_call: Any) -> dict[str, Any]:
    """Fail-closed preflight for Tau2 pending-order cancellation and refund."""
    messages = _messages(trajectory)
    name = _get(tool_call, "name")
    arguments = _get(tool_call, "arguments", {})
    if name != "cancel_pending_order" or not isinstance(arguments, dict):
        return {
            "decision": "NO_GO",
            "allowed": False,
            "blocking_checks": ["unsupported_or_malformed_tool_call"],
        }

    order_id = arguments.get("order_id")
    reason = arguments.get("reason")
    order_args, order_before = _find_call_result(
        messages,
        {"get_order_details"},
        lambda call_args: call_args.get("order_id") == order_id,
    )
    order_is_object = isinstance(order_before, dict)
    snapshot_matches = order_is_object and order_before.get("order_id") == order_id
    order_status = order_before.get("status") if order_is_object else None
    owner_id = order_before.get("user_id") if order_is_object else None

    _, identity_result = _find_call_result(
        messages,
        {"find_user_id_by_name_zip", "find_user_id_by_email"},
        lambda _: True,
    )
    identity_id = identity_result.strip() if isinstance(identity_result, str) else None
    identity_valid = bool(
        identity_id and owner_id and identity_id == owner_id and order_args and snapshot_matches
    )

    payment_history = order_before.get("payment_history") if order_is_object else None
    payments_valid = (
        isinstance(payment_history, list)
        and bool(payment_history)
        and all(
            isinstance(payment, dict)
            and payment.get("transaction_type") == "payment"
            and isinstance(payment.get("payment_method_id"), str)
            and bool(payment.get("payment_method_id"))
            and isinstance(payment.get("amount"), (int, float))
            and not isinstance(payment.get("amount"), bool)
            and payment.get("amount") >= 0
            for payment in payment_history
        )
    )
    payments = payment_history if payments_valid else []
    payment_ids = [payment["payment_method_id"] for payment in payments]
    refund_total = round(sum(float(payment["amount"]) for payment in payments), 2) if payments_valid else None
    refund_total_text = f"{refund_total:.2f}" if refund_total is not None else ""
    refund_timing_valid = payments_valid

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

    identifiers = [order_id, reason, *payment_ids]
    disclosure_valid = (
        all(isinstance(item, str) and item for item in identifiers)
        and last_assistant_text_index >= 0
        and _contains_all(last_assistant_text, identifiers)
        and refund_total_text in last_assistant_text
        and "refund" in last_assistant_text.casefold()
        and refund_timing_valid
        and (
            not any(payment_id.startswith("gift_card_") for payment_id in payment_ids)
            or "immediately" in last_assistant_text.casefold()
        )
        and (
            not any(not payment_id.startswith("gift_card_") for payment_id in payment_ids)
            or "5-7 business days" in last_assistant_text.casefold()
        )
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
        prior_messages, order_id, "cancel_pending_order"
    )
    reconfirmed_after_block = (
        latest_blocked_index < 0 or last_assistant_text_index > latest_blocked_index
    )
    confirmation_valid = (
        disclosure_valid
        and last_user_index > last_assistant_text_index
        and _is_affirmative(last_user_text)
        and _cancel_confirmation_references_consistent(
            last_user_text, order_id, reason, payment_ids
        )
        and reconfirmed_after_block
        and last_user_index < current_message_index
    )
    snapshot_fresh = _order_snapshot_is_fresh(messages, order_id)

    checks = {
        "order_snapshot_matches_requested_order": snapshot_matches,
        "order_is_pending": order_status == "pending",
        "identity_and_order_ownership_verified": identity_valid,
        "cancellation_reason_supported": reason in {"no longer needed", "ordered by mistake"},
        "refund_history_supported": payments_valid,
        "exact_cancellation_and_refund_disclosure_valid": disclosure_valid,
        "user_confirmed_after_disclosure": confirmation_valid,
        "user_reconfirmed_after_latest_blocked_attempt": reconfirmed_after_block,
        "order_snapshot_fresh": snapshot_fresh,
    }
    blocking = [name for name, passed in checks.items() if not passed]
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
            "cancellation_reason": reason,
            "refund_total": refund_total,
            "refund_payment_method_ids": payment_ids,
        },
    }


def _address_confirmation_references_consistent(
    text: str, order_id: Any, expected_zip: Any
) -> bool:
    """Reject explicit conflicting order IDs or postal codes in an address confirmation."""
    if not isinstance(order_id, str) or not order_id or not isinstance(expected_zip, str):
        return False
    folded = text.casefold()
    order_pattern = r"([a-z][a-z0-9_-]*\d[a-z0-9_-]*)"
    order_refs = re.findall(r"\border\s*#?\s*" + order_pattern + r"\b", folded)
    order_refs += re.findall(r"#" + order_pattern + r"\b", folded)
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


def _order_and_payment_references_consistent(
    text: str, order_id: Any, payment_ids: list[str]
) -> bool:
    """Reject explicit conflicting order or payment identifiers in a confirmation."""
    if not isinstance(order_id, str) or not order_id:
        return False
    folded = text.casefold()
    order_pattern = r"([a-z][a-z0-9_-]*\d[a-z0-9_-]*)"
    order_refs = re.findall(r"\border\s*#?\s*" + order_pattern + r"\b", folded)
    order_refs += re.findall(r"#" + order_pattern + r"\b", folded)
    if any(reference != order_id.casefold().lstrip("#") for reference in order_refs):
        return False
    payment_refs = re.findall(
        r"\b(?:credit_card|gift_card|paypal|payment_method)[_-][a-z0-9_-]+\b",
        folded,
    )
    allowed = {payment_id.casefold() for payment_id in payment_ids}
    return all(reference in allowed for reference in payment_refs)


def evaluate_tau2_payment_prewrite(trajectory: Any, tool_call: Any) -> dict[str, Any]:
    """Fail-closed preflight for changing a pending order's payment method."""
    messages = _messages(trajectory)
    name = _get(tool_call, "name")
    arguments = _get(tool_call, "arguments", {})
    if name != "modify_pending_order_payment" or not isinstance(arguments, dict):
        return {
            "decision": "NO_GO",
            "allowed": False,
            "blocking_checks": ["unsupported_or_malformed_tool_call"],
        }

    order_id = arguments.get("order_id")
    new_payment_id = arguments.get("payment_method_id")
    order_args, order_before = _find_call_result(
        messages,
        {"get_order_details"},
        lambda call_args: call_args.get("order_id") == order_id,
    )
    order_is_object = isinstance(order_before, dict)
    snapshot_matches = order_is_object and order_before.get("order_id") == order_id
    order_status = order_before.get("status") if order_is_object else None
    owner_id = order_before.get("user_id") if order_is_object else None

    _, identity_result = _find_call_result(
        messages,
        {"find_user_id_by_name_zip", "find_user_id_by_email"},
        lambda _: True,
    )
    identity_id = identity_result.strip() if isinstance(identity_result, str) else None
    identity_valid = bool(
        identity_id and owner_id and identity_id == owner_id and order_args and snapshot_matches
    )

    payment_history = order_before.get("payment_history") if order_is_object else None
    payment_history_valid = (
        isinstance(payment_history, list)
        and len(payment_history) == 1
        and isinstance(payment_history[0], dict)
        and payment_history[0].get("transaction_type") == "payment"
        and isinstance(payment_history[0].get("payment_method_id"), str)
        and bool(payment_history[0].get("payment_method_id"))
    )
    old_payment_id = (
        payment_history[0].get("payment_method_id") if payment_history_valid else None
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
    new_method = (
        payment_methods.get(new_payment_id)
        if isinstance(payment_methods, dict) and isinstance(new_payment_id, str)
        else None
    )
    new_method_valid = (
        isinstance(new_method, dict)
        and new_method.get("id") == new_payment_id
        and new_method.get("source") in {"credit_card", "gift_card", "paypal"}
    )
    payment_method_changes = (
        isinstance(new_payment_id, str)
        and bool(new_payment_id)
        and isinstance(old_payment_id, str)
        and new_payment_id != old_payment_id
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

    method_details = []
    if new_method_valid:
        source = new_method.get("source")
        if isinstance(source, str):
            method_details.append(source.replace("_", " "))
        for field in ("brand", "last_four"):
            value = new_method.get(field)
            if isinstance(value, str) and value:
                method_details.append(value)
    disclosure_values = [order_id, old_payment_id, new_payment_id, *method_details]
    disclosure_valid = (
        all(isinstance(value, str) and value for value in disclosure_values)
        and new_method_valid
        and last_assistant_text_index >= 0
        and _contains_all(last_assistant_text, disclosure_values)
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
        prior_messages, order_id, "modify_pending_order_payment"
    )
    reconfirmed_after_block = (
        latest_blocked_index < 0 or last_assistant_text_index > latest_blocked_index
    )
    confirmation_valid = (
        disclosure_valid
        and last_user_index > last_assistant_text_index
        and _is_affirmative(last_user_text)
        and _order_and_payment_references_consistent(
            last_user_text, order_id, [value for value in (old_payment_id, new_payment_id) if isinstance(value, str)]
        )
        and reconfirmed_after_block
        and last_user_index < current_message_index
    )
    snapshot_fresh = _order_snapshot_is_fresh(messages, order_id)

    checks = {
        "order_snapshot_matches_requested_order": snapshot_matches,
        "order_is_pending": order_status == "pending",
        "identity_and_order_ownership_verified": identity_valid,
        "exactly_one_current_payment_transaction": payment_history_valid,
        "new_payment_method_belongs_to_order_owner": user_details_valid and new_method_valid,
        "payment_method_is_changed": payment_method_changes,
        "exact_old_and_new_payment_details_disclosed": disclosure_valid,
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
            "old_payment_method_id": old_payment_id,
            "new_payment_method_id": new_payment_id,
            "new_payment_method_source": new_method.get("source") if new_method_valid else None,
        },
    }


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
    """Apply the item policy to pending orders and enforce Tau2's one-modification limit."""
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
