"""exchange pre-write policy for the pinned Tau2 retail simulator."""

from __future__ import annotations

import re
from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Any

from ai_workflow_assurance_mcp.prewrite_guard import evaluate_prewrite
from ai_workflow_assurance_mcp.tau2_prewrite_common import (
    _assistant_variant_claims_match_catalog,
    _confirmation_references_consistent,
    _contains_all,
    _evaluate_exchange_confirmation_context,
    _exchange_price_difference,
    _exchange_pairing_disclosed,
    _find_call_result,
    _get,
    _is_affirmative,
    _latest_blocked_write_result_index,
    _messages,
    _normalize_disclosure_text,
    _order_snapshot_is_fresh,
    _price_difference_disclosed,
    _tool_calls,
    _variant_details,
)


def _phrase_present(text: str, phrase: str) -> bool:
    """Match a complete, normalized phrase in customer-facing disclosure text."""
    normalized_text = _normalize_disclosure_text(text).casefold().replace("-", " ")
    normalized_phrase = _normalize_disclosure_text(phrase).casefold().replace("-", " ")
    if not normalized_phrase:
        return False
    pattern = (
        r"(?<![a-z0-9])"
        + re.escape(normalized_phrase).replace(r"\ ", r"\s+")
        + r"(?![a-z0-9])"
    )
    return bool(re.search(pattern, normalized_text))


_OPTION_PHRASES: dict[str, dict[str, tuple[str, ...]]] = {
    "switch type": {
        "linear": ("linear",),
        "tactile": ("tactile",),
        "clicky": ("clicky",),
    },
    "backlight": {
        "rgb": ("rgb",),
        "white": ("white backlight", "white"),
        "none": ("no backlight", "without backlight", "backlight none", "none"),
    },
    "size": {
        "full size": ("full size", "full-size"),
        "80%": ("80%",),
        "60%": ("60%",),
    },
    "compatibility": {
        "google assistant": ("google assistant", "google home"),
        "apple homekit": ("apple homekit", "homekit"),
        "amazon alexa": ("amazon alexa", "alexa"),
    },
    "color": {
        "black": ("black",),
        "white": ("white",),
        "blue": ("blue",),
        "gold": ("gold",),
        "stainless steel": ("stainless steel",),
    },
}


def _semantic_options_match(segment: str, options: Any) -> bool:
    """Require all catalog options and reject conflicting values for known options."""
    if not isinstance(options, dict) or not options:
        return False
    for raw_key, raw_value in options.items():
        if not isinstance(raw_key, str) or not isinstance(raw_value, str) or not raw_value:
            return False
        key = raw_key.casefold()
        value = raw_value.casefold()
        known_values = _OPTION_PHRASES.get(key)
        selected_aliases = (
            known_values.get(value, (raw_value,))
            if known_values is not None
            else (raw_value,)
        )
        if not any(_phrase_present(segment, alias) for alias in selected_aliases):
            return False
        if known_values is not None:
            # A disclosure cannot describe a different value for the same option.
            for other_value, aliases in known_values.items():
                if other_value == value:
                    continue
                if any(_phrase_present(segment, alias) for alias in aliases):
                    return False
    return True


def _segment_has_exact_price(segment: str, expected_price: Any) -> bool:
    """Require exactly one disclosed amount and match it to the observed catalog value."""
    if expected_price is None:
        return False
    amounts = re.findall(
        r"\$\s*((?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2})(?!\d)",
        segment,
    )
    if len(amounts) != 1:
        return False
    try:
        observed = Decimal(amounts[0].replace(",", "")).quantize(Decimal("0.01"))
        expected = Decimal(str(expected_price)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return False
    return observed == expected


def _semantic_exchange_disclosure_matches(
    disclosure_text: str,
    order_id: Any,
    old_items: Any,
    new_items: Any,
    payment_id: Any,
    price_difference: float | None,
    order_items: Any,
    variants: dict[str, dict[str, Any]],
) -> bool:
    """Verify natural-language old/new descriptions against the order and catalog.

    Internal item IDs are not required in text shown to the customer. In their place,
    every old/new pair must be explicitly labeled and match the observed product name,
    every option, and exact price. The order ID, payment-method ID, and labeled price
    difference/direction remain mandatory. Any long numeric ID in this fallback forces
    the strict identifier-pairing path, so malformed or reordered IDs cannot be ignored.
    """
    if (
        not isinstance(disclosure_text, str)
        or not disclosure_text.strip()
        or not isinstance(order_id, str)
        or not isinstance(payment_id, str)
        or not isinstance(old_items, list)
        or not isinstance(new_items, list)
        or not old_items
        or len(old_items) != len(new_items)
        or not isinstance(order_items, list)
    ):
        return False
    if not _contains_all(disclosure_text, [order_id, payment_id]):
        return False
    if not any(term in disclosure_text.casefold() for term in ("exchange", "replace", "swap")):
        return False
    if not _price_difference_disclosed(disclosure_text, price_difference):
        return False

    # This fallback applies only to human-readable descriptions. If long numeric
    # item IDs appear, require the existing strict ordered-ID check instead.
    if re.search(r"(?<![a-z0-9_])\d{8,}(?![a-z0-9_])", disclosure_text.casefold()):
        return False

    markers = list(
        re.finditer(r"\b(old item|new item|price difference)\s*:", disclosure_text, re.IGNORECASE)
    )
    expected_labels = [
        label
        for _ in old_items
        for label in ("old item", "new item")
    ] + ["price difference"]
    if [marker.group(1).casefold() for marker in markers] != expected_labels:
        return False

    for pair_index, (old_item_id, new_item_id) in enumerate(
        zip(old_items, new_items, strict=True)
    ):
        if not isinstance(old_item_id, str) or not isinstance(new_item_id, str):
            return False
        old_item = next(
            (
                item for item in order_items
                if isinstance(item, dict) and item.get("item_id") == old_item_id
            ),
            None,
        )
        variant = variants.get(new_item_id)
        if not isinstance(old_item, dict) or not isinstance(variant, dict):
            return False
        if variant.get("available") is not True:
            return False
        if old_item.get("product_id") != variant.get("product_id"):
            return False

        old_segment = disclosure_text[markers[pair_index * 2].end():markers[pair_index * 2 + 1].start()]
        next_marker_index = pair_index * 2 + 2
        new_segment = disclosure_text[markers[pair_index * 2 + 1].end():markers[next_marker_index].start()]
        product_name = old_item.get("name")
        if not isinstance(product_name, str) or not product_name.strip():
            return False
        if not _phrase_present(old_segment, product_name) or not _phrase_present(new_segment, product_name):
            return False
        if not _semantic_options_match(old_segment, old_item.get("options")):
            return False
        if not _semantic_options_match(new_segment, variant.get("options")):
            return False
        if not _segment_has_exact_price(old_segment, old_item.get("price")):
            return False
        if not _segment_has_exact_price(new_segment, variant.get("price")):
            return False

    return True


def _payment_method_display_disclosed(
    messages: list[Any], owner_id: Any, payment_id: Any, disclosure_text: str,
) -> bool:
    """Match a customer-safe card brand and last four to the selected payment ID.

    The payment ID is an internal database reference. Do not require the agent to
    expose it to the customer when a verified card descriptor (brand + last four)
    identifies the exact same payment method in the owner's profile.
    """
    if (
        not isinstance(owner_id, str) or not owner_id
        or not isinstance(payment_id, str) or not payment_id
        or not isinstance(disclosure_text, str) or not disclosure_text.strip()
    ):
        return False
    _, profile = _find_call_result(
        messages,
        {"get_user_details"},
        lambda call_args: call_args.get("user_id") == owner_id,
    )
    if not isinstance(profile, dict) or profile.get("user_id") != owner_id:
        return False
    payment_methods = profile.get("payment_methods")
    if not isinstance(payment_methods, dict):
        return False
    method = payment_methods.get(payment_id)
    if (
        not isinstance(method, dict)
        or method.get("id") != payment_id
        or method.get("source") != "credit_card"
    ):
        return False
    brand = method.get("brand")
    last_four = method.get("last_four")
    if (
        not isinstance(brand, str) or not brand.strip()
        or not isinstance(last_four, str) or not re.fullmatch(r"\d{4}", last_four)
    ):
        return False
    normalized = _normalize_disclosure_text(disclosure_text)
    # Require brand and last four in one short card descriptor, with an explicit
    # "ending in"/"last four" link. A generic mention of a brand is insufficient.
    pattern = (
        r"(?<![a-z0-9])" + re.escape(brand.casefold()) + r"(?![a-z0-9])"
        + r".{0,48}"
        + r"\b(?:ending(?:\s+in)?|last\s+(?:four|4)(?:\s+digits?)?)\s+"
        + re.escape(last_four) + r"(?!\d)"
    )
    return re.search(pattern, normalized, re.IGNORECASE) is not None


def _customer_safe_exchange_disclosure_matches(
    disclosure_text: str,
    order_id: Any,
    old_items: Any,
    new_items: Any,
    payment_method_disclosed: bool,
    price_difference_disclosed: bool,
) -> bool:
    """Require exact order/item references plus verified customer-safe payment wording."""
    if (
        not isinstance(order_id, str) or not order_id
        or not isinstance(old_items, list) or not old_items
        or not isinstance(new_items, list) or len(old_items) != len(new_items)
        or not all(isinstance(item, str) and item for item in [*old_items, *new_items])
        or not isinstance(disclosure_text, str)
    ):
        return False
    return bool(
        _contains_all(disclosure_text, [order_id, *old_items, *new_items])
        and _exchange_pairing_disclosed(disclosure_text, old_items, new_items)
        and any(term in disclosure_text.casefold() for term in ("exchange", "replace", "swap"))
        and payment_method_disclosed
        and price_difference_disclosed
    )


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

    latest_blocked_attempt_index = _latest_blocked_write_result_index(
        prior_messages, order_id, expected_tool_name
    )
    reconfirmed_after_block = (
        latest_blocked_attempt_index < 0
        or last_assistant_text_index > latest_blocked_attempt_index
    )

    last_user_index = -1
    last_user_text = ""
    for index, message in enumerate(prior_messages):
        if index > last_assistant_text_index and _get(message, "role") == "user":
            text = _get(message, "content")
            if isinstance(text, str):
                last_user_index = index
                last_user_text = text

    confirmation_context = _evaluate_exchange_confirmation_context(
        last_assistant_text, last_user_text, order_id, old_items, new_items,
        payment_id, price_difference,
    )
    # Prefer strict item-ID disclosure when the agent provides it. If it uses
    # customer-friendly descriptions instead, verify each ordered pair against
    # the trusted order snapshot and catalog response; do not weaken the boundary
    # by accepting descriptions that omit or misstate an option or price.
    semantic_disclosure_valid = _semantic_exchange_disclosure_matches(
        last_assistant_text,
        order_id,
        old_items,
        new_items,
        payment_id,
        price_difference,
        order_items,
        variants,
    )
    price_difference_disclosed = confirmation_context["price_difference_disclosed"]
    payment_display_disclosed = _payment_method_display_disclosed(
        messages, owner_id, payment_id, last_assistant_text,
    )
    customer_safe_disclosure_valid = _customer_safe_exchange_disclosure_matches(
        last_assistant_text, order_id, old_items, new_items,
        payment_display_disclosed, price_difference_disclosed,
    )
    pairing_disclosed = (
        confirmation_context["pairing_disclosed"]
        or semantic_disclosure_valid
        or customer_safe_disclosure_valid
    )
    disclosure_valid = (
        confirmation_context["disclosure_valid"]
        or semantic_disclosure_valid
        or customer_safe_disclosure_valid
    )
    confirmation_valid = (
        disclosure_valid
        and price_difference_disclosed
        and _is_affirmative(last_user_text)
        and _confirmation_references_consistent(
            last_user_text, order_id, old_items, new_items, payment_id
        )
        and last_user_index > last_assistant_text_index
        and reconfirmed_after_block
        and last_user_index < current_message_index
    )

    # Bind the generic reference checks to observed message context rather than
    # encoding the overall policy result into each lower-level evidence field.
    affirmative_confirmation = _is_affirmative(last_user_text)
    confirmation_references_valid = _confirmation_references_consistent(
        last_user_text, order_id, old_items, new_items, payment_id
    )
    assistant_disclosed_order = (
        isinstance(order_id, str) and bool(order_id)
        and _contains_all(last_assistant_text, [order_id])
    )
    assistant_disclosed_old_items = (
        isinstance(old_items, list) and bool(old_items)
        and (
            _contains_all(last_assistant_text, old_items)
            or semantic_disclosure_valid
        )
    )
    assistant_disclosed_new_items = (
        isinstance(new_items, list) and bool(new_items)
        and (
            _contains_all(last_assistant_text, new_items)
            or semantic_disclosure_valid
        )
    )
    assistant_disclosed_payment = (
        isinstance(payment_id, str) and bool(payment_id)
        and (
            _contains_all(last_assistant_text, [payment_id])
            or payment_display_disclosed
        )
    )
    evidence = {
        "identity_verified": identity_valid,
        "verified_user_id": identity_id,
        "order_owner_id": owner_id,
        "order_id": order_id if order_is_object else None,
        "order_status": order_status,
        "confirmation": {
            "confirmed": affirmative_confirmation,
            "order_id": order_id,
            "old_item_ids": old_items,
            "new_item_ids": new_items,
            "payment_method_id": payment_id,
            "confirmation_id": (
                f"tau2-turn-{last_user_index + 1}"
                if affirmative_confirmation and last_user_index >= 0
                else ""
            ),
        },
        "customer_facing_confirmation": {
            "order_id": order_id if assistant_disclosed_order else None,
            "old_item_ids": old_items if assistant_disclosed_old_items else [],
            "new_item_ids": new_items if assistant_disclosed_new_items else [],
            "payment_method_id": payment_id if assistant_disclosed_payment else None,
            "payment_method_disclosed": assistant_disclosed_payment,
        },
        "confirmation_event_sequence": (
            last_user_index + 1
            if affirmative_confirmation and last_user_index >= 0
            else None
        ),
        "proposed_write_sequence": current_message_index + 1,
    }
    result = evaluate_prewrite(
        action,
        evidence,
        expected_order_status=expected_order_status,
        # Supply item IDs from the matching order snapshot; the generic evaluator
        # independently checks multiplicity, and this adapter rechecks it below.
        order_item_ids=order_item_ids if order_snapshot_matches_request else None,
    )
    # The generic reference evaluator uses a broad failure label. Translate it to
    # a truthful reason for the Tau2 adapter, where confirmation fields are context-bound.
    if "explicit_confirmation_does_not_match_action" in result.get("blocking_checks", []):
        blocking = [
            item for item in result["blocking_checks"]
            if item != "explicit_confirmation_does_not_match_action"
        ]
        specific_failure = (
            "explicit_customer_confirmation_missing"
            if not affirmative_confirmation
            else "confirmation_action_binding_invalid"
        )
        blocking.append(specific_failure)
        result["blocking_checks"] = list(dict.fromkeys(blocking))
    order_snapshot_fresh = _order_snapshot_is_fresh(messages, order_id)
    extra_checks = {
        "order_snapshot_matches_requested_order": order_snapshot_matches_request,
        "order_status_matches_required_state": order_status == expected_order_status,
        "old_item_multiplicity_does_not_exceed_order_quantity": old_items_belong_to_order,
        "new_items_are_verified_available_variants": new_items_verified_available,
        "new_items_match_the_corresponding_old_product_types": new_items_match_old_product_types,
        "assistant_variant_claims_match_catalog": _assistant_variant_claims_match_catalog(
            prior_messages, new_items, variants
        ),
        "payment_method_belongs_to_order": payment_method_belongs_to_order,
        "complete_customer_facing_exchange_disclosure": disclosure_valid,
        "user_confirmation_references_match_requested_action": confirmation_references_valid,
        "user_reconfirmed_after_latest_blocked_attempt": reconfirmed_after_block,
        "exact_price_difference_and_direction_disclosed": price_difference_disclosed,
        "customer_disclosed_item_pairs_match_requested_exchange": pairing_disclosed,
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
        "assistant_variant_claims_match_catalog": _assistant_variant_claims_match_catalog(
            prior_messages, new_items, variants
        ),
        "payment_method_belongs_to_order": payment_method_belongs_to_order,
        "price_difference": price_difference,
        "exact_price_difference_and_direction_disclosed": price_difference_disclosed,
        "order_snapshot_fresh": order_snapshot_fresh,
        "assistant_disclosed_exact_order_items_and_payment": disclosure_valid,
        "user_affirmed_after_disclosure": confirmation_valid,
        "user_reconfirmed_after_latest_blocked_attempt": reconfirmed_after_block,
    }
    return result
