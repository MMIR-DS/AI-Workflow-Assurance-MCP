"""Replay one saved tau2 retail write and verify the database state independently.

This script is run inside a pinned tau2-bench checkout. It intentionally ignores the
return value of the write tool and re-reads the order from RetailDB after the call.
No model or user-simulator calls are made.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from ai_workflow_assurance_mcp.tau2_prewrite import TAU2_WRITE_TOOLS

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
WRITE_TOOLS = TAU2_WRITE_TOOLS


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


def _hash(value: Any) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def other_database_entities_unchanged(
    snapshot_before: dict[str, Any],
    snapshot_after: dict[str, Any],
    target_order_id: str,
) -> bool:
    """Return False for missing entities, added/deleted orders, or collateral mutations."""
    expected_roots = {"orders", "products", "users"}
    if set(snapshot_before) != expected_roots or set(snapshot_after) != expected_roots:
        return False
    before_orders = snapshot_before.get("orders")
    after_orders = snapshot_after.get("orders")
    if not isinstance(before_orders, dict) or not isinstance(after_orders, dict):
        return False
    if target_order_id not in before_orders or target_order_id not in after_orders:
        return False
    before_unrelated_orders = {
        key: value for key, value in before_orders.items() if key != target_order_id
    }
    after_unrelated_orders = {
        key: value for key, value in after_orders.items() if key != target_order_id
    }
    return bool(
        snapshot_before["products"] == snapshot_after["products"]
        and snapshot_before["users"] == snapshot_after["users"]
        and before_unrelated_orders == after_unrelated_orders
    )


def evaluate_snapshot_evidence(
    *,
    recorded_before: dict[str, Any],
    recorded_after: dict[str, Any],
    db_before: dict[str, Any],
    db_after: dict[str, Any],
    args: dict[str, Any],
    products: dict[str, dict[str, Any]],
    valid_payment_method_ids: set[str],
    source_commit_matches_trace: bool,
    write_execution_succeeded: bool,
    other_database_entities_unchanged: bool,
) -> dict[str, Any]:
    """Pure comparison logic, separately testable without installing tau2-bench."""
    order_id = str(args.get("order_id", ""))
    payment_id = str(args.get("payment_method_id", ""))
    old_ids = args.get("item_ids") if isinstance(args.get("item_ids"), list) else []
    new_ids = args.get("new_item_ids") if isinstance(args.get("new_item_ids"), list) else []

    profile_and_original_payment = payment_id in valid_payment_method_ids and any(
        isinstance(item, dict)
        and item.get("transaction_type") == "payment"
        and str(item.get("payment_method_id")) == payment_id
        for item in recorded_before.get("payment_history", [])
    )

    computed_delta: Decimal | None = None
    old_items = {
        str(item.get("item_id")): item
        for item in db_before.get("items", [])
        if isinstance(item, dict)
    }
    if old_ids and len(old_ids) == len(new_ids):
        delta = Decimal("0.00")
        valid_prices = True
        for old_id, new_id in zip(old_ids, new_ids, strict=True):
            old_item = old_items.get(str(old_id))
            product = products.get(str(old_item.get("product_id"))) if old_item else None
            variants = product.get("variants") if isinstance(product, dict) else None
            variant = variants.get(str(new_id)) if isinstance(variants, dict) else None
            old_price = _money(old_item.get("price")) if old_item else None
            new_price = _money(variant.get("price")) if isinstance(variant, dict) else None
            available = isinstance(variant, dict) and variant.get("available") is True
            if old_price is None or new_price is None or not available:
                valid_prices = False
                break
            delta += new_price - old_price
        if valid_prices:
            computed_delta = delta.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    unrelated_fields_unchanged = bool(
        set(db_before) == ORDER_KEYS
        and set(db_after) == ORDER_KEYS
        and all(db_before.get(key) == db_after.get(key) for key in ORDER_KEYS - MUTABLE_FIELDS)
    )
    transition_matches_request = bool(
        set(db_before) == ORDER_KEYS
        and set(db_after) == ORDER_KEYS
        and str(db_before.get("order_id")) == order_id == str(db_after.get("order_id"))
        and db_before.get("status") == "delivered"
        and db_after.get("status") == "exchange requested"
        and Counter(map(str, db_after.get("exchange_items") or [])) == Counter(map(str, old_ids))
        and Counter(map(str, db_after.get("exchange_new_items") or [])) == Counter(map(str, new_ids))
        and str(db_after.get("exchange_payment_method_id")) == payment_id
        and computed_delta is not None
        and _money(db_after.get("exchange_price_difference")) == computed_delta
    )

    checks = {
        "source_code_commit_matches_trace": bool(source_commit_matches_trace),
        "pre_state_matches_recorded_order_read": db_before == recorded_before,
        "write_execution_succeeded": bool(write_execution_succeeded),
        "no_other_database_entities_mutated": bool(other_database_entities_unchanged),
        "independent_db_state_matches_recorded_exchange_response": db_after == recorded_after,
        "replay_db_payment_profile_and_original_transaction_match": profile_and_original_payment,
        "unrelated_order_fields_unchanged_in_database": unrelated_fields_unchanged,
        "database_price_recalculation_matches_post_state": bool(
            computed_delta is not None
            and _money(db_after.get("exchange_price_difference")) == computed_delta
        ),
        "database_transition_matches_write_request": transition_matches_request,
    }
    return {
        "decision": "GO" if all(checks.values()) else "NO_GO",
        "checks": checks,
        "summary": {
            "passed_checks": sum(checks.values()),
            "total_checks": len(checks),
            "computed_price_difference": str(computed_delta) if computed_delta is not None else None,
            "order_before_sha256": _hash(db_before),
            "order_after_sha256": _hash(db_after),
            "recorded_before_sha256": _hash(recorded_before),
            "recorded_after_sha256": _hash(recorded_after),
        },
    }


def _find_trace_evidence(
    results: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], int]:
    simulations = results.get("simulations")
    if not isinstance(simulations, list) or len(simulations) != 1:
        raise ValueError("Expected exactly one recorded tau2 simulation.")
    messages = [m for m in simulations[0].get("messages", []) if isinstance(m, dict)]
    calls: list[dict[str, Any]] = []
    result_by_id: dict[str, dict[str, Any]] = {
        str(m.get("id")): m for m in messages
        if m.get("role") == "tool" and m.get("id") is not None
    }
    for index, message in enumerate(messages):
        if message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls") or []:
            if isinstance(call, dict):
                calls.append({
                    "index": index,
                    "name": str(call.get("name", "")),
                    "id": str(call.get("id", "")),
                    "arguments": _args(call),
                })
    exchanges = [call for call in calls if call["name"] == "exchange_delivered_order_items"]
    if len(exchanges) != 1:
        raise ValueError(f"Expected exactly one exchange write; found {len(exchanges)}.")
    exchange = exchanges[0]
    order_id = str(exchange["arguments"].get("order_id", ""))
    pre_reads = [
        call for call in calls
        if call["name"] == "get_order_details"
        and call["index"] < exchange["index"]
        and str(call["arguments"].get("order_id", "")) == order_id
    ]
    if len(pre_reads) != 1:
        raise ValueError(f"Expected exactly one pre-write order read for {order_id}; found {len(pre_reads)}.")
    before_message = result_by_id.get(pre_reads[0]["id"])
    after_message = result_by_id.get(exchange["id"])
    if before_message is None or after_message is None:
        raise ValueError("Pre-write or exchange tool response is missing.")
    recorded_before = _payload(before_message)
    recorded_after = _payload(after_message)
    if not isinstance(recorded_before, dict) or not isinstance(recorded_after, dict):
        raise ValueError("Recorded before/after tool payloads must be JSON objects.")
    write_count = sum(call["name"] in WRITE_TOOLS for call in calls)
    return simulations[0], exchange, recorded_before, recorded_after, result_by_id, write_count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-commit", required=True)
    args_cli = parser.parse_args()
    results = json.loads(args_cli.results.read_text(encoding="utf-8"))
    sim, exchange, recorded_before, recorded_after, _, write_count = _find_trace_evidence(results)
    recorded_commit = str((results.get("info") or {}).get("git_commit") or "")
    exchange_args = exchange["arguments"]
    order_id = str(exchange_args.get("order_id", ""))

    from tau2.domains.retail.data_model import RetailDB
    from tau2.domains.retail.tools import RetailTools
    from tau2.domains.retail.utils import RETAIL_DB_PATH

    db = RetailDB.load(RETAIL_DB_PATH)
    if order_id not in db.orders:
        raise ValueError(f"Order {order_id} is missing from the loaded RetailDB.")
    tools = RetailTools(db)

    # This is a direct state read from RetailDB, not get_order_details' recorded response.
    database_snapshot_before = db.model_dump(mode="json", exclude_none=False)
    db_before = database_snapshot_before["orders"][order_id]
    source_commit_matches = bool(recorded_commit and recorded_commit == args_cli.source_commit)
    payment_ids: set[str] = set()
    user_id = str(db_before.get("user_id", ""))
    if user_id in db.users:
        payment_ids = {str(value) for value in db.users[user_id].payment_methods.keys()}

    write_execution_succeeded = False
    execution_error = None
    if (
        write_count == 1
        and source_commit_matches
        and db_before == recorded_before
    ):
        try:
            # Deliberately discard the operation's return value. AWA observes the DB object itself.
            tools.exchange_delivered_order_items(**exchange_args)
            write_execution_succeeded = True
        except Exception as exc:  # a failed replay must be represented as NO_GO
            execution_error = f"{type(exc).__name__}: {exc}"

    database_snapshot_after = db.model_dump(mode="json", exclude_none=False)
    db_after = database_snapshot_after["orders"][order_id]
    no_collateral_mutations = other_database_entities_unchanged(
        database_snapshot_before, database_snapshot_after, order_id
    )
    product_payloads = database_snapshot_before["products"]
    evaluated = evaluate_snapshot_evidence(
        recorded_before=recorded_before,
        recorded_after=recorded_after,
        db_before=db_before,
        db_after=db_after,
        args=exchange_args,
        products=product_payloads,
        valid_payment_method_ids=payment_ids,
        source_commit_matches_trace=source_commit_matches,
        write_execution_succeeded=write_execution_succeeded,
        other_database_entities_unchanged=no_collateral_mutations,
    )
    # Built-in negative control: corrupt a copy of the recorded response and ensure the
    # database comparison would reject it. This does not mutate the trace on disk.
    tampered = copy.deepcopy(recorded_after)
    before_status = tampered.get("status")
    tampered["status"] = "__AWA_TAMPER_PROBE__" if before_status != "__AWA_TAMPER_PROBE__" else "__AWA_TAMPER_PROBE_2__"
    tamper_probe_detected = db_after != tampered
    evaluated["checks"]["tamper_probe_is_detected"] = tamper_probe_detected
    evaluated["summary"]["passed_checks"] = sum(evaluated["checks"].values())
    evaluated["summary"]["total_checks"] = len(evaluated["checks"])
    if not all(evaluated["checks"].values()):
        evaluated["decision"] = "NO_GO"
    report = {
        "schema_version": "1.0.0",
        "verification_type": "pinned_tau2_retail_database_replay",
        "simulation_task_id": sim.get("task_id"),
        "order_id": order_id,
        "source": {
            "trace_commit": recorded_commit,
            "checked_out_commit": args_cli.source_commit,
            "database_path": str(RETAIL_DB_PATH),
            "database_reader": "RetailDB.orders[order_id].model_dump(mode='json')",
        },
        "database_evidence": {
            "before": db_before,
            "after": db_after,
            "full_database_before_sha256": _hash(database_snapshot_before),
            "full_database_after_sha256": _hash(database_snapshot_after),
            "other_database_entities_unchanged": no_collateral_mutations,
            "recorded_before": recorded_before,
            "recorded_after": recorded_after,
            "write_count_in_trace": write_count,
            "write_execution_error": execution_error,
            "tool_return_value_used_for_decision": False,
            "tamper_probe": {
                "mutated_field": "status",
                "detected": tamper_probe_detected,
            },
        },
        **evaluated,
    }
    args_cli.output.parent.mkdir(parents=True, exist_ok=True)
    args_cli.output.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "decision": report["decision"],
        "passed_checks": report["summary"]["passed_checks"],
        "total_checks": report["summary"]["total_checks"],
        "order_id": order_id,
        "computed_price_difference": report["summary"]["computed_price_difference"],
        "checks": report["checks"],
        "write_execution_error": execution_error,
    }, indent=2))
    return 0 if report["decision"] == "GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
