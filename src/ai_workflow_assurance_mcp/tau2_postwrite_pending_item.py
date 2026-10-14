"""Runtime audit for a single pending-order item modification."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ai_workflow_assurance_mcp.tau2_postwrite_catalog import (
    _field,
    audit_tau2_order_items_against_catalog,
)
from ai_workflow_assurance_mcp.tau2_postwrite_trace import (
    _json_object,
    _trace_messages,
    _trace_messages_are_well_formed,
    _trace_tool_calls,
)


def audit_tau2_single_pending_item_write_response(
    trajectory: Any,
    tool_call: Any,
    tool_result: Any,
) -> dict[str, Any]:
    """Audit one executed pending-item replacement against its post-write catalog state.

    This intentionally supports exactly one old/new item pair. It validates the
    replaced row against the latest catalog read and checks that all non-target
    order rows are unchanged. The function observes a write response; it cannot
    roll back a write that has already executed.
    """
    messages = _trace_messages(trajectory)
    if not _trace_messages_are_well_formed(messages):
        return _single_pending_item_audit_result(
            "NOT_EVALUABLE", "trajectory_messages_are_well_formed",
            "The pre-write trajectory is missing or malformed.",
        )
    arguments = _field(tool_call, "arguments", {})
    if not isinstance(arguments, Mapping):
        return _single_pending_item_audit_result(
            "NOT_EVALUABLE", "write_arguments_valid",
            "The executed tool call has no valid arguments mapping.",
        )

    order_id = arguments.get("order_id")
    old_ids = arguments.get("item_ids")
    new_ids = arguments.get("new_item_ids")
    if not (
        isinstance(order_id, str) and order_id
        and isinstance(old_ids, list) and len(old_ids) == 1
        and isinstance(new_ids, list) and len(new_ids) == 1
        and isinstance(old_ids[0], str) and old_ids[0]
        and isinstance(new_ids[0], str) and new_ids[0]
        and old_ids[0] != new_ids[0]
    ):
        return _single_pending_item_audit_result(
            "NOT_EVALUABLE", "single_item_action_valid",
            "Expected exactly one distinct old/new item ID pair.",
        )
    if _field(tool_result, "error", False) is True:
        return _single_pending_item_audit_result(
            "NOT_EVALUABLE", "successful_write_result_available",
            "The environment returned a tool error; no successful post-write snapshot is available.",
        )

    order_after = _json_object(_field(tool_result, "content"))
    if not isinstance(order_after, Mapping):
        return _single_pending_item_audit_result(
            "NOT_EVALUABLE", "postwrite_order_snapshot_available",
            "The successful write response is not a JSON order snapshot.",
        )
    if order_after.get("order_id") != order_id:
        return _single_pending_item_audit_result(
            "FAIL", "postwrite_order_matches_target",
            "The returned post-write order does not match the requested order ID.",
        )
    after_items = order_after.get("items")
    if not isinstance(after_items, list) or not all(
        isinstance(item, Mapping) and isinstance(item.get("item_id"), str) and item.get("item_id")
        for item in after_items
    ):
        return _single_pending_item_audit_result(
            "NOT_EVALUABLE", "postwrite_order_items_well_formed",
            "The post-write order items are missing or malformed.",
        )

    def latest_snapshot(tool_name: str, argument_name: str, value: str) -> Mapping[str, Any] | None:
        matching_calls: list[tuple[int, Any]] = []
        all_call_ids: list[str] = []
        for index, message in enumerate(messages):
            for candidate in _trace_tool_calls(message):
                candidate_id = _field(candidate, "id")
                if isinstance(candidate_id, str) and candidate_id:
                    all_call_ids.append(candidate_id)
                candidate_args = _field(candidate, "arguments", {})
                if (
                    _field(candidate, "name") == tool_name
                    and isinstance(candidate_args, Mapping)
                    and candidate_args.get(argument_name) == value
                ):
                    matching_calls.append((index, candidate))
        if not matching_calls:
            return None
        _, latest_call = matching_calls[-1]
        call_id = _field(latest_call, "id")
        if not isinstance(call_id, str) or not call_id or all_call_ids.count(call_id) != 1:
            return None
        result_messages = [
            message for message in messages
            if _field(message, "role") == "tool"
            and str(_field(message, "id", "")) == call_id
        ]
        if len(result_messages) != 1 or _field(result_messages[0], "error", False) is True:
            return None
        return _json_object(_field(result_messages[0], "content"))

    order_before = latest_snapshot("get_order_details", "order_id", order_id)
    if not isinstance(order_before, Mapping) or order_before.get("order_id") != order_id:
        return _single_pending_item_audit_result(
            "NOT_EVALUABLE", "prewrite_order_snapshot_available",
            "The latest matching order read is missing, malformed, or ambiguous.",
        )
    before_items = order_before.get("items")
    if not isinstance(before_items, list) or not all(
        isinstance(item, Mapping) and isinstance(item.get("item_id"), str) and item.get("item_id")
        for item in before_items
    ):
        return _single_pending_item_audit_result(
            "NOT_EVALUABLE", "prewrite_order_items_well_formed",
            "The pre-write order items are missing or malformed.",
        )

    old_id, new_id = old_ids[0], new_ids[0]
    old_before = [item for item in before_items if item.get("item_id") == old_id]
    new_before = [item for item in before_items if item.get("item_id") == new_id]
    new_after = [item for item in after_items if item.get("item_id") == new_id]
    old_after = [item for item in after_items if item.get("item_id") == old_id]
    if len(old_before) != 1 or new_before:
        return _single_pending_item_audit_result(
            "NOT_EVALUABLE", "prewrite_item_identity_unambiguous",
            "The old item must occur exactly once and the replacement must not already occur in the pre-write order.",
        )
    if len(new_after) != 1 or old_after:
        return _single_pending_item_audit_result(
            "FAIL", "single_item_replacement_observed",
            "The post-write order must contain the replacement exactly once and no longer contain the old item.",
        )

    def canonical_rows(rows: list[Any]) -> list[str] | None:
        try:
            return sorted(
                json.dumps(dict(item), sort_keys=True, separators=(",", ":"), allow_nan=False)
                for item in rows
            )
        except (TypeError, ValueError):
            return None

    before_untouched = [item for item in before_items if item.get("item_id") != old_id]
    after_untouched = [item for item in after_items if item.get("item_id") != new_id]
    before_canonical = canonical_rows(before_untouched)
    after_canonical = canonical_rows(after_untouched)
    if before_canonical is None or after_canonical is None:
        return _single_pending_item_audit_result(
            "NOT_EVALUABLE", "non_target_rows_comparable",
            "Unmodified order rows could not be canonicalized for comparison.",
        )
    if before_canonical != after_canonical:
        return _single_pending_item_audit_result(
            "FAIL", "non_target_order_rows_unchanged",
            "One or more non-target order rows changed during the single-item write.",
        )

    new_row = new_after[0]
    product_id = new_row.get("product_id")
    if not isinstance(product_id, str) or not product_id:
        return _single_pending_item_audit_result(
            "NOT_EVALUABLE", "replacement_product_id_available",
            "The replacement order row has no product_id.",
        )
    catalog = latest_snapshot("get_product_details", "product_id", product_id)
    if not isinstance(catalog, Mapping) or catalog.get("product_id") != product_id:
        return _single_pending_item_audit_result(
            "NOT_EVALUABLE", "latest_replacement_catalog_available",
            "The latest matching product catalog read is missing, malformed, or ambiguous.",
        )

    catalog_audit = audit_tau2_order_items_against_catalog(
        {"order_id": order_id, "items": [dict(new_row)]},
        [catalog],
    )
    if catalog_audit.get("decision") != "PASS":
        return {
            **catalog_audit,
            "decision": catalog_audit.get("decision", "NOT_EVALUABLE"),
            "blocking_checks": list(dict.fromkeys([
                "replacement_matches_catalog",
                *catalog_audit.get("blocking_checks", []),
            ])),
            "checked": {
                "single_item_replacement_observed": "PASS",
                "non_target_order_rows_unchanged": "PASS",
                **catalog_audit.get("checked", {}),
            },
            "scope": "single_pending_item_runtime_postwrite_audit_not_rollback",
        }

    return {
        "decision": "PASS",
        "checked": {
            "single_item_replacement_observed": "PASS",
            "non_target_order_rows_unchanged": "PASS",
            "replacement_matches_catalog": "PASS",
            **catalog_audit.get("checked", {}),
        },
        "blocking_checks": [],
        "violations": [],
        "not_evaluable": [],
        "evidence_summary": {
            "order_id": order_id,
            "old_item_id": old_id,
            "new_item_id": new_id,
            "prewrite_item_count": len(before_items),
            "postwrite_item_count": len(after_items),
            "catalog_audit": catalog_audit.get("evidence_summary", {}),
        },
        "scope": "single_pending_item_runtime_postwrite_audit_not_rollback",
    }


def _single_pending_item_audit_result(
    decision: str,
    check: str,
    detail: str,
) -> dict[str, Any]:
    """Build a small fail-closed result for an unevaluable or invalid single-item write."""
    record = {"check": check, "detail": detail}
    return {
        "decision": decision,
        "checked": {check: decision},
        "blocking_checks": [] if decision == "PASS" else [check],
        "violations": [record] if decision == "FAIL" else [],
        "not_evaluable": [record] if decision == "NOT_EVALUABLE" else [],
        "evidence_summary": {
            "violation_count": 1 if decision == "FAIL" else 0,
            "not_evaluable_count": 1 if decision == "NOT_EVALUABLE" else 0,
        },
        "scope": "single_pending_item_runtime_postwrite_audit_not_rollback",
    }
