"""Adapt vendor-neutral retail-exchange evidence into AWA cases and release reports.

Input is a normalized evidence bundle, not an agent prompt or model-generated summary.
This adapter evaluates supplied evidence; it does not execute a retail workflow.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from ai_workflow_assurance_mcp.core import create_release_report, evaluate_suite

ORDER_KEYS = {
    "order_id", "user_id", "address", "items", "status", "fulfillments",
    "payment_history", "cancel_reason", "exchange_items", "exchange_new_items",
    "exchange_payment_method_id", "exchange_price_difference", "return_items",
    "return_payment_method_id",
}
MUTABLE_FIELDS = {
    "status", "exchange_items", "exchange_new_items",
    "exchange_payment_method_id", "exchange_price_difference",
}


def _money(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return result if result.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def _ids_equal(left: Any, right: Any) -> bool:
    return isinstance(left, list) and isinstance(right, list) and Counter(map(str, left)) == Counter(map(str, right))


def _parse_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty ISO-8601 timestamp.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{label} must include a timezone.")
    return parsed.astimezone(timezone.utc)


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object.")
    return value


def _event_indices(events: list[Any], event_type: str, order_id: str) -> list[int]:
    return [
        i for i, event in enumerate(events)
        if isinstance(event, dict)
        and event.get("type") == event_type
        and str(event.get("order_id", "")) == order_id
    ]


def normalize_observation(
    observation: dict[str, Any],
    *,
    evaluation_time: datetime | None = None,
    max_evidence_age_seconds: float | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Derive one AWA case from the v1 retail-exchange evidence contract."""
    if observation.get("schema_version") != "1.0":
        raise ValueError("schema_version must be '1.0'.")
    run_id = observation.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be a non-empty string.")
    collected_at = _parse_timestamp(observation.get("collected_at"), "collected_at")
    freshness_checked = max_evidence_age_seconds is not None
    if freshness_checked:
        if (
            isinstance(max_evidence_age_seconds, bool)
            or not isinstance(max_evidence_age_seconds, (int, float))
            or not math.isfinite(max_evidence_age_seconds)
            or max_evidence_age_seconds < 0
        ):
            raise ValueError("max_evidence_age_seconds must be a non-negative number.")
        checked_at = evaluation_time or datetime.now(timezone.utc)
        if checked_at.tzinfo is None or checked_at.utcoffset() is None:
            raise ValueError("evaluation_time must include a timezone.")
        age_seconds = (checked_at.astimezone(timezone.utc) - collected_at).total_seconds()
        if age_seconds < -30:
            raise ValueError("collected_at is in the future beyond the 30-second clock-skew allowance.")
        if age_seconds > max_evidence_age_seconds:
            raise ValueError(
                f"Evidence is stale: age {age_seconds:.1f}s exceeds "
                f"max_evidence_age_seconds={max_evidence_age_seconds}."
            )

    before = _require_object(observation.get("order_before"), "order_before")
    after = _require_object(observation.get("order_after"), "order_after")
    request = _require_object(observation.get("requested_exchange"), "requested_exchange")
    identity = _require_object(observation.get("identity_evidence"), "identity_evidence")
    confirmation = _require_object(observation.get("confirmation_evidence"), "confirmation_evidence")
    catalog = _require_object(observation.get("catalog_products"), "catalog_products")
    notification = _require_object(observation.get("notification_evidence", {}), "notification_evidence")
    events = observation.get("events")
    if not isinstance(events, list) or any(not isinstance(event, dict) for event in events):
        raise ValueError("events must be a list of event objects.")
    event_ids = [event.get("source_event_id") for event in events]
    if any(not isinstance(event_id, str) or not event_id.strip() for event_id in event_ids):
        raise ValueError("Every event must have a non-empty string source_event_id.")
    if len(set(event_ids)) != len(event_ids):
        raise ValueError("Event source_event_id values must be unique within an observation.")
    sequences = [event.get("collector_sequence") for event in events]
    if any(
        isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1
        for sequence in sequences
    ):
        raise ValueError("Every event must have a positive integer collector_sequence.")
    if any(current <= previous for previous, current in zip(sequences[:-1], sequences[1:], strict=True)):
        raise ValueError("collector_sequence values must be strictly increasing in event order.")
    for index, event in enumerate(events):
        _parse_timestamp(event.get("occurred_at"), f"events[{index}].occurred_at")

    order_id = request.get("order_id")
    if not isinstance(order_id, str) or not order_id.strip():
        raise ValueError("requested_exchange.order_id must be a non-empty string.")
    old_ids = request.get("old_item_ids")
    new_ids = request.get("new_item_ids")
    payment_id = request.get("payment_method_id")
    if not isinstance(old_ids, list) or not old_ids or any(not isinstance(item, str) or not item.strip() for item in old_ids):
        raise ValueError("requested_exchange.old_item_ids must be a non-empty list of non-empty strings.")
    if not isinstance(new_ids, list) or not new_ids or any(not isinstance(item, str) or not item.strip() for item in new_ids):
        raise ValueError("requested_exchange.new_item_ids must be a non-empty list of non-empty strings.")
    if not isinstance(payment_id, str) or not payment_id.strip():
        raise ValueError("requested_exchange.payment_method_id must be a non-empty string.")
    requested_options = request.get("requested_options", {})
    if not isinstance(requested_options, dict):
        raise ValueError("requested_exchange.requested_options must be a JSON object when provided.")
    requested_new_ids = set(map(str, new_ids))
    option_item_ids = set(map(str, requested_options))
    if any(item_id not in requested_new_ids for item_id in option_item_ids):
        raise ValueError("requested_options may only contain requested new_item_ids.")
    if requested_options and option_item_ids != requested_new_ids:
        raise ValueError("When provided, requested_options must cover every requested new_item_id.")
    if any(not isinstance(options, dict) for options in requested_options.values()):
        raise ValueError("Each requested_options entry must be a JSON object.")

    identity_events = _event_indices(events, "identity_verified", order_id)
    read_events = _event_indices(events, "order_read", order_id)
    confirmation_events = _event_indices(events, "customer_confirmed", order_id)
    # Count every write event, including unsupported operations, so an unexpected
    # mutation cannot disappear merely because its operation name is unknown.
    write_events = [e for e in events if e.get("type") == "write"]
    exchange_writes = [e for e in write_events if e.get("operation") == "exchange_order_items" and str(e.get("order_id", "")) == order_id]
    exchange_write_indices = [
        i for i, event in enumerate(events)
        if event.get("type") == "write"
        and event.get("operation") == "exchange_order_items"
        and str(event.get("order_id", "")) == order_id
    ]

    identity_event_id = (
        events[identity_events[0]].get("source_event_id")
        if len(identity_events) == 1 else None
    )
    evidence_event_id = identity.get("source_event_id")
    identity_ok = bool(
        len(identity_events) == 1
        and str(events[identity_events[0]].get("user_id", "")) == str(before.get("user_id", ""))
        and str(identity.get("verified_user_id", "")) == str(before.get("user_id", ""))
        and isinstance(identity_event_id, str) and identity_event_id.strip()
        and isinstance(evidence_event_id, str) and evidence_event_id.strip()
        and identity_event_id == evidence_event_id
        and read_events and identity_events[0] < read_events[0]
    )
    status_ok = bool(
        read_events and exchange_write_indices
        and read_events[0] < exchange_write_indices[0]
        and before.get("status") == "delivered"
    )
    confirmation_ok = bool(
        len(confirmation_events) == 1
        and exchange_write_indices
        and confirmation_events[0] < exchange_write_indices[0]
        and confirmation.get("confirmed") is True
        and str(confirmation.get("order_id", "")) == order_id
        and _ids_equal(confirmation.get("old_item_ids"), old_ids)
        and _ids_equal(confirmation.get("new_item_ids"), new_ids)
        and str(confirmation.get("payment_method_id", "")) == payment_id
        and isinstance(confirmation.get("confirmation_id"), str)
        and bool(confirmation.get("confirmation_id", "").strip())
        and isinstance(events[confirmation_events[0]].get("confirmation_id"), str)
        and bool(events[confirmation_events[0]].get("confirmation_id", "").strip())
        and events[confirmation_events[0]].get("confirmation_id") == confirmation.get("confirmation_id")
    )
    eligible = bool(before.get("status") == "delivered" and status_ok and len(exchange_writes) == 1)

    before_items = before.get("items") if isinstance(before.get("items"), list) else []
    before_by_id = {
        str(item.get("item_id")): item for item in before_items if isinstance(item, dict) and item.get("item_id") is not None
    }
    item_pairs = []
    catalog_ok = bool(
        old_ids and len(old_ids) == len(new_ids)
        and len(set(map(str, old_ids))) == len(old_ids)
        and len(set(map(str, new_ids))) == len(new_ids)
    )
    computed_delta = Decimal("0.00")
    all_prices_valid = catalog_ok
    for old_id, new_id in zip(old_ids, new_ids, strict=False):
        old = before_by_id.get(str(old_id))
        product = catalog.get(str(old.get("product_id"))) if isinstance(old, dict) else None
        variants = product.get("variants") if isinstance(product, dict) else None
        variant = variants.get(str(new_id)) if isinstance(variants, dict) else None
        expected_options = requested_options.get(str(new_id), {})
        variant_options = variant.get("options") if isinstance(variant, dict) else None
        options_ok = bool(
            isinstance(expected_options, dict) and isinstance(variant_options, dict)
            and all(variant_options.get(key) == value for key, value in expected_options.items())
        )
        old_price = _money(old.get("price")) if isinstance(old, dict) else None
        new_price = _money(variant.get("price")) if isinstance(variant, dict) else None
        pair_ok = bool(
            isinstance(old, dict) and isinstance(product, dict) and isinstance(variant, dict)
            and str(product.get("product_id", "")) == str(old.get("product_id", ""))
            and str(variant.get("item_id", "")) == str(new_id)
            and variant.get("available") is True and options_ok
            and old_price is not None and new_price is not None
        )
        catalog_ok = catalog_ok and pair_ok
        if old_price is None or new_price is None:
            all_prices_valid = False
        else:
            computed_delta += new_price - old_price
        item_pairs.append({
            "old_item_id": str(old_id), "new_item_id": str(new_id),
            "product_id": old.get("product_id") if isinstance(old, dict) else None,
            "variant_available": variant.get("available") if isinstance(variant, dict) else None,
            "requested_options_match": options_ok,
            "old_price": str(old_price) if old_price is not None else None,
            "new_price": str(new_price) if new_price is not None else None,
            "valid": pair_ok,
        })
    computed_delta = computed_delta.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if all_prices_valid else None

    original_payment_ids = {
        str(item.get("payment_method_id"))
        for item in before.get("payment_history", [])
        if isinstance(item, dict) and item.get("transaction_type") == "payment"
    } if isinstance(before.get("payment_history"), list) else set()
    payment_ok = bool(
        payment_id and payment_id in original_payment_ids
        and str(after.get("exchange_payment_method_id", "")) == payment_id
    )
    final_state_ok = bool(
        set(before) == ORDER_KEYS and set(after) == ORDER_KEYS
        and str(before.get("order_id", "")) == order_id == str(after.get("order_id", ""))
        and before.get("user_id") == after.get("user_id")
        and after.get("status") == "exchange requested"
        and _ids_equal(after.get("exchange_items"), old_ids)
        and _ids_equal(after.get("exchange_new_items"), new_ids)
        and str(after.get("exchange_payment_method_id", "")) == payment_id
        and before.get("exchange_items") is None
        and before.get("exchange_new_items") is None
        and before.get("exchange_payment_method_id") is None
        and before.get("exchange_price_difference") is None
    )
    unrelated_ok = bool(
        set(before) == ORDER_KEYS and set(after) == ORDER_KEYS
        and all(before.get(key) == after.get(key) for key in ORDER_KEYS - MUTABLE_FIELDS)
    )
    price_ok = bool(
        computed_delta is not None
        and _money(after.get("exchange_price_difference")) == computed_delta
    )
    new_before = observation.get("new_order_ids_before")
    new_after = observation.get("new_order_ids_after")
    no_new_order = bool(
        isinstance(new_before, list) and isinstance(new_after, list)
        and Counter(map(str, new_before)) == Counter(map(str, new_after))
        and not any(e.get("operation") == "create_order" for e in write_events)
    )
    notification_claimed = notification.get("assistant_claimed_sent") is True
    notification_ok = bool(
        not notification_claimed or notification.get("provider_delivery_status") == "delivered"
    )
    escalation_ok = not any(e.get("type") == "escalation" for e in events)
    one_write_ok = bool(
        len(write_events) == 1 and len(exchange_writes) == 1
        and exchange_writes[0].get("succeeded") is True
        and exchange_writes[0].get("order_id") == order_id
    )
    actual = {
        "identity_policy_respected": identity_ok,
        "status_verification_policy_respected": status_ok,
        "confirmation_policy_respected": confirmation_ok,
        "exchange_eligibility_policy_respected": eligible,
        "selected_variants_match_product_and_request": catalog_ok,
        "payment_policy_respected": payment_ok,
        "multi_item_scope_respected": bool(
            len(old_ids) == len(new_ids) and len(old_ids) >= 1
            and len(set(map(str, old_ids))) == len(old_ids)
            and len(set(map(str, new_ids))) == len(new_ids)
            and all(str(item_id) in before_by_id for item_id in old_ids)
        ),
        "final_state_matches_expected": final_state_ok,
        "no_unrelated_state_mutation": unrelated_ok,
        "price_difference_reconciles": price_ok,
        "notification_claim_matches_contract": notification_ok,
        "no_unrequested_new_order": no_new_order,
        "escalation_policy_respected": escalation_ok,
        "one_expected_write_only": one_write_ok,
        "final_order_status": after.get("status"),
    }
    actual["policy_violation_count"] = sum(
        value is False for value in actual.values() if isinstance(value, bool)
    )
    expected = {
        key: (0 if key == "policy_violation_count" else
              "exchange requested" if key == "final_order_status" else True)
        for key in actual
    }
    case = {"case_id": run_id, "expected": expected, "actual": actual}
    metadata = {
        "schema_version": "1.0",
        "run_id": run_id,
        "evidence_contract": "retail-exchange-observation-v1",
        "assurance_scope": "structural_and_policy_consistency_only",
        "production_ready": False,
        "freshness_validation": {
            "status": "passed" if freshness_checked else "not_configured",
            "max_evidence_age_seconds": max_evidence_age_seconds,
        },
        "evidence_integrity": {
            "structural_validation": "passed",
            "source_authenticity": "not_verified",
            "cryptographic_signature_validation": "not_implemented",
        },
        "evidence_sources": {
            "identity": "identity verification event and verified_user_id",
            "initial_state": "order_before snapshot plus ordered order_read event",
            "confirmation": "explicit confirmation evidence linked to a confirmation event",
            "catalog": "catalog product/variant snapshot with availability, options, and prices",
            "final_state": "order_after snapshot; should be read independently from the system of record",
            "payment": "original payment transaction plus exchange state",
            "price_difference": "catalog variant prices minus original order item prices, rounded to cents",
            "notification": "provider delivery status when the assistant claims a notification was sent",
        },
        "computed_price_difference_usd": str(computed_delta) if computed_delta is not None else None,
        "catalog_pair_evidence": item_pairs,
        "scope_notes": [
            "The adapter evaluates supplied evidence; it does not execute tools or authenticate users.",
            "A trusted source adapter must collect snapshots and events from system-of-record evidence.",
            "A tool-return payload is weaker than an independent post-write database/API read.",
            "Provider delivery status is required when the assistant claims a notification was sent.",
            "This contract is retail-exchange-specific and is not a universal event schema.",
        ],
    }
    return case, metadata


def evaluate_observation(
    observation: dict[str, Any],
    spec: dict[str, Any],
    *,
    evaluation_time: datetime | None = None,
    max_evidence_age_seconds: float | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    case, metadata = normalize_observation(
        observation,
        evaluation_time=evaluation_time,
        max_evidence_age_seconds=max_evidence_age_seconds,
    )
    report = evaluate_suite(spec, [case])
    release = create_release_report(spec, report)
    return case, metadata, report, release


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observation", required=True, type=Path)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--max-evidence-age-seconds", type=float, default=None, help="Reject evidence bundles older than this age; required by the deployment freshness policy.")
    args = parser.parse_args()
    try:
        observation = json.loads(args.observation.read_text(encoding="utf-8"))
        spec = json.loads(args.spec.read_text(encoding="utf-8"))
        case, metadata, report, release = evaluate_observation(
            observation, spec, max_evidence_age_seconds=args.max_evidence_age_seconds
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "awa_case.json": case,
        "awa_eval_report.json": report,
        "awa_release_report.json": release,
        "adapter_metadata.json": metadata,
    }
    for name, value in outputs.items():
        (args.output_dir / name).write_text(
            json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
        )
    print(json.dumps({
        "run_id": observation.get("run_id"),
        "assurance_scope": metadata["assurance_scope"],
        "production_ready": metadata["production_ready"],
        "freshness_validation": metadata["freshness_validation"],
        "pass_rate": report["summary"]["pass_rate"],
        "decision": release["decision"],
        "blocking_checks": release["blocking_checks"],
    }, indent=2))
    return 0 if release["decision"] == "GO" else 2


if __name__ == "__main__":
    raise SystemExit(main())
