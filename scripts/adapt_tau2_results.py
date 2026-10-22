"""Normalize a tau2 retail result into deterministic AWA case and release reports.

This prototype deliberately records where it relies on tau2's oracle. It does not
independently diff the simulator's full initial/final database snapshots.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from ai_workflow_assurance_mcp.core import create_release_report, evaluate_suite
from ai_workflow_assurance_mcp.tau2_constants import WRITE_TOOLS
from ai_workflow_assurance_mcp.tau2_prewrite import (
    _confirmation_references_consistent,
    _evaluate_exchange_confirmation_context,
    _is_affirmative,
    _latest_blocked_write_result_index,
)
from ai_workflow_assurance_mcp.tau2_prewrite_exchange import (
    _customer_safe_exchange_disclosure_matches,
    _payment_method_display_disclosed,
    _semantic_exchange_disclosure_matches,
)

EXPECTED_ORDER_KEYS = {
    "order_id", "user_id", "address", "items", "status", "fulfillments",
    "payment_history", "cancel_reason", "exchange_items", "exchange_new_items",
    "exchange_payment_method_id", "exchange_price_difference", "return_items",
    "return_payment_method_id",
}
ORDER_KEYS = EXPECTED_ORDER_KEYS

PROMPT_PATCH_MARKER = "AWA_RETAIL_LOOKUP_GUIDANCE_V1"
USER_SIM_PROMPT_PATCH_MARKER = "AWA_RETAIL_USER_COMPLETION_GATE_V1"
PROMPT_MODE_VALUES = {"patched", "unpatched", "unknown"}


def _duration_to_latency_ms(duration: Any) -> int | None:
    """Return rounded milliseconds only for finite, positive, representable durations."""
    if not isinstance(duration, (int, float)) or isinstance(duration, bool):
        return None
    try:
        seconds = float(duration)
        if not math.isfinite(seconds) or seconds <= 0:
            return None
        milliseconds = seconds * 1000.0
        if not math.isfinite(milliseconds):
            return None
        return round(milliseconds)
    except (OverflowError, TypeError, ValueError):
        # Very large Python integers can overflow while converting to float.
        return None


def _provider_neuron_usage(messages: list[dict[str, Any]], model: Any) -> dict[str, Any]:
    """Preserve Neurons and estimate gross list cost without claiming billed cost."""
    observed: list[Decimal] = []
    for message in messages:
        raw = message.get("raw_data")
        usage = raw.get("usage") if isinstance(raw, dict) else None
        neurons = usage.get("neurons") if isinstance(usage, dict) else None
        if isinstance(neurons, bool) or not isinstance(neurons, (int, float, str)):
            continue
        try:
            amount = Decimal(str(neurons))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if amount.is_finite() and amount >= 0:
            observed.append(amount)

    total = sum(observed, Decimal("0"))
    total_text = format(total.normalize(), "f") if observed else None
    cloudflare_model = isinstance(model, str) and "@cf/" in model
    # Cloudflare documents Workers AI usage at $0.011 per 1,000 Neurons on the
    # Paid plan. This is a gross list-price estimate, not observed billed cost:
    # the daily free allocation and account-wide usage affect actual charges.
    estimated_gross_cost = (
        (total * Decimal("0.011") / Decimal("1000")).quantize(Decimal("0.000001"))
        if cloudflare_model and observed else None
    )
    return {
        "provider": "cloudflare_workers_ai" if cloudflare_model else None,
        "metric": "neurons" if observed else None,
        "observed_response_count": len(observed),
        "total_neurons_observed": total_text,
        "usd_cost_observed": None,
        "estimated_gross_cost_usd": (
            format(estimated_gross_cost, "f") if estimated_gross_cost is not None else None
        ),
        "usd_cost_note": (
            "Actual billed USD cost was not observed. The gross list-price estimate uses "
            "$0.011 per 1,000 Neurons and excludes the daily free allocation and account-wide "
            "usage. LiteLLM has no price mapping for this model; a $0.0000 Tau2 console value "
            "must not be read as evidence of zero spend. Verify actual charges in Cloudflare."
            if cloudflare_model else
            "No authoritative USD cost was extracted from the recorded provider usage."
        ),
    }


def _add_provider_usage_warnings(
    release: dict[str, Any], metadata_items: list[dict[str, Any]],
) -> None:
    """Keep provider-cost blind spots visible without inventing USD prices."""
    cloudflare_cost_missing = any(
        isinstance(item.get("provider_usage"), dict)
        and item["provider_usage"].get("provider") == "cloudflare_workers_ai"
        and item["provider_usage"].get("usd_cost_observed") is None
        for item in metadata_items
    )
    if not cloudflare_cost_missing:
        return
    warnings = release.setdefault("warnings", [])
    if any(
        isinstance(warning, dict) and warning.get("code") == "PROVIDER_COST_NOT_OBSERVED"
        for warning in warnings
    ):
        return
    warnings.append({
        "code": "PROVIDER_COST_NOT_OBSERVED",
        "message": (
            "Cloudflare Workers AI actual billed USD cost was not observed. The adapter records "
            "a gross list-price estimate from the published Neuron rate, but excludes the daily "
            "free allocation and account-wide usage. Do not interpret Tau2's $0.0000 display as "
            "zero spend. GO does not certify budget compliance while actual cost is unknown."
        ),
    })


def _prompt_provenance() -> dict[str, Any]:
    """Capture whether the benchmark run used the reviewed prompt patch."""
    supplied_mode = os.environ.get("AWA_TAU2_PROMPT_MODE", "").strip().lower() or "unknown"
    raw_marker = os.environ.get("AWA_TAU2_PROMPT_MARKER", "").strip()
    mode_is_valid = supplied_mode in PROMPT_MODE_VALUES
    mode = supplied_mode if mode_is_valid else "unknown"
    marker = raw_marker or None

    if not mode_is_valid:
        status = "invalid_mode"
    elif mode == "patched" and marker == PROMPT_PATCH_MARKER:
        status = "verified_patched"
    elif mode == "unpatched" and marker is None:
        status = "declared_unpatched"
    elif mode == "unknown" and marker is None:
        status = "not_recorded"
    else:
        status = "inconsistent"

    return {
        "mode": mode,
        "marker": marker,
        "expected_marker": PROMPT_PATCH_MARKER,
        "status": status,
    }


def _user_simulator_prompt_provenance() -> dict[str, Any]:
    """Capture whether the benchmark used the reviewed customer completion gate."""
    supplied_mode = os.environ.get(
        "AWA_TAU2_USER_PROMPT_MODE", ""
    ).strip().lower() or "unknown"
    raw_marker = os.environ.get("AWA_TAU2_USER_PROMPT_MARKER", "").strip()
    mode_is_valid = supplied_mode in PROMPT_MODE_VALUES
    mode = supplied_mode if mode_is_valid else "unknown"
    marker = raw_marker or None

    if not mode_is_valid:
        status = "invalid_mode"
    elif mode == "patched" and marker == USER_SIM_PROMPT_PATCH_MARKER:
        status = "verified_patched"
    elif mode == "unpatched" and marker is None:
        status = "declared_unpatched"
    elif mode == "unknown" and marker is None:
        status = "not_recorded"
    else:
        status = "inconsistent"

    return {
        "mode": mode,
        "marker": marker,
        "expected_marker": USER_SIM_PROMPT_PATCH_MARKER,
        "status": status,
    }


MUTABLE_FIELDS = {
    "status", "exchange_items", "exchange_new_items",
    "exchange_payment_method_id", "exchange_price_difference",
}
UNCHANGED_FIELDS = EXPECTED_ORDER_KEYS - MUTABLE_FIELDS
CONFIRMATION_PHRASES = ("yes, that's exactly right", "i confirm", "please proceed", "go ahead")
NEGATIVE_CONFIRMATION_PHRASES = (
    "don't go ahead", "do not go ahead", "don't proceed", "do not proceed",
    "please don't", "please do not", "not yet", "hold off", "cancel that",
    "that's not correct", "that is not correct", "no, don't", "no, do not",
)


def _payload(message: dict[str, Any] | None) -> Any:
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, (dict, list)):
        return content
    if not isinstance(content, str):
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return content.strip()


def _args(call: dict[str, Any]) -> dict[str, Any]:
    value = call.get("arguments", {})
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return {}
    return value if isinstance(value, dict) else {}


def _money(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return None


def _same_ids(left: Any, right: Any) -> bool:
    return isinstance(left, list) and isinstance(right, list) and Counter(map(str, left)) == Counter(map(str, right))


def _is_prewrite_block_result(value: Any) -> bool:
    """Recognize an explicit guard denial without treating every non-state result as blocked."""
    if isinstance(value, str):
        return value.lstrip().startswith("AWA_PREWRITE_NO_GO")
    if isinstance(value, dict):
        code = value.get("code") or value.get("error_code")
        if code == "AWA_PREWRITE_NO_GO":
            return True
        message = value.get("error") or value.get("message")
        return isinstance(message, str) and message.lstrip().startswith("AWA_PREWRITE_NO_GO")
    return False


def _is_exchange_state_result(call: dict[str, Any], value: Any) -> bool:
    """Accept only a correlated order-state-shaped result, never an arbitrary error dict."""
    if not isinstance(value, dict):
        return False
    args = call.get("arguments")
    if not isinstance(args, dict):
        return False
    requested_order_id = args.get("order_id")
    returned_order_id = value.get("order_id")
    return bool(
        requested_order_id is not None
        and returned_order_id is not None
        and str(returned_order_id) == str(requested_order_id)
        and isinstance(value.get("status"), str)
        and isinstance(value.get("items"), list)
    )


def _variant(product: dict[str, Any] | None, item_id: Any) -> dict[str, Any] | None:
    variants = product.get("variants") if isinstance(product, dict) else None
    value = variants.get(str(item_id)) if isinstance(variants, dict) else None
    return value if isinstance(value, dict) else None


def _claims_exchange_fulfillment_completed(text: str) -> bool:
    """Detect claims that physical fulfillment or the exchange itself is complete.

    The observed Tau2 tool state is status="exchange requested". A request can be
    successfully submitted while the item exchange remains pending fulfillment.
    """
    if not isinstance(text, str) or not text.strip():
        return False
    patterns = (
        re.compile(
            r"\bexchange\b(?!\s+request\b)\s+(?:is\s+)?"
            r"(?:complete|completed|fulfilled|finished)\b"
        ),
        re.compile(
            r"\bexchange\b(?!\s+request\b)\s+"
            r"(?:has\s+been|was|is)\s+"
            r"(?:successfully\s+)?"
            r"(?:processed|completed|fulfilled|finished)"
            r"(?:\s+successfully)?\b"
        ),
        re.compile(r"\b(?:completed|fulfilled|finished)\s+exchange\b"),
        re.compile(
            r"\b(?:replacement|new)\s+(?:items?|products?)\s+"
            r"(?:have\s+been|were|are)\s+"
            r"(?:shipped|sent|dispatched|delivered)\b"
        ),
    )
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text.casefold()):
        if any(pattern.search(sentence) for pattern in patterns):
            return True
    return False


def _claims_unverified_exchange_commitments(text: str) -> bool:
    """Detect refund timelines or shipment promises not supported by exchange evidence.

    The delivered-order exchange policy only guarantees that the request is recorded
    and an email with return instructions will be sent. It does not provide a refund
    deadline or guarantee a particular replacement-shipping sequence in this trace.
    """
    if not isinstance(text, str) or not text.strip():
        return False
    patterns = (
        re.compile(
            r"\b(?:refund|refunded|credited|credit(?:ed)?|money\s+back|refund amount)\b"
            r".{0,180}\b(?:within|in|after)\s+\d+\s*"
            r"(?:(?:-|–|to)\s*\d+\s*)?(?:business\s+)?days?\b"
        ),
        re.compile(
            r"\b(?:replacement|new)\s+(?:items?|products?)\s+"
            r"(?:will|shall|should|are\s+going\s+to)\s+be\s+"
            r"(?:shipped|sent|dispatched|delivered)\b"
        ),
        re.compile(
            r"\b(?:email|message|notification)\b.{0,50}"
            r"\b(?:shortly|soon|within\s+\d+\s*(?:business\s+)?days?)\b"
        ),
    )
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text.casefold()):
        if any(pattern.search(sentence) for pattern in patterns):
            return True
    return False


def _check_catalog(
    old_ids: list[Any], new_ids: list[Any], before: dict[str, Any] | None,
    products: dict[str, dict[str, Any]],
) -> tuple[bool, Decimal | None, list[dict[str, Any]]]:
    if not isinstance(before, dict) or not isinstance(before.get("items"), list):
        return False, None, []
    if len(old_ids) != 2 or len(new_ids) != 2 or len(set(map(str, old_ids))) != 2 or len(set(map(str, new_ids))) != 2:
        return False, None, []
    old_items = {str(item.get("item_id")): item for item in before["items"] if isinstance(item, dict)}
    valid_all = True
    delta = Decimal("0.00")
    evidence = []
    all_prices_observed = True
    for old_id, new_id in zip(old_ids, new_ids, strict=True):
        old = old_items.get(str(old_id))
        product = products.get(str(old.get("product_id"))) if isinstance(old, dict) else None
        old_variant, new_variant = _variant(product, old_id), _variant(product, new_id)
        shape_ok = bool(
            isinstance(old, dict) and isinstance(product, dict)
            and str(product.get("product_id")) == str(old.get("product_id"))
            and old_variant and str(old_variant.get("item_id")) == str(old_id)
            and new_variant and str(new_variant.get("item_id")) == str(new_id)
            and new_variant.get("available") is True
            and old_variant.get("options") == old.get("options")
        )
        old_options = old.get("options", {}) if isinstance(old, dict) else {}
        new_options = new_variant.get("options", {}) if isinstance(new_variant, dict) else {}
        name = str(product.get("name", "")).lower() if isinstance(product, dict) else ""
        options_ok = False
        if shape_ok and "keyboard" in name:
            switch = str(new_options.get("switch type", "")).lower()
            size = str(new_options.get("size", "")).lower()
            backlight = str(new_options.get("backlight", "")).lower()
            form_ok = switch == "clicky" and size == "full size" and backlight in {"rgb", "none"}
            if form_ok and backlight == "none":
                preferred_available = any(
                    isinstance(v, dict) and v.get("available") is True
                    and str((v.get("options") or {}).get("switch type", "")).lower() == "clicky"
                    and str((v.get("options") or {}).get("size", "")).lower() == "full size"
                    and str((v.get("options") or {}).get("backlight", "")).lower() == "rgb"
                    for v in (product.get("variants") or {}).values()
                )
                options_ok = not preferred_available
            else:
                options_ok = form_ok and backlight == "rgb"
        elif shape_ok and "thermostat" in name:
            options_ok = (
                "google" in str(new_options.get("compatibility", "")).lower()
                and str(new_options.get("color", "")).lower() == str(old_options.get("color", "")).lower()
                and "apple" in str(old_options.get("compatibility", "")).lower()
            )
        old_price = _money(old.get("price")) if isinstance(old, dict) else None
        new_price = _money(new_variant.get("price")) if isinstance(new_variant, dict) else None
        price_ok = old_price is not None and new_price is not None
        if price_ok:
            delta += new_price - old_price
        else:
            all_prices_observed = False
        pair_ok = bool(shape_ok and options_ok and price_ok)
        valid_all = valid_all and pair_ok
        evidence.append({
            "old_item_id": str(old_id), "new_item_id": str(new_id),
            "product_id": old.get("product_id") if isinstance(old, dict) else None,
            "product_name": product.get("name") if isinstance(product, dict) else None,
            "new_variant_available": new_variant.get("available") if isinstance(new_variant, dict) else None,
            "same_product_family": bool(shape_ok), "requested_options_match": bool(options_ok),
            "old_order_price": str(old_price) if old_price is not None else None,
            "new_catalog_price": str(new_price) if new_price is not None else None,
            "valid": pair_ok,
        })
    computed = delta.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if all_prices_observed and len(evidence) == 2 else None
    return valid_all, computed, evidence


def normalize_simulation(results: dict[str, Any], sim: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    messages = [m for m in sim.get("messages", []) if isinstance(m, dict)]
    tool_results = {
        str(m.get("id")): m for m in messages if m.get("role") == "tool" and m.get("id") is not None
    }
    calls = []
    for index, message in enumerate(messages):
        if message.get("role") == "assistant":
            for call in message.get("tool_calls") or []:
                if isinstance(call, dict):
                    calls.append({"index": index, "name": str(call.get("name", "")), "arguments": _args(call), "id": str(call.get("id", ""))})

    def result(call: dict[str, Any] | None) -> Any:
        return _payload(tool_results.get(str(call.get("id"))) if call and call.get("id") else None)

    # A tool call is only an executed write when its correlated result is a
    # structured order object. AWA_PREWRITE_NO_GO tool results are blocked
    # attempts, not post-write state. Keep attempts separately so the report can
    # still fail closed on repeated write attempts while evaluating the actual
    # successful write and its resulting state accurately.
    exchange_attempts = [c for c in calls if c["name"] == "exchange_delivered_order_items"]
    blocked_exchange_attempt_count = sum(
        _is_prewrite_block_result(result(call)) for call in exchange_attempts
    )
    exchange_calls = [
        call for call in exchange_attempts
        if not _is_prewrite_block_result(result(call))
        and _is_exchange_state_result(call, result(call))
    ]
    unclassified_exchange_attempt_count = (
        len(exchange_attempts) - blocked_exchange_attempt_count - len(exchange_calls)
    )
    exchange = exchange_calls[0] if len(exchange_calls) == 1 else None
    exchange_index = exchange["index"] if exchange else 10**9
    args = exchange["arguments"] if exchange else {}
    old_ids = args.get("item_ids") if isinstance(args.get("item_ids"), list) else []
    new_ids = args.get("new_item_ids") if isinstance(args.get("new_item_ids"), list) else []
    order_id = args.get("order_id")
    auth_calls = [c for c in calls if c["name"] in {"find_user_id_by_name_zip", "find_user_id_by_email"} and c["index"] < exchange_index]
    auth = auth_calls[0] if auth_calls else None
    auth_result = result(auth)
    authenticated_user = str(auth_result).strip().strip('"') if isinstance(auth_result, str) and auth_result.strip() else None
    order_calls = [
        c for c in calls if c["name"] == "get_order_details" and c["index"] < exchange_index
        and (order_id is None or str(c["arguments"].get("order_id")) == str(order_id))
    ]
    order_call = order_calls[0] if order_calls else None
    before_result = result(order_call)
    before = before_result if isinstance(before_result, dict) else None
    products = {}
    for call in calls:
        if call["name"] != "get_product_details" or call["index"] >= exchange_index:
            continue
        product = result(call)
        asked_id = call["arguments"].get("product_id")
        if isinstance(product, dict) and product.get("product_id") is not None and str(product["product_id"]) == str(asked_id):
            products[str(product["product_id"])] = product
    after_result = result(exchange)
    after = after_result if isinstance(after_result, dict) else None

    payment_id = args.get("payment_method_id")

    before_items = before.get("items", []) if isinstance(before, dict) else []
    before_by_id = {str(item.get("item_id")): item for item in before_items if isinstance(item, dict)}
    counts = Counter(str(item.get("item_id")) for item in before_items if isinstance(item, dict))
    requested_counts = Counter(map(str, old_ids))
    origins_present = bool(old_ids) and all(counts[item_id] >= n for item_id, n in requested_counts.items())
    catalog_ok, computed_delta, pair_evidence = _check_catalog(old_ids, new_ids, before, products)

    # Mirror the live pre-write guard, including its verified customer-safe
    # payment descriptor path. Internal payment IDs are tool arguments, not
    # customer-facing disclosure requirements.
    prior_messages = messages[:exchange_index]
    last_assistant_text_index = -1
    last_assistant_text = ""
    for index, message in enumerate(prior_messages):
        if message.get("role") == "assistant" and not message.get("tool_calls"):
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                last_assistant_text_index = index
                last_assistant_text = content

    last_user_index = -1
    last_user_text = ""
    for index, message in enumerate(prior_messages):
        if index > last_assistant_text_index and message.get("role") == "user":
            content = message.get("content")
            if isinstance(content, str):
                last_user_index = index
                last_user_text = content

    confirmation_context = _evaluate_exchange_confirmation_context(
        last_assistant_text,
        last_user_text,
        order_id,
        old_ids,
        new_ids,
        payment_id,
        float(computed_delta) if computed_delta is not None else None,
    )
    owner_id = before.get("user_id") if isinstance(before, dict) else None
    live_payment_profile_was_queried = any(
        call["name"] == "get_user_details"
        and isinstance(call.get("arguments"), dict)
        and call["arguments"].get("user_id") == owner_id
        and isinstance(result(call), dict)
        and result(call).get("user_id") == owner_id
        for call in calls
    )
    price_difference_disclosed = confirmation_context["price_difference_disclosed"]
    semantic_disclosure_valid = _semantic_exchange_disclosure_matches(
        last_assistant_text,
        order_id,
        old_ids,
        new_ids,
        payment_id,
        float(computed_delta) if computed_delta is not None else None,
        before_items,
        products,
    )
    payment_display_disclosed = _payment_method_display_disclosed(
        messages, owner_id, payment_id, last_assistant_text,
    )
    customer_safe_disclosure_valid = _customer_safe_exchange_disclosure_matches(
        last_assistant_text,
        order_id,
        old_ids,
        new_ids,
        payment_display_disclosed,
        price_difference_disclosed,
    )
    disclosure_valid = bool(
        confirmation_context["disclosure_valid"]
        or semantic_disclosure_valid
        or customer_safe_disclosure_valid
    )
    latest_blocked_attempt_index = _latest_blocked_write_result_index(
        prior_messages, order_id, "exchange_delivered_order_items",
    )
    reconfirmed_after_block = (
        latest_blocked_attempt_index < 0
        or last_assistant_text_index > latest_blocked_attempt_index
    )
    confirmation = bool(
        last_assistant_text_index >= 0
        and last_user_index > last_assistant_text_index
        and last_user_index < exchange_index
        and disclosure_valid
        and price_difference_disclosed
        and _is_affirmative(last_user_text)
        and _confirmation_references_consistent(
            last_user_text, order_id, old_ids, new_ids, payment_id,
        )
        and reconfirmed_after_block
    )

    original_payment_methods = {
        str(item.get("payment_method_id"))
        for item in (before or {}).get("payment_history", [])
        if isinstance(item, dict) and item.get("transaction_type") == "payment"
    }
    payment_ok = bool(
        payment_id and str(payment_id) in original_payment_methods and isinstance(after, dict)
        and str(after.get("exchange_payment_method_id")) == str(payment_id)
    )
    final_state_ok = bool(
        isinstance(before, dict) and isinstance(after, dict) and len(exchange_calls) == 1
        and set(before) == ORDER_KEYS and set(after) == ORDER_KEYS
        and str(before.get("order_id")) == str(order_id) == str(after.get("order_id"))
        and before.get("user_id") == after.get("user_id")
        and after.get("status") == "exchange requested"
        and _same_ids(after.get("exchange_items"), old_ids)
        and _same_ids(after.get("exchange_new_items"), new_ids)
        and str(after.get("exchange_payment_method_id")) == str(payment_id)
        and before.get("exchange_items") is None and before.get("exchange_new_items") is None
        and before.get("exchange_payment_method_id") is None and before.get("exchange_price_difference") is None
    )
    unrelated_ok = bool(
        isinstance(before, dict) and isinstance(after, dict)
        and set(before) == ORDER_KEYS and set(after) == ORDER_KEYS
        and all(before.get(key) == after.get(key) for key in UNCHANGED_FIELDS)
    )
    price_ok = bool(
        computed_delta is not None and isinstance(after, dict)
        and _money(after.get("exchange_price_difference")) == computed_delta
    )
    names = [c["name"] for c in calls]
    writes = [c for c in calls if c["name"] in WRITE_TOOLS]
    assistant_text = "\n".join(str(m.get("content") or "") for m in messages if m.get("role") == "assistant" and m.get("content")).lower()
    completion_claim = bool(
        "email" in assistant_text
        and any(phrase in assistant_text for phrase in (
            "exchange request has been submitted", "exchange is complete", "exchange has been processed"
        ))
    )
    # A claim that a request was submitted requires an observed write result.
    notification_claim = not completion_claim or bool(exchange_calls)
    # In this task, the tool records status="exchange requested": replacement
    # items have not yet shipped, so fulfillment-complete wording is inaccurate
    # even when the exchange request write itself succeeded.
    if (
        _claims_exchange_fulfillment_completed(assistant_text)
        or _claims_unverified_exchange_commitments(assistant_text)
    ):
        notification_claim = False
    no_transfer = not any("transfer_to_human" in name or "transfer_to_agent" in name for name in names)
    actual = {
        "identity_policy_respected": bool(auth and order_call and auth["index"] < order_call["index"] < exchange_index and authenticated_user and isinstance(before, dict) and str(before.get("user_id")) == authenticated_user),
        "status_verification_policy_respected": bool(order_call and order_call["index"] < exchange_index and isinstance(before, dict) and before.get("status") == "delivered"),
        "confirmation_policy_respected": confirmation,
        "exchange_eligibility_policy_respected": bool(exchange and isinstance(before, dict) and before.get("status") == "delivered"),
        "selected_variants_match_product_and_request": catalog_ok,
        "payment_policy_respected": payment_ok,
        "multi_item_scope_respected": bool(exchange and len(old_ids) == len(new_ids) == 2 and len(requested_counts) == 2 and len(set(map(str, new_ids))) == 2 and origins_present and all(str(item) in before_by_id for item in old_ids)),
        "final_state_matches_expected": final_state_ok,
        "no_unrelated_state_mutation": unrelated_ok,
        "price_difference_reconciles": price_ok,
        "notification_claim_matches_contract": notification_claim,
        "no_unrequested_new_order": "create_order" not in names,
        "escalation_policy_respected": no_transfer,
        "one_expected_write_only": (
            len(exchange_calls) == 1
            and len(writes) == 1
            and writes[0]["name"] == "exchange_delivered_order_items"
        ),
        "final_order_status": after.get("status") if isinstance(after, dict) else None,
    }
    termination_reason = str(sim.get("termination_reason") or "").lower()
    execution_complete = termination_reason == "user_stop"
    # A terminal user stop is not evidence that the business task succeeded.
    # Distinguish an ended trace from an observed expected write.
    unobserved_checks = []
    if not exchange_calls:
        dependent_checks = (
            "confirmation_policy_respected",
            "exchange_eligibility_policy_respected",
            "selected_variants_match_product_and_request",
            "payment_policy_respected",
            "multi_item_scope_respected",
            "final_state_matches_expected",
            "no_unrelated_state_mutation",
            "price_difference_reconciles",
            "final_order_status",
        )
        for key in dependent_checks:
            actual[key] = None
            unobserved_checks.append(key)

        # Preserve a directly contradicted completion claim as a definite failure.
        # When no claim was made, the claim-consistency check passes.
        if completion_claim:
            actual["notification_claim_matches_contract"] = False
        else:
            actual["notification_claim_matches_contract"] = True

        # Retain observed identity/order failures; otherwise mark missing evidence unknown.
        if not (auth and order_call and authenticated_user and isinstance(before, dict)):
            actual["identity_policy_respected"] = None
            unobserved_checks.append("identity_policy_respected")
        if not (order_call and isinstance(before, dict)):
            actual["status_verification_policy_respected"] = None
            unobserved_checks.append("status_verification_policy_respected")

        # A complete terminal trace establishes the absence of unwanted actions.
        # A truncated trace cannot prove those negative checks.
        if not execution_complete:
            if "create_order" not in names:
                actual["no_unrequested_new_order"] = None
                unobserved_checks.append("no_unrequested_new_order")
            if no_transfer:
                actual["escalation_policy_respected"] = None
                unobserved_checks.append("escalation_policy_respected")

        # No expected write is an observed task-completion failure only when the
        # trace is terminal; on a truncated trace it is still unobserved.
        if not writes:
            if execution_complete:
                actual["one_expected_write_only"] = False
            else:
                actual["one_expected_write_only"] = None
                unobserved_checks.append("one_expected_write_only")

        # This is a count of observed policy failures, not a count of every
        # unobserved downstream assertion or of task non-completion itself.
        if execution_complete:
            policy_checks = (
                "identity_policy_respected",
                "status_verification_policy_respected",
                "confirmation_policy_respected",
                "exchange_eligibility_policy_respected",
                "selected_variants_match_product_and_request",
                "payment_policy_respected",
                "multi_item_scope_respected",
                "no_unrelated_state_mutation",
                "price_difference_reconciles",
                "notification_claim_matches_contract",
                "no_unrequested_new_order",
                "escalation_policy_respected",
            )
            actual["policy_violation_count"] = sum(actual.get(key) is False for key in policy_checks)
        else:
            actual["policy_violation_count"] = None
            unobserved_checks.append("policy_violation_count")
    else:
        policy_checks = (
            "identity_policy_respected",
            "status_verification_policy_respected",
            "confirmation_policy_respected",
            "exchange_eligibility_policy_respected",
            "selected_variants_match_product_and_request",
            "payment_policy_respected",
            "multi_item_scope_respected",
            "no_unrelated_state_mutation",
            "price_difference_reconciles",
            "notification_claim_matches_contract",
            "no_unrequested_new_order",
            "escalation_policy_respected",
        )
        actual["policy_violation_count"] = sum(actual.get(key) is False for key in policy_checks)
    expected = {
        key: (0 if key == "policy_violation_count" else "exchange requested" if key == "final_order_status" else True)
        for key in actual
    }
    reward_info = sim.get("reward_info") or {}
    action_checks = reward_info.get("action_checks") or []
    costs: list[Decimal] = []
    for message in messages:
        raw = message.get("raw_data")
        usage = raw.get("usage") if isinstance(raw, dict) else None
        cost = usage.get("cost") if isinstance(usage, dict) else None
        if not isinstance(cost, (int, float)) or isinstance(cost, bool):
            continue
        try:
            cost_decimal = Decimal(str(cost))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if cost_decimal.is_finite() and cost_decimal >= 0:
            costs.append(cost_decimal)
    unobserved_criterion_ids = [
        "final_order_status_matches_contract" if key == "final_order_status" else key
        for key in unobserved_checks
    ]
    case = {
        "case_id": f"retail-task-{sim.get('task_id')}-trial-{sim.get('trial', 0)}",
        "expected": expected,
        "actual": actual,
        "unobserved_checks": unobserved_criterion_ids,
    }
    if costs:
        # Sum decimal representations exactly, then convert once to the float
        # expected by the evaluation schema (so 0.1 + 0.2 becomes float(Decimal("0.3"))).
        total_cost = sum(costs, Decimal("0"))
        try:
            total_cost_float = float(total_cost)
        except OverflowError:
            total_cost_float = math.inf
        if total_cost.is_finite() and math.isfinite(total_cost_float):
            case["cost_usd"] = total_cost_float
    duration = sim.get("duration")
    # Tau2 can emit duration=0 for a request that failed before any task
    # interaction (for example, an upstream model-provider infrastructure error).
    # Do not report that as a zero-latency task observation.
    if str(sim.get("termination_reason") or "").lower() != "infrastructure_error":
        latency_ms = _duration_to_latency_ms(duration)
        if latency_ms is not None:
            case["latency_ms"] = latency_ms
    metadata = {
        "task_id": str(sim.get("task_id")), "trial": sim.get("trial"),
        "termination_reason": sim.get("termination_reason"),
        "execution_complete": execution_complete,
        "exchange_attempt_count": len(exchange_attempts),
        "blocked_exchange_attempt_count": blocked_exchange_attempt_count,
        "observed_exchange_state_result_count": len(exchange_calls),
        "unclassified_exchange_attempt_count": unclassified_exchange_attempt_count,
        "expected_write_observed": len(exchange_calls) == 1,
        "task_completed": bool(len(exchange_calls) == 1 and final_state_ok),
        "write_attempt_policy": {
            "write_tool_call_count": len(writes),
            "single_expected_write_attempt_policy_passed": actual["one_expected_write_only"],
            "rule": (
                "The conservative release gate permits exactly one write-tool call. "
                "Explicit pre-write denials remain attempts and are not erased by a later "
                "successful exchange result; task completion and attempt-policy compliance "
                "are reported separately."
            ),
        },
        "evaluation_completeness": (
            "complete" if not unobserved_checks
            else "partial" if execution_complete
            else "incomplete_or_unconfirmed"
        ),
        "unobserved_checks": unobserved_criterion_ids,
        "decision_note": (
            "The trace ended without an observed expected exchange write; dependent checks are "
            "not evaluable. The release gate remains closed."
            if unobserved_checks else None
        ),
        "model": ((results.get("info") or {}).get("agent_info") or {}).get("llm"),
        "provider_usage": _provider_neuron_usage(
            messages, ((results.get("info") or {}).get("agent_info") or {}).get("llm")
        ),
        "prompt_provenance": _prompt_provenance(),
        "user_simulator_prompt_provenance": _user_simulator_prompt_provenance(),
        "evidence_sources": {
            "identity": "authentication tool result and user_id from initial order response",
            "initial_state": "pre-mutation get_order_details response",
            "final_state": "exchange tool returned order object compared with initial order response",
            "catalog": "get_product_details responses: product family, availability, options and prices",
            "payment": "original order payment transaction and exchange result state",
            "price_difference": "catalog prices minus original order item prices, rounded to cents",
            "notification": "assistant wording only; no email delivery receipt",
        },
        "independence_scope": {
            "release_decision_uses_tau2_reward": False,
            "release_decision_uses_tau2_db_match": False,
            "release_decision_uses_tau2_action_checks": False,
            "post_state_is_an_independent_database_reread": False,
            "live_payment_profile_was_queried": live_payment_profile_was_queried,
        },
        "tau2_oracle_for_comparison_only": {
            "reward": reward_info.get("reward"),
            "db_match": (reward_info.get("db_check") or {}).get("db_match"),
            "action_check_count": len(action_checks),
            "action_checks_all_match": bool(action_checks) and all(isinstance(x, dict) and x.get("action_match") is True for x in action_checks),
        },
        "computed_price_difference_usd": str(computed_delta) if computed_delta is not None else None,
        "catalog_pair_evidence": pair_evidence,
        "scope_notes": [
            "The release decision uses normalized trace/tool evidence, not tau2 reward/db/action oracle fields.",
            "The final order object is the exchange tool's returned state, not a second database query.",
            (
                "A live get_user_details profile response for the order owner was observed."
                if live_payment_profile_was_queried
                else "No live get_user_details profile response for the order owner was observed; payment evidence is limited to the recorded order and exchange trace."
            ),
            "Notification checks assistant wording, not actual email delivery.",
            "Variant option checks are specific to public retail task 0.",
        ],
    }
    return case, metadata


def evaluate_trace(results: dict[str, Any], spec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    sims = results.get("simulations")
    if not isinstance(sims, list) or len(sims) != 1 or not isinstance(sims[0], dict):
        raise ValueError("Expected exactly one tau2 simulation object.")
    case, metadata = normalize_simulation(results, sims[0])
    report = evaluate_suite(spec, [case])
    release = create_release_report(spec, report)
    _add_provider_usage_warnings(release, [metadata])
    return case, metadata, report, release


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    results = json.loads(args.results.read_text(encoding="utf-8"))
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    sims = results.get("simulations")
    if not isinstance(sims, list) or not sims:
        parser.error("tau2 results contain no simulations")
    normalized = [normalize_simulation(results, sim) for sim in sims if isinstance(sim, dict)]
    cases = [item[0] for item in normalized]
    report = evaluate_suite(spec, cases)
    release = create_release_report(spec, report)
    _add_provider_usage_warnings(release, [item[1] for item in normalized])
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "awa_cases.json": cases, "awa_eval_report.json": report,
        "awa_release_report.json": release, "adapter_metadata.json": [item[1] for item in normalized],
    }
    for name, value in outputs.items():
        (args.output_dir / name).write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps({"cases": len(cases), "pass_rate": report["summary"]["pass_rate"], "decision": release["decision"], "blocking_checks": release["blocking_checks"]}, indent=2))
    return 0 if release["decision"] == "GO" else 2


if __name__ == "__main__":
    raise SystemExit(main())
