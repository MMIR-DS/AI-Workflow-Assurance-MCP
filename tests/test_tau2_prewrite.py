from __future__ import annotations

import json
from pathlib import Path

from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_prewrite

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "tau2_task0_trace_minimal.json"


def _trajectory_and_call() -> tuple[list[dict], dict]:
    results = json.loads(FIXTURE.read_text(encoding="utf-8"))
    messages = results["simulations"][0]["messages"]
    # The current tool call is present in the trajectory; its result is not yet present.
    messages = messages[:19]
    call = messages[-1]["tool_calls"][0]
    return messages, call


def _tool_result_json(trajectory: list[dict], call_id: str) -> dict:
    message = next(
        item for item in trajectory
        if item.get("role") == "tool" and item.get("id") == call_id
    )
    return json.loads(message["content"])


def _replace_tool_result_json(trajectory: list[dict], call_id: str, payload: dict) -> None:
    message = next(
        item for item in trajectory
        if item.get("role") == "tool" and item.get("id") == call_id
    )
    message["content"] = json.dumps(payload)


def _cancel_trajectory_and_call() -> tuple[list[dict], dict]:
    trajectory, _ = _trajectory_and_call()
    order = _tool_result_json(trajectory, "order-read-1")
    order["status"] = "pending"
    _replace_tool_result_json(trajectory, "order-read-1", order)
    call = {
        "id": "cancel-call-001",
        "name": "cancel_pending_order",
        "arguments": {
            "order_id": "#W2378156",
            "reason": "no longer needed",
        },
    }
    trajectory[-1]["tool_calls"] = [call]
    trajectory[16]["content"] = (
        "To cancel order #W2378156 because it is no longer needed, you will receive "
        "a refund of 1819.92 to credit_card_9513926 in 5-7 business days. Please confirm."
    )
    trajectory[17]["content"] = "Yes, I confirm the cancellation and refund as described."
    return trajectory, call


def test_tau2_adapter_blocks_write_when_final_confirmation_omits_order_and_old_items() -> None:
    trajectory, call = _trajectory_and_call()

    result = evaluate_tau2_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert result["allowed"] is False
    assert result["evidence_summary"]["identity_matches_order_owner"] is True
    assert result["evidence_summary"]["assistant_disclosed_exact_order_items_and_payment"] is False
    assert "exact_action_or_payment_method_not_disclosed_to_customer" in result["blocking_checks"]


def test_tau2_adapter_allows_only_after_complete_disclosure_and_affirmative_reply() -> None:
    trajectory, call = _trajectory_and_call()
    trajectory[16]["content"] = (
        "To confirm order #W2378156: exchange old item 1151293680 for 7706410293 "
        "and old item 4983901480 for 7747408585. The total price difference is "
        "a $16.63 refund to credit_card_9513926. Please confirm."
    )
    trajectory[17]["content"] = (
        "Yes, that's correct. Go ahead and use credit_card_9513926 for this exchange."
    )

    result = evaluate_tau2_prewrite(trajectory, call)

    assert result["decision"] == "GO"
    assert result["allowed"] is True
    assert result["evidence_summary"]["assistant_disclosed_exact_order_items_and_payment"] is True
    assert result["evidence_summary"]["user_affirmed_after_disclosure"] is True


def test_tau2_adapter_blocks_negative_reply_even_when_details_were_disclosed() -> None:
    trajectory, call = _trajectory_and_call()
    trajectory[16]["content"] = (
        "To confirm order #W2378156: exchange old item 1151293680 for 7706410293 "
        "and old item 4983901480 for 7747408585. The total price difference is "
        "a $16.63 refund to credit_card_9513926. Please confirm."
    )
    trajectory[17]["content"] = "No, don't go ahead. I need to change the selections."

    result = evaluate_tau2_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert result["evidence_summary"]["user_affirmed_after_disclosure"] is False


def test_tau2_adapter_blocks_affirmative_reply_that_names_another_payment_id() -> None:
    trajectory, call = _trajectory_and_call()
    trajectory[16]["content"] = (
        "To confirm order #W2378156: exchange old item 1151293680 for 7706410293 "
        "and old item 4983901480 for 7747408585. The total price difference is "
        "a $16.63 refund to credit_card_9513926. Please confirm."
    )
    # This is superficially affirmative and does not contain words like "change" or "instead",
    # but it explicitly names a different payment instrument.
    trajectory[17]["content"] = "Yes, use credit_card_1234567."

    result = evaluate_tau2_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert result["allowed"] is False
    assert result["evidence_summary"]["user_affirmed_after_disclosure"] is False


def test_tau2_adapter_blocks_affirmative_reply_that_names_another_order() -> None:
    trajectory, call = _trajectory_and_call()
    trajectory[16]["content"] = (
        "To confirm order #W2378156: exchange old item 1151293680 for 7706410293 "
        "and old item 4983901480 for 7747408585. The total price difference is "
        "a $16.63 refund to credit_card_9513926. Please confirm."
    )
    trajectory[17]["content"] = "Yes, order #W9999999 is correct."

    result = evaluate_tau2_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert result["allowed"] is False
    assert result["evidence_summary"]["user_affirmed_after_disclosure"] is False


def test_tau2_adapter_blocks_affirmative_reply_that_names_an_unknown_item_id() -> None:
    trajectory, call = _trajectory_and_call()
    trajectory[16]["content"] = (
        "To confirm order #W2378156: exchange old item 1151293680 for 7706410293 "
        "and old item 4983901480 for 7747408585. The total price difference is "
        "a $16.63 refund to credit_card_9513926. Please confirm."
    )
    trajectory[17]["content"] = "Yes, exchange item 9999999999."

    result = evaluate_tau2_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert result["allowed"] is False
    assert result["evidence_summary"]["user_affirmed_after_disclosure"] is False


def test_tau2_adapter_blocks_qualified_yes_that_changes_payment_method() -> None:
    trajectory, call = _trajectory_and_call()
    trajectory[16]["content"] = (
        "To confirm order #W2378156: exchange old item 1151293680 for 7706410293 "
        "and old item 4983901480 for 7747408585. The total price difference is "
        "a $16.63 refund to credit_card_9513926. Please confirm."
    )
    trajectory[17]["content"] = (
        "Yes, but use a different payment method instead."
    )

    result = evaluate_tau2_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert result["allowed"] is False
    assert result["evidence_summary"]["user_affirmed_after_disclosure"] is False


def test_tau2_adapter_blocks_when_order_was_written_after_the_snapshot() -> None:
    trajectory, call = _trajectory_and_call()
    trajectory[16]["content"] = (
        "To confirm order #W2378156: exchange old item 1151293680 for 7706410293 "
        "and old item 4983901480 for 7747408585. The total price difference is "
        "a $16.63 refund to credit_card_9513926. Please confirm."
    )
    trajectory[17]["content"] = (
        "Yes, that's correct. Go ahead and use credit_card_9513926 for this exchange."
    )
    # Place a successful write immediately after the order-read result, before confirmation.
    read_call_index = next(
        index for index, message in enumerate(trajectory)
        if any(
            tool.get("name") == "get_order_details"
            and tool.get("arguments", {}).get("order_id") == "#W2378156"
            for tool in message.get("tool_calls", [])
        )
    )
    read_call_id = trajectory[read_call_index]["tool_calls"][0]["id"]
    read_result_index = next(
        index for index, message in enumerate(trajectory)
        if message.get("role") == "tool" and message.get("id") == read_call_id
    )
    trajectory.insert(read_result_index + 1, {
        "role": "assistant",
        "tool_calls": [{
            "id": "prior-write-001",
            "name": "modify_pending_order_address",
            "arguments": {"order_id": "#W2378156", "city": "Updated City"},
        }],
    })
    trajectory.insert(read_result_index + 2, {
        "role": "tool",
        "id": "prior-write-001",
        "content": "{\"status\": \"ok\"}",
    })

    result = evaluate_tau2_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert result["allowed"] is False
    assert "order_snapshot_stale_after_prior_write_attempt" in result["blocking_checks"]
    assert result["evidence_summary"]["order_snapshot_fresh"] is False


def test_tau2_adapter_fails_closed_without_matching_identity_lookup() -> None:
    trajectory, call = _trajectory_and_call()
    trajectory[:] = [
        message for message in trajectory
        if not (
            message.get("role") == "assistant"
            and any(
                tool.get("name") in {"find_user_id_by_name_zip", "find_user_id_by_email"}
                for tool in message.get("tool_calls", [])
            )
        )
    ]

    result = evaluate_tau2_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert "identity_or_order_ownership_not_verified" in result["blocking_checks"]


def test_tau2_adapter_fails_closed_without_order_read_evidence() -> None:
    trajectory, call = _trajectory_and_call()
    trajectory[:] = [
        message for message in trajectory
        if not (
            message.get("role") == "assistant"
            and any(tool.get("name") == "get_order_details" for tool in message.get("tool_calls", []))
        )
    ]

    result = evaluate_tau2_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert "order_not_confirmed_delivered" in result["blocking_checks"]


def test_tau2_adapter_recovers_after_blocked_attempt_and_fresh_confirmation() -> None:
    trajectory, first_call = _trajectory_and_call()
    retry_call = {
        "id": "retry-call-001",
        "name": first_call["name"],
        "arguments": first_call["arguments"],
    }

    # Model the actual recovery sequence: first attempt was blocked, the assistant
    # clarifies every material detail, the user confirms, then the same write is retried.
    trajectory.extend([
        {
            "role": "tool",
            "id": first_call["id"],
            "content": json.dumps({
                "error": "AWA_PREWRITE_NO_GO: missing complete customer confirmation"
            }),
        },
        {
            "role": "assistant",
            "content": (
                "To confirm order #W2378156: exchange old item 1151293680 for 7706410293 "
                "and old item 4983901480 for 7747408585. The total price difference is "
                "a $16.63 refund to credit_card_9513926. Please confirm."
            ),
        },
        {
            "role": "user",
            "content": "Yes, that's correct. Please proceed with this exchange.",
        },
        {
            "role": "assistant",
            "tool_calls": [retry_call],
        },
    ])

    result = evaluate_tau2_prewrite(trajectory, retry_call)

    assert result["decision"] == "GO"
    assert result["allowed"] is True
    assert result["evidence_summary"]["identity_matches_order_owner"] is True
    assert result["evidence_summary"]["assistant_disclosed_exact_order_items_and_payment"] is True
    assert result["evidence_summary"]["user_affirmed_after_disclosure"] is True


def test_tau2_adapter_blocks_order_snapshot_for_a_different_order_id() -> None:
    trajectory, call = _trajectory_and_call()
    snapshot = _tool_result_json(trajectory, "order-read-1")
    snapshot["order_id"] = "#W9999999"
    _replace_tool_result_json(trajectory, "order-read-1", snapshot)

    result = evaluate_tau2_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert "order_snapshot_matches_requested_order" in result["blocking_checks"]
    assert result["evidence_summary"]["order_snapshot_matches_requested_order"] is False


def test_tau2_adapter_blocks_old_item_not_present_in_order() -> None:
    trajectory, call = _trajectory_and_call()
    call["arguments"]["item_ids"] = ["9999999999", "4983901480"]
    trajectory[16]["content"] = (
        "To confirm order #W2378156: exchange old item 9999999999 for 7706410293 "
        "and old item 4983901480 for 7747408585. The total price difference is "
        "a $16.63 refund to credit_card_9513926. Please confirm."
    )
    trajectory[17]["content"] = (
        "Yes, exchange item 9999999999 and item 4983901480 for 7706410293 and "
        "7747408585 using credit_card_9513926."
    )

    result = evaluate_tau2_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert "old_item_multiplicity_does_not_exceed_order_quantity" in result["blocking_checks"]


def test_tau2_adapter_blocks_payment_method_not_in_order_history() -> None:
    trajectory, call = _trajectory_and_call()
    call["arguments"]["payment_method_id"] = "credit_card_1234567"
    trajectory[16]["content"] = (
        "To confirm order #W2378156: exchange old item 1151293680 for 7706410293 "
        "and old item 4983901480 for 7747408585. The total price difference is "
        "a $16.63 refund to credit_card_1234567. Please confirm."
    )
    trajectory[17]["content"] = (
        "Yes, that's correct. Go ahead and use credit_card_1234567 for this exchange."
    )

    result = evaluate_tau2_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert "payment_method_belongs_to_order" in result["blocking_checks"]


def test_tau2_adapter_blocks_new_variant_not_verified_available() -> None:
    trajectory, call = _trajectory_and_call()
    product = _tool_result_json(trajectory, "keyboard-product-1")
    product["variants"]["7706410293"]["available"] = False
    _replace_tool_result_json(trajectory, "keyboard-product-1", product)

    result = evaluate_tau2_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert "new_items_are_verified_available_variants" in result["blocking_checks"]


def test_tau2_adapter_does_not_rely_on_stale_available_variant_snapshot() -> None:
    trajectory, call = _trajectory_and_call()
    latest_product = _tool_result_json(trajectory, "keyboard-product-1")
    latest_product["variants"]["7706410293"]["available"] = False
    trajectory.insert(-1, {
        "role": "assistant",
        "tool_calls": [{
            "id": "keyboard-product-2",
            "name": "get_product_details",
            "arguments": {"product_id": "1656367028"},
        }],
    })
    trajectory.insert(-1, {
        "role": "tool",
        "id": "keyboard-product-2",
        "content": json.dumps(latest_product),
    })

    result = evaluate_tau2_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert "new_items_are_verified_available_variants" in result["blocking_checks"]


def test_tau2_adapter_blocks_exchange_without_exact_price_difference_disclosure() -> None:
    trajectory, call = _trajectory_and_call()
    trajectory[16]["content"] = (
        "To confirm order #W2378156: exchange old item 1151293680 for 7706410293 "
        "and old item 4983901480 for 7747408585. Use payment method "
        "credit_card_9513926. Please confirm."
    )
    trajectory[17]["content"] = (
        "Yes, that's correct. Go ahead and use credit_card_9513926 for this exchange."
    )

    result = evaluate_tau2_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert "exact_price_difference_and_direction_disclosed" in result["blocking_checks"]


def test_tau2_adapter_blocks_exchange_to_variant_of_another_product() -> None:
    trajectory, call = _trajectory_and_call()
    call["arguments"]["new_item_ids"] = ["7706410293", "6342039236"]
    trajectory[16]["content"] = (
        "To confirm order #W2378156: exchange old item 1151293680 for 7706410293 "
        "and old item 4983901480 for 6342039236. The total price difference is "
        "a $20.73 refund to credit_card_9513926. Please confirm."
    )
    trajectory[17]["content"] = (
        "Yes, exchange both items as described and use credit_card_9513926."
    )

    result = evaluate_tau2_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert "new_items_match_the_corresponding_old_product_types" in result["blocking_checks"]


def test_tau2_adapter_allows_duplicate_old_item_ids_only_when_order_quantity_supports_them() -> None:
    trajectory, call = _trajectory_and_call()
    order = _tool_result_json(trajectory, "order-read-1")
    keyboard = next(item for item in order["items"] if item["item_id"] == "1151293680")
    order["items"].append(dict(keyboard))
    _replace_tool_result_json(trajectory, "order-read-1", order)
    call["arguments"]["item_ids"] = ["1151293680", "1151293680"]
    call["arguments"]["new_item_ids"] = ["7706410293", "6342039236"]
    trajectory[16]["content"] = (
        "To confirm order #W2378156: exchange item 1151293680 twice for "
        "7706410293 and 6342039236. The total price difference is a $30.59 "
        "refund to credit_card_9513926. Please confirm."
    )
    trajectory[17]["content"] = (
        "Yes, exchange both units as described and use credit_card_9513926."
    )

    result = evaluate_tau2_prewrite(trajectory, call)

    assert result["decision"] == "GO"
    assert result["allowed"] is True
    assert result["evidence_summary"]["old_item_multiplicity_does_not_exceed_order_quantity"] is True


def test_tau2_adapter_blocks_replay_of_confirmation_after_no_go() -> None:
    trajectory, first_call = _trajectory_and_call()
    trajectory[16]["content"] = (
        "To confirm order #W2378156: exchange old item 1151293680 for 7706410293 "
        "and old item 4983901480 for 7747408585. The total price difference is "
        "a $16.63 refund to credit_card_9513926. Please confirm."
    )
    trajectory[17]["content"] = (
        "Yes, that's correct. Go ahead and use credit_card_9513926 for this exchange."
    )
    trajectory.append({
        "role": "tool",
        "id": first_call["id"],
        "content": "AWA_PREWRITE_NO_GO: the previous attempt was blocked.",
    })
    retry_call = {
        "id": "retry-with-replayed-confirmation",
        "name": first_call["name"],
        "arguments": dict(first_call["arguments"]),
    }
    trajectory.append({"role": "assistant", "tool_calls": [retry_call]})

    result = evaluate_tau2_prewrite(trajectory, retry_call)

    assert result["decision"] == "NO_GO"
    assert result["allowed"] is False
    assert result["evidence_summary"]["user_reconfirmed_after_latest_blocked_attempt"] is False
    assert "explicit_confirmation_does_not_match_action" in result["blocking_checks"]


def test_tau2_cancel_adapter_allows_pending_order_after_exact_refund_disclosure() -> None:
    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_cancel_prewrite

    trajectory, call = _cancel_trajectory_and_call()

    result = evaluate_tau2_cancel_prewrite(trajectory, call)

    assert result["decision"] == "GO"
    assert result["allowed"] is True
    assert result["evidence_summary"]["refund_total"] == 1819.92
    assert result["evidence_summary"]["identity_and_order_ownership_verified"] is True


def test_tau2_cancel_adapter_blocks_non_pending_order() -> None:
    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_cancel_prewrite

    trajectory, call = _cancel_trajectory_and_call()
    order = _tool_result_json(trajectory, "order-read-1")
    order["status"] = "delivered"
    _replace_tool_result_json(trajectory, "order-read-1", order)

    result = evaluate_tau2_cancel_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert "order_is_pending" in result["blocking_checks"]


def test_tau2_cancel_adapter_blocks_unsupported_reason() -> None:
    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_cancel_prewrite

    trajectory, call = _cancel_trajectory_and_call()
    call["arguments"]["reason"] = "changed my mind"
    trajectory[16]["content"] = (
        "To cancel order #W2378156 because it is changed my mind, you will receive "
        "a refund of 1819.92 to credit_card_9513926 in 5-7 business days. Please confirm."
    )

    result = evaluate_tau2_cancel_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert "cancellation_reason_supported" in result["blocking_checks"]


def test_tau2_cancel_adapter_blocks_missing_refund_timing_disclosure() -> None:
    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_cancel_prewrite

    trajectory, call = _cancel_trajectory_and_call()
    trajectory[16]["content"] = (
        "To cancel order #W2378156 because it is no longer needed, you will receive "
        "a refund to credit_card_9513926. Please confirm."
    )

    result = evaluate_tau2_cancel_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert "exact_cancellation_and_refund_disclosure_valid" in result["blocking_checks"]
