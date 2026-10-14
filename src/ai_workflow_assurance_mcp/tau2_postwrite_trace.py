"""Trace integrity and catalog-conformance audit for Tau2 post-write trajectories."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ai_workflow_assurance_mcp.tau2_postwrite_catalog import (
    _field,
    audit_tau2_order_items_against_catalog,
)


def _trace_messages(trajectory: Any) -> list[Any] | None:
    if isinstance(trajectory, (list, tuple)):
        return list(trajectory)
    return None


def _trace_tool_calls(message: Any) -> list[Any]:
    calls = _field(message, "tool_calls", []) or []
    return list(calls) if isinstance(calls, (list, tuple)) else []


def _trace_messages_are_well_formed(messages: list[Any] | None) -> bool:
    """Reject malformed trace records instead of silently ignoring them."""
    if messages is None:
        return False

    for message in messages:
        role = _field(message, "role")
        if not isinstance(role, str) or not role.strip():
            return False

        raw_calls = _field(message, "tool_calls", None)
        if raw_calls is not None:
            if not isinstance(raw_calls, (list, tuple)):
                return False
            for call in raw_calls:
                call_id = _field(call, "id")
                name = _field(call, "name")
                arguments = _field(call, "arguments", {})
                if (
                    not isinstance(call_id, str)
                    or not call_id
                    or not isinstance(name, str)
                    or not name
                    or not isinstance(arguments, Mapping)
                ):
                    return False

        if role == "tool":
            result_id = _field(message, "id")
            if (
                not isinstance(result_id, str)
                or not result_id
                or _field(message, "content", None) is None
            ):
                return False

    return True


def _trace_ambiguous_correlation_ids(messages: list[Any]) -> set[str]:
    """Return IDs that cannot safely correlate calls with results.

    Tau2 traces are expected to use one unique ID per tool call and one result per
    call. If either side repeats an ID, a later result could be attributed to the
    wrong call (or reused for multiple calls). Treat every occurrence of that ID as
    unavailable evidence instead of guessing which call a result belongs to.
    """
    call_counts: dict[str, int] = {}
    result_counts: dict[str, int] = {}
    for message in messages:
        for call in _trace_tool_calls(message):
            call_id = _field(call, "id")
            if isinstance(call_id, str) and call_id:
                call_counts[call_id] = call_counts.get(call_id, 0) + 1
        if _field(message, "role") == "tool":
            result_id = _field(message, "id")
            if isinstance(result_id, str) and result_id:
                result_counts[result_id] = result_counts.get(result_id, 0) + 1

    return {
        call_id
        for call_id, count in call_counts.items()
        if count != 1 or result_counts.get(call_id, 0) > 1
    } | {
        result_id
        for result_id, count in result_counts.items()
        if count != 1 or call_counts.get(result_id, 0) > 1
    }


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
    if not _trace_messages_are_well_formed(messages):
        return _trace_not_evaluable(
            order_id,
            "trajectory_messages_are_well_formed",
            "Every message must have a role; tool calls need a name, ID, and mapping "
            "arguments; tool results need a matching-call ID and content.",
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

    ambiguous_correlation_ids = _trace_ambiguous_correlation_ids(messages)
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
            if call_id not in ambiguous_correlation_ids:
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
            result_message = (
                next(
                    (
                        candidate
                        for candidate in messages[message_index + 1 :]
                        if _field(candidate, "role") == "tool"
                        and _field(candidate, "id") == call_id
                    ),
                    None,
                )
                if call_id not in ambiguous_correlation_ids
                else None
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
            if (
                isinstance(call_id, str)
                and call_id
                and call_id not in ambiguous_correlation_ids
            ):
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
