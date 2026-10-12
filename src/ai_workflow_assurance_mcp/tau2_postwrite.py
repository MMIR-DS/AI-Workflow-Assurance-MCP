"""Independent post-write invariants for Tau2 retail order snapshots.

This audit compares persisted order rows with their authoritative product/variant
snapshots. It is intentionally separate from Tau2's replay-based reward/DB oracle.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any


def _field(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _money(value: Any) -> Decimal | None:
    """Normalize a JSON-style numeric price to cents without accepting booleans."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    try:
        amount = Decimal(str(value))
        if not amount.is_finite():
            return None
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None


def _catalog_entries(product_snapshots: Any) -> list[Any] | None:
    """Accept a list of product snapshots or a mapping of product IDs to snapshots."""
    if isinstance(product_snapshots, (list, tuple)):
        return list(product_snapshots)
    if isinstance(product_snapshots, Mapping):
        if _field(product_snapshots, "product_id") and isinstance(
            _field(product_snapshots, "variants"), Mapping
        ):
            return [product_snapshots]
        return list(product_snapshots.values())
    return None


def audit_tau2_order_items_against_catalog(
    order_snapshot: Any,
    product_snapshots: Any,
) -> dict[str, Any]:
    """Audit each order item's product, variant, price, and options against catalog data.

    Decision semantics:
    - PASS: all order items are fully evaluable and match their catalog variants.
    - FAIL: at least one definite item/catalog invariant is violated.
    - NOT_EVALUABLE: no definite mismatch was found, but evidence is missing/malformed.
      A caller must not treat NOT_EVALUABLE as a successful audit.

    Product snapshots use Tau2's get_product_details shape:
    {product_id, variants: {item_id: {item_id, price, options, ...}}}.
    """
    order_id = _field(order_snapshot, "order_id")
    items = _field(order_snapshot, "items")
    product_entries = _catalog_entries(product_snapshots)

    checked: dict[str, str] = {
        "order_snapshot_is_well_formed": "PASS",
        "catalog_snapshots_are_well_formed": "PASS",
        "every_item_has_a_catalog_product_snapshot": "PASS",
        "item_variants_exist_in_catalog": "PASS",
        "item_prices_match_catalog": "PASS",
        "item_options_match_catalog": "PASS",
    }
    violations: list[dict[str, Any]] = []
    not_evaluable: list[dict[str, Any]] = []
    validated_item_count = 0

    def set_status(check: str, status: str) -> None:
        current = checked[check]
        if current == "FAIL":
            return
        if status == "FAIL" or (status == "NOT_EVALUABLE" and current != "FAIL"):
            checked[check] = status

    def record_unknown(
        check: str,
        detail: str,
        *,
        item_index: int | None = None,
        product_id: str | None = None,
        item_id: str | None = None,
    ) -> None:
        set_status(check, "NOT_EVALUABLE")
        entry: dict[str, Any] = {"check": check, "detail": detail}
        if item_index is not None:
            entry["item_index"] = item_index
        if product_id is not None:
            entry["product_id"] = product_id
        if item_id is not None:
            entry["item_id"] = item_id
        not_evaluable.append(entry)

    def record_violation(
        check: str,
        *,
        item_index: int,
        product_id: str,
        item_id: str,
        expected: Any,
        actual: Any,
    ) -> None:
        set_status(check, "FAIL")
        violations.append(
            {
                "check": check,
                "item_index": item_index,
                "product_id": product_id,
                "item_id": item_id,
                "expected": expected,
                "actual": actual,
            }
        )

    order_shape_valid = (
        isinstance(order_id, str)
        and bool(order_id.strip())
        and isinstance(items, (list, tuple))
        and bool(items)
    )
    if not order_shape_valid:
        record_unknown(
            "order_snapshot_is_well_formed",
            "Expected a non-empty order_id and a non-empty items list.",
        )

    if product_entries is None:
        record_unknown(
            "catalog_snapshots_are_well_formed",
            "Expected a product snapshot, a sequence of snapshots, or a product-ID mapping.",
        )
        product_entries = []

    products_by_id: dict[str, Mapping[str, Any]] = {}
    seen_product_ids: set[str] = set()
    ambiguous_product_ids: set[str] = set()
    for product in product_entries:
        product_id = _field(product, "product_id")
        variants = _field(product, "variants")
        if not (
            isinstance(product, Mapping)
            and isinstance(product_id, str)
            and product_id
            and isinstance(variants, Mapping)
        ):
            record_unknown(
                "catalog_snapshots_are_well_formed",
                "Each product snapshot must contain product_id and a variants mapping.",
            )
            continue
        if product_id in seen_product_ids:
            ambiguous_product_ids.add(product_id)
            products_by_id.pop(product_id, None)
            record_unknown(
                "catalog_snapshots_are_well_formed",
                "Duplicate product_id snapshots are ambiguous.",
                product_id=product_id,
            )
            continue
        seen_product_ids.add(product_id)
        products_by_id[product_id] = product

    # A product duplicated anywhere in the input remains ambiguous, even if a third
    # entry with the same ID appears later.
    for product_id in ambiguous_product_ids:
        products_by_id.pop(product_id, None)

    if isinstance(items, (list, tuple)):
        for index, item in enumerate(items):
            product_id = _field(item, "product_id")
            item_id = _field(item, "item_id")
            actual_price_value = _field(item, "price")
            actual_options = _field(item, "options")

            if not isinstance(item, Mapping):
                record_unknown(
                    "order_snapshot_is_well_formed",
                    "An order item is not an object/mapping.",
                    item_index=index,
                )
                continue
            if not (
                isinstance(product_id, str)
                and product_id
                and isinstance(item_id, str)
                and item_id
            ):
                record_unknown(
                    "order_snapshot_is_well_formed",
                    "An order item is missing a non-empty product_id or item_id.",
                    item_index=index,
                )
                continue

            product = products_by_id.get(product_id)
            if product is None:
                record_unknown(
                    "every_item_has_a_catalog_product_snapshot",
                    "No unique, valid catalog snapshot was supplied for this product_id.",
                    item_index=index,
                    product_id=product_id,
                    item_id=item_id,
                )
                continue

            variants = _field(product, "variants")
            if not isinstance(variants, Mapping):
                record_unknown(
                    "catalog_snapshots_are_well_formed",
                    "The product's variants field is not a mapping.",
                    item_index=index,
                    product_id=product_id,
                    item_id=item_id,
                )
                continue

            variant = variants.get(item_id)
            if not isinstance(variant, Mapping):
                record_violation(
                    "item_variants_exist_in_catalog",
                    item_index=index,
                    product_id=product_id,
                    item_id=item_id,
                    expected="variant present under this product_id",
                    actual="variant missing",
                )
                continue

            if _field(variant, "item_id") != item_id:
                record_violation(
                    "item_variants_exist_in_catalog",
                    item_index=index,
                    product_id=product_id,
                    item_id=item_id,
                    expected=item_id,
                    actual=_field(variant, "item_id"),
                )
                continue

            # Count an item as validated only if every catalog invariant is evaluable
            # and matches. The decision already fails closed; this keeps the summary
            # metric from overstating the number of fully verified items.
            item_validated = True
            expected_price = _money(_field(variant, "price"))
            if expected_price is None:
                record_unknown(
                    "item_prices_match_catalog",
                    "Catalog variant price is missing or not a finite numeric amount.",
                    item_index=index,
                    product_id=product_id,
                    item_id=item_id,
                )
                item_validated = False
            else:
                actual_price = _money(actual_price_value)
                if actual_price is None:
                    record_violation(
                        "item_prices_match_catalog",
                        item_index=index,
                        product_id=product_id,
                        item_id=item_id,
                        expected=str(expected_price),
                        actual=actual_price_value,
                    )
                    item_validated = False
                elif actual_price != expected_price:
                    record_violation(
                        "item_prices_match_catalog",
                        item_index=index,
                        product_id=product_id,
                        item_id=item_id,
                        expected=str(expected_price),
                        actual=str(actual_price),
                    )
                    item_validated = False

            expected_options = _field(variant, "options")
            if not isinstance(expected_options, Mapping):
                record_unknown(
                    "item_options_match_catalog",
                    "Catalog variant options are missing or not a mapping.",
                    item_index=index,
                    product_id=product_id,
                    item_id=item_id,
                )
                item_validated = False
            elif not isinstance(actual_options, Mapping):
                record_violation(
                    "item_options_match_catalog",
                    item_index=index,
                    product_id=product_id,
                    item_id=item_id,
                    expected=dict(expected_options),
                    actual=actual_options,
                )
                item_validated = False
            elif dict(actual_options) != dict(expected_options):
                record_violation(
                    "item_options_match_catalog",
                    item_index=index,
                    product_id=product_id,
                    item_id=item_id,
                    expected=dict(expected_options),
                    actual=dict(actual_options),
                )
                item_validated = False

            if item_validated:
                validated_item_count += 1

    if any(status == "FAIL" for status in checked.values()):
        decision = "FAIL"
    elif any(status == "NOT_EVALUABLE" for status in checked.values()):
        decision = "NOT_EVALUABLE"
    else:
        decision = "PASS"

    return {
        "decision": decision,
        "checked": checked,
        "blocking_checks": [
            name for name, status in checked.items() if status != "PASS"
        ],
        "violations": violations,
        "not_evaluable": not_evaluable,
        "evidence_summary": {
            "order_id": order_id if isinstance(order_id, str) else None,
            "order_item_count": len(items) if isinstance(items, (list, tuple)) else None,
            "catalog_product_count": len(products_by_id),
            "validated_item_count": validated_item_count,
            "violation_count": len(violations),
            "not_evaluable_count": len(not_evaluable),
        },
        "scope": "tau2_order_snapshot_vs_product_catalog_not_production_data_integrity_proof",
    }


def _trace_messages(trajectory: Any) -> list[Any] | None:
    if isinstance(trajectory, (list, tuple)):
        return list(trajectory)
    return None


def _trace_tool_calls(message: Any) -> list[Any]:
    calls = _field(message, "tool_calls", []) or []
    return list(calls) if isinstance(calls, (list, tuple)) else []


def _json_object(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    if not isinstance(value, str):
        return None
    try:
        decoded = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None
    return decoded if isinstance(decoded, Mapping) else None


def _trace_not_evaluable(
    order_id: Any,
    check: str,
    detail: str,
    *,
    write_call_id: str | None = None,
) -> dict[str, Any]:
    return {
        "decision": "NOT_EVALUABLE",
        "checked": {check: "NOT_EVALUABLE"},
        "blocking_checks": [check],
        "violations": [],
        "not_evaluable": [{"check": check, "detail": detail}],
        "evidence_summary": {
            "order_id": order_id if isinstance(order_id, str) else None,
            "write_call_id": write_call_id,
            "post_write_snapshot_source": None,
            "catalog_product_count": 0,
            "validated_item_count": 0,
            "violation_count": 0,
            "not_evaluable_count": 1,
        },
        "scope": "tau2_trace_postwrite_audit_not_production_data_integrity_proof",
    }


def audit_tau2_trace_postwrite(
    trajectory: Any,
    order_id: str,
    *,
    write_tool_name: str = "modify_pending_order_items",
) -> dict[str, Any]:
    """Extract the post-write order and catalog evidence from a Tau2 message trace.

    The successful write result is treated as a post-write order snapshot unless a
    later matching get_order_details result exists. The latest catalog read for each
    product is used; a later failed or mismatched read supersedes older catalog data.
    """
    messages = _trace_messages(trajectory)
    if messages is None:
        return _trace_not_evaluable(
            order_id,
            "trajectory_is_well_formed",
            "Expected a list of Tau2 messages.",
        )
    if not isinstance(order_id, str) or not order_id.strip():
        return _trace_not_evaluable(
            order_id,
            "order_id_is_valid",
            "A non-empty target order_id is required.",
        )
    if not isinstance(write_tool_name, str) or not write_tool_name:
        return _trace_not_evaluable(
            order_id,
            "write_tool_name_is_valid",
            "A non-empty write_tool_name is required.",
        )

    write_attempts: list[dict[str, Any]] = []
    for message_index, message in enumerate(messages):
        for call in _trace_tool_calls(message):
            arguments = _field(call, "arguments", {})
            if (
                _field(call, "name") != write_tool_name
                or not isinstance(arguments, Mapping)
                or arguments.get("order_id") != order_id
            ):
                continue
            call_id = _field(call, "id")
            if not isinstance(call_id, str) or not call_id:
                write_attempts.append(
                    {
                        "call_id": None,
                        "call_index": message_index,
                        "result_index": -1,
                        "outcome": "malformed_call_id",
                        "order_snapshot": None,
                    }
                )
                continue

            result_message = None
            result_index = -1
            for candidate_index in range(message_index + 1, len(messages)):
                candidate = messages[candidate_index]
                if (
                    _field(candidate, "role") == "tool"
                    and _field(candidate, "id") == call_id
                ):
                    result_message = candidate
                    result_index = candidate_index
                    break

            outcome = "missing_result"
            order_result: Mapping[str, Any] | None = None
            if result_message is not None:
                content = _field(result_message, "content")
                if isinstance(content, str) and "AWA_PREWRITE_NO_GO" in content:
                    outcome = "blocked"
                elif _field(result_message, "error", False) is True:
                    outcome = "tool_error"
                else:
                    parsed_result = _json_object(content)
                    if (
                        isinstance(parsed_result, Mapping)
                        and parsed_result.get("order_id") == order_id
                        and isinstance(parsed_result.get("items"), (list, tuple))
                    ):
                        order_result = parsed_result
                        outcome = "successful_order_snapshot"
                    else:
                        outcome = "invalid_result"

            write_attempts.append(
                {
                    "call_id": call_id,
                    "call_index": message_index,
                    "result_index": result_index,
                    "outcome": outcome,
                    "order_snapshot": order_result,
                }
            )

    if not write_attempts:
        return _trace_not_evaluable(
            order_id,
            "matching_write_attempt_available",
            "No matching write-tool call for the target order was found in the trace.",
        )

    # Never fall back to an older successful write result after a newer attempt failed
    # or was blocked. The state must then be established by a fresh subsequent order read.
    latest_attempt = write_attempts[-1]
    post_order = latest_attempt["order_snapshot"]
    snapshot_source = "successful_write_result"
    latest_read_seen = False
    latest_read_snapshot: Mapping[str, Any] | None = None
    read_start_index = (
        latest_attempt["result_index"]
        if latest_attempt["result_index"] >= 0
        else latest_attempt["call_index"]
    )

    for message_index in range(read_start_index + 1, len(messages)):
        message = messages[message_index]
        for call in _trace_tool_calls(message):
            arguments = _field(call, "arguments", {})
            if (
                _field(call, "name") != "get_order_details"
                or not isinstance(arguments, Mapping)
                or arguments.get("order_id") != order_id
            ):
                continue
            latest_read_seen = True
            latest_read_snapshot = None
            call_id = _field(call, "id")
            if not isinstance(call_id, str) or not call_id:
                continue
            result_message = next(
                (
                    candidate
                    for candidate in messages[message_index + 1 :]
                    if _field(candidate, "role") == "tool"
                    and _field(candidate, "id") == call_id
                ),
                None,
            )
            if result_message is None or _field(result_message, "error", False) is True:
                continue
            candidate_order = _json_object(_field(result_message, "content"))
            if (
                isinstance(candidate_order, Mapping)
                and candidate_order.get("order_id") == order_id
                and isinstance(candidate_order.get("items"), (list, tuple))
            ):
                latest_read_snapshot = candidate_order

    if latest_read_seen:
        if latest_read_snapshot is None:
            return _trace_not_evaluable(
                order_id,
                "latest_postwrite_order_read_is_valid",
                "A later order read was attempted but the latest result is missing, "
                "failed, malformed, or does not match the requested order.",
                write_call_id=latest_attempt["call_id"],
            )
        post_order = latest_read_snapshot
        snapshot_source = "get_order_details_after_latest_write_attempt"
    elif latest_attempt["outcome"] != "successful_order_snapshot":
        result = _trace_not_evaluable(
            order_id,
            "successful_postwrite_order_snapshot_available",
            "The latest matching write attempt was "
            f"{latest_attempt['outcome']!r}. Its result cannot establish post-write "
            "state, and no subsequent matching get_order_details snapshot was found.",
            write_call_id=latest_attempt["call_id"],
        )
        result["evidence_summary"]["latest_write_outcome"] = latest_attempt["outcome"]
        return result

    if not isinstance(post_order, Mapping):
        return _trace_not_evaluable(
            order_id,
            "postwrite_order_snapshot_is_available",
            "No valid post-write order snapshot could be established.",
            write_call_id=latest_attempt["call_id"],
        )
    write_call_id = latest_attempt["call_id"]

    # Product catalog data is unaffected by order writes. Use the latest observed
    # result for each product in the post-write order; failed latest reads invalidate
    # earlier reads instead of silently reusing stale data.
    target_product_ids = {
        item.get("product_id")
        for item in post_order.get("items", [])
        if isinstance(item, Mapping)
        and isinstance(item.get("product_id"), str)
        and item.get("product_id")
    }
    latest_products: dict[str, Mapping[str, Any] | None] = {}
    for message_index, message in enumerate(messages):
        for call in _trace_tool_calls(message):
            arguments = _field(call, "arguments", {})
            if (
                _field(call, "name") != "get_product_details"
                or not isinstance(arguments, Mapping)
            ):
                continue
            product_id = arguments.get("product_id")
            if not isinstance(product_id, str) or product_id not in target_product_ids:
                continue
            call_id = _field(call, "id")
            result_message = None
            if isinstance(call_id, str) and call_id:
                result_message = next(
                    (
                        candidate
                        for candidate in messages[message_index + 1 :]
                        if _field(candidate, "role") == "tool"
                        and _field(candidate, "id") == call_id
                    ),
                    None,
                )
            snapshot = (
                _json_object(_field(result_message, "content"))
                if result_message is not None
                and _field(result_message, "error", False) is not True
                else None
            )
            latest_products[product_id] = (
                snapshot
                if isinstance(snapshot, Mapping)
                and snapshot.get("product_id") == product_id
                and isinstance(snapshot.get("variants"), Mapping)
                else None
            )

    product_snapshots = [
        snapshot
        for product_id, snapshot in latest_products.items()
        if product_id in target_product_ids and snapshot is not None
    ]
    result = audit_tau2_order_items_against_catalog(post_order, product_snapshots)
    result.setdefault("evidence_summary", {}).update(
        {
            "write_call_id": write_call_id,
            "latest_write_outcome": latest_attempt["outcome"],
            "write_tool_name": write_tool_name,
            "post_write_snapshot_source": snapshot_source,
            "catalog_product_count": len(product_snapshots),
            "catalog_product_ids_missing": sorted(
                (target_product_ids - set(latest_products.keys()))
                | {
                    product_id
                    for product_id, snapshot in latest_products.items()
                    if snapshot is None
                }
            ),
        }
    )
    result["scope"] = "tau2_trace_postwrite_audit_not_production_data_integrity_proof"
    return result


def audit_tau2_benchmark_result_postwrite(
    benchmark_result: Any,
    *,
    write_tool_name: str = "modify_pending_order_items",
    simulation_index: int | None = None,
) -> dict[str, Any]:
    """Audit write results across a complete Tau2 benchmark JSON artifact.

    Expected artifact shape: a mapping with a simulations list where every
    simulation contains a messages trace. Each matching target write/order is
    audited independently. Tau2 reward metadata is deliberately ignored.
    """
    simulations = _field(benchmark_result, "simulations")
    if not isinstance(simulations, (list, tuple)):
        return {
            "decision": "NOT_EVALUABLE",
            "checked": {"benchmark_simulations_are_well_formed": "NOT_EVALUABLE"},
            "blocking_checks": ["benchmark_simulations_are_well_formed"],
            "simulation_results": [],
            "order_audits": [],
            "evidence_summary": {
                "simulation_count": 0,
                "selected_simulation_indices": [],
                "order_audit_count": 0,
                "simulations_without_matching_write": 0,
                "fail_count": 0,
                "not_evaluable_count": 1,
            },
            "scope": "tau2_benchmark_artifact_postwrite_audit_not_production_data_integrity_proof",
            "not_evaluable": [
                {
                    "check": "benchmark_simulations_are_well_formed",
                    "detail": "Expected a Tau2 benchmark artifact with a simulations list.",
                }
            ],
        }
    if not isinstance(write_tool_name, str) or not write_tool_name:
        return {
            "decision": "NOT_EVALUABLE",
            "checked": {"write_tool_name_is_valid": "NOT_EVALUABLE"},
            "blocking_checks": ["write_tool_name_is_valid"],
            "simulation_results": [],
            "order_audits": [],
            "evidence_summary": {
                "simulation_count": len(simulations),
                "selected_simulation_indices": [],
                "order_audit_count": 0,
                "simulations_without_matching_write": 0,
                "fail_count": 0,
                "not_evaluable_count": 1,
            },
            "scope": "tau2_benchmark_artifact_postwrite_audit_not_production_data_integrity_proof",
            "not_evaluable": [
                {
                    "check": "write_tool_name_is_valid",
                    "detail": "A non-empty write_tool_name is required.",
                }
            ],
        }

    if simulation_index is None:
        selected = list(enumerate(simulations))
    elif (
        isinstance(simulation_index, int)
        and not isinstance(simulation_index, bool)
        and 0 <= simulation_index < len(simulations)
    ):
        selected = [(simulation_index, simulations[simulation_index])]
    else:
        return {
            "decision": "NOT_EVALUABLE",
            "checked": {"simulation_index_is_valid": "NOT_EVALUABLE"},
            "blocking_checks": ["simulation_index_is_valid"],
            "simulation_results": [],
            "order_audits": [],
            "evidence_summary": {
                "simulation_count": len(simulations),
                "selected_simulation_indices": [],
                "order_audit_count": 0,
                "simulations_without_matching_write": 0,
                "fail_count": 0,
                "not_evaluable_count": 1,
            },
            "scope": "tau2_benchmark_artifact_postwrite_audit_not_production_data_integrity_proof",
            "not_evaluable": [
                {
                    "check": "simulation_index_is_valid",
                    "detail": (
                        "simulation_index must be a valid zero-based index into simulations."
                    ),
                }
            ],
        }

    if not selected:
        return {
            "decision": "NOT_EVALUABLE",
            "checked": {"at_least_one_simulation_selected": "NOT_EVALUABLE"},
            "blocking_checks": ["at_least_one_simulation_selected"],
            "simulation_results": [],
            "order_audits": [],
            "evidence_summary": {
                "simulation_count": 0,
                "selected_simulation_indices": [],
                "order_audit_count": 0,
                "simulations_without_matching_write": 0,
                "fail_count": 0,
                "not_evaluable_count": 1,
                "benchmark_reward_used_as_integrity_oracle": False,
            },
            "scope": "tau2_benchmark_artifact_postwrite_audit_not_production_data_integrity_proof",
            "not_evaluable": [
                {
                    "check": "at_least_one_simulation_selected",
                    "detail": "The benchmark artifact contains no simulations to audit.",
                }
            ],
        }

    simulation_results: list[dict[str, Any]] = []
    order_audits: list[dict[str, Any]] = []
    simulation_decisions: list[str] = []
    simulations_without_write = 0
    all_simulations_well_formed = True

    for index, simulation in selected:
        task_id = _field(simulation, "task_id")
        messages = _trace_messages(_field(simulation, "messages"))
        if messages is None:
            all_simulations_well_formed = False
            audit = _trace_not_evaluable(
                None,
                "simulation_messages_are_well_formed",
                "This simulation does not contain a messages list.",
            )
            entry = {
                "simulation_index": index,
                "task_id": task_id,
                "decision": "NOT_EVALUABLE",
                "order_audits": [],
                "not_evaluable": audit["not_evaluable"],
            }
            simulation_results.append(entry)
            simulation_decisions.append("NOT_EVALUABLE")
            continue

        target_order_ids: list[str] = []
        for message in messages:
            for call in _trace_tool_calls(message):
                arguments = _field(call, "arguments", {})
                if (
                    _field(call, "name") == write_tool_name
                    and isinstance(arguments, Mapping)
                    and isinstance(arguments.get("order_id"), str)
                    and arguments["order_id"].strip()
                    and arguments["order_id"] not in target_order_ids
                ):
                    target_order_ids.append(arguments["order_id"])

        if not target_order_ids:
            audit = _trace_not_evaluable(
                None,
                "matching_write_attempt_available",
                f"No {write_tool_name!r} call with a valid order_id was found in this simulation.",
            )
            simulation_results.append(
                {
                    "simulation_index": index,
                    "task_id": task_id,
                    "decision": "NOT_EVALUABLE",
                    "order_audits": [],
                    "not_evaluable": audit["not_evaluable"],
                }
            )
            simulation_decisions.append("NOT_EVALUABLE")
            simulations_without_write += 1
            continue

        this_simulation_audits: list[dict[str, Any]] = []
        for target_order_id in target_order_ids:
            audit = audit_tau2_trace_postwrite(
                messages,
                target_order_id,
                write_tool_name=write_tool_name,
            )
            audit_entry = {
                "simulation_index": index,
                "task_id": task_id,
                "order_id": target_order_id,
                **audit,
            }
            this_simulation_audits.append(audit_entry)
            order_audits.append(audit_entry)

        this_decisions = [audit["decision"] for audit in this_simulation_audits]
        if any(decision == "FAIL" for decision in this_decisions):
            simulation_decision = "FAIL"
        elif any(decision != "PASS" for decision in this_decisions):
            simulation_decision = "NOT_EVALUABLE"
        else:
            simulation_decision = "PASS"
        simulation_results.append(
            {
                "simulation_index": index,
                "task_id": task_id,
                "decision": simulation_decision,
                "order_audits": this_simulation_audits,
            }
        )
        simulation_decisions.append(simulation_decision)

    if any(decision == "FAIL" for decision in simulation_decisions):
        decision = "FAIL"
    elif not simulation_decisions or any(
        decision != "PASS" for decision in simulation_decisions
    ):
        decision = "NOT_EVALUABLE"
    else:
        decision = "PASS"

    fail_count = sum(audit["decision"] == "FAIL" for audit in order_audits)
    not_evaluable_order_count = sum(
        audit["decision"] == "NOT_EVALUABLE" for audit in order_audits
    )
    simulations_without_usable_trace = sum(
        item["decision"] == "NOT_EVALUABLE" and not item["order_audits"]
        for item in simulation_results
    )
    not_evaluable_count = (
        not_evaluable_order_count + simulations_without_usable_trace
    )
    not_evaluable_simulation_count = sum(
        item["decision"] == "NOT_EVALUABLE" for item in simulation_results
    )
    blocking_checks: list[str] = []
    if fail_count:
        blocking_checks.append("one_or_more_order_audits_failed")
    if not_evaluable_count:
        blocking_checks.append("one_or_more_simulations_not_evaluable")
    if simulations_without_usable_trace:
        blocking_checks.append("one_or_more_simulations_have_no_usable_write_trace")

    return {
        "decision": decision,
        "checked": {
            "benchmark_simulations_are_well_formed": (
                "PASS" if all_simulations_well_formed else "NOT_EVALUABLE"
            ),
            "all_target_order_audits_passed": (
                "PASS" if decision == "PASS" else decision
            ),
        },
        "blocking_checks": blocking_checks,
        "simulation_results": simulation_results,
        "order_audits": order_audits,
        "evidence_summary": {
            "simulation_count": len(simulation_results),
            "selected_simulation_indices": [index for index, _ in selected],
            "order_audit_count": len(order_audits),
            "simulations_without_matching_write": simulations_without_write,
            "not_evaluable_simulation_count": not_evaluable_simulation_count,
            "simulations_without_usable_trace": simulations_without_usable_trace,
            "fail_count": fail_count,
            "not_evaluable_count": not_evaluable_count,
            "benchmark_reward_used_as_integrity_oracle": False,
        },
        "scope": "tau2_benchmark_artifact_postwrite_audit_not_production_data_integrity_proof",
    }
