"""Fail-closed, exchange-specific reference preflight for delivered retail orders.

This policy validates replacement of old item IDs with new item IDs, including
payment-method disclosure. It is not a generic policy for arbitrary sensitive
writes such as cancellation or address changes.

The module evaluates normalized intent/evidence only. It does not execute or
intercept a write; the calling application must enforce an allow decision.
"""
from __future__ import annotations

from typing import Any


def _nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _nonempty_string_list(value: Any) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and all(_nonempty_string(item) for item in value)
    )


def evaluate_prewrite(
    action: Any, evidence: Any, *, expected_order_status: str = "delivered"
) -> dict[str, Any]:
    """Return GO only when supplied values satisfy the retail item-exchange policy.

    This function validates structure and consistency; it does not authenticate the
    evidence values or prove their provenance. Callers must obtain them from trusted
    sources and enforce the result at the actual write boundary. Do not reuse this
    evaluator for other write types; each operation needs its own policy.
    """
    failures: list[str] = []

    if not isinstance(action, dict):
        return {
            "decision": "NO_GO",
            "allowed": False,
            "blocking_checks": ["action_not_object"],
            "scope": "reference_preflight_only_not_a_write_interceptor",
            "evidence_trust_boundary": "caller_supplied_not_authenticated",
        }
    if not isinstance(evidence, dict):
        return {
            "decision": "NO_GO",
            "allowed": False,
            "blocking_checks": ["evidence_not_object"],
            "scope": "reference_preflight_only_not_a_write_interceptor",
            "evidence_trust_boundary": "caller_supplied_not_authenticated",
        }

    order_id = action.get("order_id")
    old_items = action.get("old_item_ids")
    new_items = action.get("new_item_ids")
    payment_id = action.get("payment_method_id")

    action_valid = (
        _nonempty_string(order_id)
        and _nonempty_string_list(old_items)
        and _nonempty_string_list(new_items)
        and len(old_items) == len(new_items)
        and _nonempty_string(payment_id)
        and set(old_items).isdisjoint(set(new_items))
    )
    if not action_valid:
        failures.append("action_incomplete_or_invalid")

    identity_valid = (
        evidence.get("identity_verified") is True
        and _nonempty_string(evidence.get("verified_user_id"))
        and _nonempty_string(evidence.get("order_owner_id"))
        and evidence.get("verified_user_id") == evidence.get("order_owner_id")
        and evidence.get("order_id") == order_id
    )
    if not identity_valid:
        failures.append("identity_or_order_ownership_not_verified")

    if evidence.get("order_status") != expected_order_status:
        failures.append(f"order_not_confirmed_{expected_order_status}")

    confirmation = evidence.get("confirmation")
    confirmation_valid = (
        isinstance(confirmation, dict)
        and confirmation.get("confirmed") is True
        and confirmation.get("order_id") == order_id
        and confirmation.get("old_item_ids") == old_items
        and confirmation.get("new_item_ids") == new_items
        and confirmation.get("payment_method_id") == payment_id
        and _nonempty_string(confirmation.get("confirmation_id"))
    )
    if not confirmation_valid:
        failures.append("explicit_confirmation_does_not_match_action")

    customer_facing = evidence.get("customer_facing_confirmation")
    disclosure_valid = (
        isinstance(customer_facing, dict)
        and customer_facing.get("order_id") == order_id
        and customer_facing.get("old_item_ids") == old_items
        and customer_facing.get("new_item_ids") == new_items
        and customer_facing.get("payment_method_id") == payment_id
        and customer_facing.get("payment_method_disclosed") is True
    )
    if not disclosure_valid:
        failures.append("exact_action_or_payment_method_not_disclosed_to_customer")

    confirmation_sequence = evidence.get("confirmation_event_sequence")
    proposed_write_sequence = evidence.get("proposed_write_sequence")
    sequence_valid = (
        type(confirmation_sequence) is int
        and confirmation_sequence > 0
        and type(proposed_write_sequence) is int
        and proposed_write_sequence > confirmation_sequence
    )
    if not sequence_valid:
        failures.append("confirmation_not_proven_to_precede_write")

    # Stable ordering and deduplication make this suitable for deterministic audit tests.
    blocking = list(dict.fromkeys(failures))
    return {
        "decision": "GO" if not blocking else "NO_GO",
        "allowed": not blocking,
        "blocking_checks": blocking,
        "checked": {
            "action_shape": action_valid,
            "identity_and_ownership": identity_valid,
            "delivered_order": evidence.get("order_status") == "delivered",
            "confirmation_matches_action": confirmation_valid,
            "customer_disclosure_matches_action": disclosure_valid,
            "confirmation_precedes_write": sequence_valid,
        },
        "scope": "reference_preflight_only_not_a_write_interceptor",
        "evidence_trust_boundary": "caller_supplied_not_authenticated",
        "enforcement_note": (
            "The caller must block the write unless decision is GO; this function does not "
            "execute, authorize, or intercept external operations."
        ),
    }
