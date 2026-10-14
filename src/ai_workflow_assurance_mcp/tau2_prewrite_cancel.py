"""cancel pre-write policy for the pinned Tau2 retail simulator."""

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
    _normalize_disclosure_text,
    _order_snapshot_is_fresh,
    _tool_calls,
)


def _cancel_confirmation_references_consistent(
    text: str, order_id: Any, reason: Any, payment_ids: list[str]
) -> bool:
    """Reject explicit order, cancellation-reason, or payment references that conflict."""
    if not isinstance(order_id, str) or not order_id or not isinstance(reason, str):
        return False
    folded = text.casefold()
    order_refs = _mentioned_order_ids(folded)
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
    normalized_disclosure = _normalize_disclosure_text(last_assistant_text)
    bank_refund_timing_valid = bool(
        re.search(r"\b5\s*(?:-|to)\s*7\s+business\s+days\b", normalized_disclosure)
    )
    disclosure_valid = (
        all(isinstance(item, str) and item for item in identifiers)
        and last_assistant_text_index >= 0
        and _contains_all(last_assistant_text, identifiers)
        and any(term in normalized_disclosure for term in ("cancel", "cancellation"))
        and refund_total_text in normalized_disclosure
        and "refund" in normalized_disclosure
        and refund_timing_valid
        and (
            not any(payment_id.startswith("gift_card_") for payment_id in payment_ids)
            or "immediately" in normalized_disclosure
        )
        and (
            not any(not payment_id.startswith("gift_card_") for payment_id in payment_ids)
            or bank_refund_timing_valid
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
        and _is_affirmative(last_user_text, action="cancel")
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
