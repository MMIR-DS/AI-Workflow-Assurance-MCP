"""Shared trace-parsing and disclosure helpers for Tau2 pre-write policies."""

from __future__ import annotations

import json
import re
from typing import Any

from ai_workflow_assurance_mcp.tau2_constants import WRITE_TOOLS as _WRITE_TOOLS


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


def _normalize_disclosure_text(text: str) -> str:
    """Normalize harmless typography and numeric grouping while preserving identifiers."""
    normalized = text.casefold().translate(str.maketrans({
        "\u2010": "-",  # hyphen
        "\u2011": "-",  # non-breaking hyphen
        "\u2012": "-",  # figure dash
        "\u2013": "-",  # en dash
        "\u2014": "-",  # em dash
        "\u2212": "-",  # minus sign
    }))
    normalized = re.sub(r"(?<=\d),(?=\d)", "", normalized)
    normalized = re.sub(r"(?:→|⇒|⟶|➜|->|=>)", " for ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _contains_all(text: str, values: list[str]) -> bool:
    """Require complete identifier tokens while retaining phrase matching for prose values."""
    normalized_text = _normalize_disclosure_text(text)
    for value in values:
        normalized_value = _normalize_disclosure_text(value)
        if not normalized_value:
            return False

        # IDs, codes, and short single-token values must not match a longer token.
        if re.fullmatch(r"#?[a-z0-9][a-z0-9_-]*", normalized_value):
            pattern = re.compile(
                r"(?<![a-z0-9_-])" + re.escape(normalized_value) + r"(?![a-z0-9_-])"
            )
            if not pattern.search(normalized_text):
                return False
        elif normalized_value not in normalized_text:
            return False
    return True


def _mentioned_order_ids(text: str) -> list[str]:
    """Extract explicit order references, including common 'order number/ID' wording."""
    folded = text.casefold()
    order_pattern = r"([a-z][a-z0-9_-]*\d[a-z0-9_-]*)"
    explicit = re.findall(
        r"\border(?:\s+(?:number|no\.?|id))?\s*[:#-]?\s*" + order_pattern + r"\b",
        folded,
    )
    hash_references = re.findall(r"#" + order_pattern + r"\b", folded)
    return [*explicit, *hash_references]


def _exchange_pairing_disclosed(text: str, old_items: Any, new_items: Any) -> bool:
    """Require explicit, ordered old→new pairs without mistaking price digits for item IDs."""
    if (
        not isinstance(old_items, list)
        or not isinstance(new_items, list)
        or not old_items
        or len(old_items) != len(new_items)
        or not all(isinstance(item, str) and item for item in [*old_items, *new_items])
    ):
        return False

    normalized_text = _normalize_disclosure_text(text)
    id_pattern = re.compile(r"(?<![A-Za-z0-9_])\d{8,}(?![A-Za-z0-9_])")
    id_matches = list(id_pattern.finditer(normalized_text))
    mentioned_ids = [match.group(0) for match in id_matches]
    expected_sequence = [
        item
        for pair in zip(old_items, new_items, strict=True)
        for item in pair
    ]

    # Require precisely the intended item IDs, in the stated old/new order.
    # Currency amounts may contain digits, but are not 8+ digit item identifiers.
    if mentioned_ids != expected_sequence:
        return False

    for pair_index, (old_item, new_item) in enumerate(
        zip(old_items, new_items, strict=True)
    ):
        old_match = id_matches[pair_index * 2]
        new_match = id_matches[pair_index * 2 + 1]
        if old_match.group(0) != old_item or new_match.group(0) != new_item:
            return False

        preceding_text = normalized_text[
            max(0, old_match.start() - 50):old_match.start()
        ]
        gap = normalized_text[old_match.end():new_match.start()]
        connector_present = bool(
            re.search(r"\b(?:for|to|with)\b|(?:->|→|⇒|=+>)", gap, re.IGNORECASE)
        )
        labeled_pair_present = (
            bool(
                re.search(
                    r"\b(?:old|original|current)\s+item\b",
                    preceding_text,
                    re.IGNORECASE,
                )
            )
            and bool(
                re.search(r"\b(?:new|replacement)\s+item\b", gap, re.IGNORECASE)
            )
        )
        if not connector_present and not labeled_pair_present:
            return False

    return True


def _order_snapshot_is_fresh(messages: list[Any], order_id: Any) -> bool:
    """Require the latest matching order read to return that exact order, with no later write."""
    if not isinstance(order_id, str) or not order_id:
        return False
    write_tools = _WRITE_TOOLS
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
                    "options": variant.get("options"),
                }
    return details


_VARIANT_OPTION_CLAIMS: dict[str, dict[str, tuple[str, ...]]] = {
    "switch type": {
        "linear": ("linear",),
        "tactile": ("tactile",),
        "clicky": ("clicky",),
    },
    "backlight": {
        "rgb": ("rgb", "rgb backlight"),
        "white": ("white", "white backlight"),
        "none": ("no backlight", "without backlight", "backlight none"),
    },
    "size": {
        "full size": ("full size", "full-size"),
        "80%": ("80%",),
        "60%": ("60%",),
    },
    "compatibility": {
        "google assistant": ("google assistant", "google home"),
        "amazon alexa": ("amazon alexa", "alexa"),
        "apple homekit": ("apple homekit", "homekit"),
    },
    "color": {
        "black": ("black",),
        "white": ("white",),
        "blue": ("blue",),
        "gold": ("gold",),
        "stainless steel": ("stainless steel",),
    },
}


def _alias_is_asserted(text: str, alias: str) -> bool:
    """Return whether an option phrase is asserted, ignoring simple explicit negation."""
    escaped = re.escape(alias).replace(r"\ ", r"\s+")
    pattern = re.compile(r"(?<![a-z0-9])" + escaped + r"(?![a-z0-9])")
    for match in pattern.finditer(text):
        preceding = text[max(0, match.start() - 28):match.start()]
        if re.search(
            r"\b(?:not|no|never|isn't|is not|without|unavailable)\s+(?:(?:a|an|the)\s+)?$",
            preceding,
        ):
            continue
        return True
    return False


def _assistant_variant_claims_match_catalog(
    messages: list[Any],
    new_items: Any,
    variants: dict[str, dict[str, Any]],
) -> bool:
    """Reject explicit assistant claims about a selected variant that contradict catalog data.

    This is a contradiction check, not a natural-language preference solver: it fails
    only when a message that names the selected item ID also asserts a different catalog
    value for a recognized option. Unknown option fields and omitted option claims are
    not inferred or guessed.
    """
    if (
        not isinstance(new_items, list)
        or not new_items
        or not all(isinstance(item_id, str) and item_id for item_id in new_items)
    ):
        return False

    for item_id in new_items:
        variant = variants.get(item_id)
        options = variant.get("options") if isinstance(variant, dict) else None
        if not isinstance(options, dict):
            return False

        for message in messages:
            if _get(message, "role") != "assistant" or _tool_calls(message):
                continue
            content = _get(message, "content")
            if not isinstance(content, str) or item_id not in content:
                continue

            normalized_content = _normalize_disclosure_text(content)
            # Work sentence-by-sentence, and focus on the text after the chosen ID.
            # This avoids attributing the old item's options to the new item in a
            # disclosure such as "old RGB item A for white-backlight item B".
            sentences = re.split(r"(?<=[.!?])\s+|\n+", normalized_content)
            for sentence in sentences:
                id_position = sentence.find(item_id)
                if id_position < 0:
                    continue
                claim_text = sentence[id_position + len(item_id):]
                next_item_ref = re.search(
                    r"(?<![A-Za-z0-9_])\d{8,}(?![A-Za-z0-9_])",
                    claim_text,
                )
                if next_item_ref:
                    claim_text = claim_text[:next_item_ref.start()]

                for option_key, actual_value in options.items():
                    if not isinstance(option_key, str) or not isinstance(actual_value, str):
                        continue
                    value_aliases = _VARIANT_OPTION_CLAIMS.get(option_key.casefold())
                    if not value_aliases:
                        continue
                    actual_canonical = next(
                        (
                            canonical
                            for canonical, aliases in value_aliases.items()
                            if actual_value.casefold() == canonical
                            or actual_value.casefold() in aliases
                        ),
                        None,
                    )
                    if actual_canonical is None:
                        continue
                    claimed_values = {
                        canonical
                        for canonical, aliases in value_aliases.items()
                        if any(_alias_is_asserted(claim_text, alias) for alias in aliases)
                    }
                    if claimed_values and claimed_values != {actual_canonical}:
                        return False

    return True


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
    """Require an explicitly labeled amount with a direction consistent with that amount."""
    # Share typography and thousands-separator handling with the other disclosure checks.
    normalized = _normalize_disclosure_text(text)
    folded = normalized
    if not any(term in folded for term in ("price difference", "price delta")):
        return False
    if price_difference is None:
        return False

    amount = f"{abs(price_difference):.2f}"
    amount_pattern = rf"(?<![\d.]){re.escape(amount)}(?![\d.])"
    matches = list(re.finditer(amount_pattern, normalized))
    if not matches:
        return False

    for match in matches:
        # Direction must appear near the amount; a payment instrument named "credit_card"
        # is not evidence that the customer was told a negative delta is a refund.
        window = folded[max(0, match.start() - 100):min(len(folded), match.end() + 100)]
        if price_difference < 0:
            refund = re.search(
                r"\brefund(?:ed|s|ing)?\b|\bmoney back\b|\breturn(?:ed)? to\b",
                window,
            )
            charge = re.search(
                r"\bcharg(?:e|ed|es|ing)\b|\bpay(?:ment)?\s+(?:an?\s+)?additional\b|"
                r"\badditional\s+payment\b",
                window,
            )
            if refund and not charge:
                return True
        elif price_difference > 0:
            charge = re.search(
                r"\bcharg(?:e|ed|es|ing)\b|\bpay(?:ing)?\s+(?:an?\s+)?additional\b|"
                r"\badditional\s+payment\b",
                window,
            )
            refund = re.search(
                r"\brefund(?:ed|s|ing)?\b|\bmoney back\b|\breturn(?:ed)? to\b",
                window,
            )
            no_charge = re.search(
                r"\b(?:no|without|not)\s+(?:an?\s+)?(?:additional\s+)?charge\b",
                window,
            )
            # Reject disclosures that state both directions; the customer must not
            # be asked to confirm an internally contradictory amount statement.
            if charge and not no_charge and not refund:
                return True
        elif "no price difference" in window or "no additional charge" in window:
            return True
    return False

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
    payment_refs = re.findall(
        r"\b(?:credit_card|gift_card|paypal|payment_method)[_-][a-z0-9_-]+\b",
        folded,
    )
    if any(reference != expected_payment_id.casefold() for reference in payment_refs):
        return False

    # Catch common explicit aliases such as "order number W..." and "order ID: W...".
    order_refs = _mentioned_order_ids(folded)
    expected_order_reference = expected_order_id.casefold().lstrip("#")
    if any(reference != expected_order_reference for reference in order_refs):
        return False

    expected_items = {str(item) for item in [*expected_old_items, *expected_new_items]}
    mentioned_numeric_ids = re.findall(r"\b\d{8,}\b", folded)
    if any(reference not in expected_items for reference in mentioned_numeric_ids):
        return False
    return True


def _is_affirmative(text: str, *, action: str = "exchange") -> bool:
    """Accept explicit, unhedged confirmation; ambiguous replies fail closed."""
    if not isinstance(text, str):
        return False

    raw_text = text.strip().casefold()
    if not raw_text or "?" in raw_text or "？" in raw_text:
        return False

    normalized = re.sub(r"[^a-z0-9' ]+", " ", raw_text)
    normalized = " ".join(normalized.split())

    # Reject question syntax anywhere, including an indirect question following a
    # superficially positive opener ("Yes, can you confirm ...").
    if re.search(r"\b(?:can|could|would|should|do|does|did|is|are|am|was|were|have|has|had|may|will)\s+(?:you|i|we|they|he|she|it|that|this|there|anything|something|the)\b", normalized):
        return False
    if re.match(
        r"^(?:what|why|when|where|who|whom|which|how)\b",
        normalized,
    ):
        return False

    if action == "cancel":
        # "No longer needed" is a cancellation reason, not a negation of consent.
        normalized = re.sub(r"\bno longer needed\b", "no_longer_needed", normalized)

    hedged = re.search(
        r"\b(?:not sure|unsure|uncertain|not certain|maybe|perhaps|probably|possibly|"
        r"i think|i guess|i suppose|i'm not sure|i am not sure|i'm unsure|i am unsure|"
        r"i'm uncertain|i am uncertain|not convinced|i need to check|i need to confirm|"
        r"i want to check|i want to confirm|let me check|let me confirm)\b",
        normalized,
    )
    if hedged:
        return False

    negative = re.search(
        r"\b(no|don't|do not|not yet|stop|wait|change|incorrect|instead|"
        r"but|however|except|different|another|rather|unless|maybe|not that)\b",
        normalized,
    )
    if negative:
        return False
    if action != "cancel" and re.search(r"\bcancel(?:led|lation)?\b", normalized):
        return False
    # Consent must lead the reply, not appear as a substring later in a question or hedge.
    return bool(
        re.match(
            r"^(?:yes|yeah|yep|sure|absolutely|confirmed|i confirm|i agree|i accept|"
            r"that's right|that is right|sounds good|exactly right|correct|please do|"
            r"do it|go ahead|proceed)\b",
            normalized,
        )
    )


def _evaluate_exchange_confirmation_context(
    disclosure_text: str,
    confirmation_text: str,
    order_id: Any,
    old_items: Any,
    new_items: Any,
    payment_id: Any,
    price_difference: float | None,
) -> dict[str, bool]:
    """Apply the same disclosure and confirmation rules to live and post-hoc traces."""
    disclosure_text = disclosure_text if isinstance(disclosure_text, str) else ""
    confirmation_text = confirmation_text if isinstance(confirmation_text, str) else ""
    old_ids = old_items if isinstance(old_items, list) else []
    new_ids = new_items if isinstance(new_items, list) else []
    identifiers = [order_id, *old_ids, *new_ids, payment_id]
    identifiers_are_strings = all(isinstance(item, str) and item for item in identifiers)
    pairing_disclosed = _exchange_pairing_disclosed(disclosure_text, old_ids, new_ids)
    disclosure_valid = bool(
        identifiers_are_strings
        and disclosure_text.strip()
        and _contains_all(disclosure_text, identifiers)
        and any(term in disclosure_text.casefold() for term in ("exchange", "replace", "swap"))
        and pairing_disclosed
    )
    price_difference_disclosed = _price_difference_disclosed(disclosure_text, price_difference)
    confirmation_valid = bool(
        disclosure_valid
        and price_difference_disclosed
        and _is_affirmative(confirmation_text)
        and _confirmation_references_consistent(
            confirmation_text, order_id, old_ids, new_ids, payment_id
        )
    )
    return {
        "disclosure_valid": disclosure_valid,
        "pairing_disclosed": pairing_disclosed,
        "price_difference_disclosed": price_difference_disclosed,
        "confirmation_valid": confirmation_valid,
    }

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
