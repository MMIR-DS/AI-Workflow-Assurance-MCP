from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_workflow_assurance_mcp.tau2_prewrite import (
    evaluate_tau2_address_prewrite,
    evaluate_tau2_cancel_prewrite,
    evaluate_tau2_pending_items_prewrite,
    evaluate_tau2_payment_prewrite,
    evaluate_tau2_prewrite,
    evaluate_tau2_return_prewrite,
    evaluate_tau2_user_address_prewrite,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "tau2_task0_trace_minimal.json"


def _trajectory_and_call() -> tuple[list[dict], dict]:
    results = json.loads(FIXTURE.read_text(encoding="utf-8"))
    messages = results["simulations"][0]["messages"]
    # The current tool call is present in the trajectory; its result is not yet present.
    messages = messages[:19]
    call = messages[-1]["tool_calls"][0]
    return messages, call


def _fully_disclosed_exchange_trajectory_and_call() -> tuple[list[dict], dict]:
    trajectory, call = _trajectory_and_call()
    trajectory[14]["content"] = (
        "Item ID 7706410293 is a full-size, clicky keyboard with no backlight. "
        "Item ID 7747408585 is a black Google Assistant-compatible thermostat."
    )
    trajectory[16]["content"] = (
        "To confirm order #W2378156: exchange old item 1151293680 for 7706410293 "
        "and old item 4983901480 for 7747408585. The total price difference is "
        "a $16.63 refund to credit_card_9513926. Please confirm."
    )
    return trajectory, call


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


def _address_trajectory_and_call() -> tuple[list[dict], dict]:
    trajectory, _ = _trajectory_and_call()
    order = _tool_result_json(trajectory, "order-read-1")
    order["status"] = "pending"
    _replace_tool_result_json(trajectory, "order-read-1", order)
    call = {
        "id": "address-call-001",
        "name": "modify_pending_order_address",
        "arguments": {
            "order_id": "#W2378156",
            "address1": "100 Main Street",
            "address2": "Unit 4",
            "city": "Boston",
            "state": "MA",
            "country": "USA",
            "zip": "02108",
        },
    }
    trajectory[-1]["tool_calls"] = [call]
    trajectory[16]["content"] = (
        "To confirm order #W2378156, change the shipping address to 100 Main Street, "
        "Unit 4, Boston, MA, USA, ZIP 02108. Please confirm."
    )
    trajectory[17]["content"] = "Yes, update the shipping address as stated."
    return trajectory, call


def _payment_trajectory_and_call() -> tuple[list[dict], dict]:
    trajectory, _ = _trajectory_and_call()
    order = _tool_result_json(trajectory, "order-read-1")
    order["status"] = "pending"
    _replace_tool_result_json(trajectory, "order-read-1", order)
    owner_id = order["user_id"]
    user_details = {
        "user_id": owner_id,
        "payment_methods": {
            "credit_card_9513926": {
                "id": "credit_card_9513926",
                "source": "credit_card",
                "brand": "visa",
                "last_four": "3926",
            },
            "credit_card_1234567": {
                "id": "credit_card_1234567",
                "source": "credit_card",
                "brand": "visa",
                "last_four": "4567",
            },
        },
    }
    trajectory.insert(16, {
        "role": "assistant",
        "tool_calls": [{
            "id": "user-details-1",
            "name": "get_user_details",
            "arguments": {"user_id": owner_id},
        }],
    })
    trajectory.insert(17, {
        "role": "tool",
        "id": "user-details-1",
        "content": json.dumps(user_details),
    })
    call = {
        "id": "payment-call-001",
        "name": "modify_pending_order_payment",
        "arguments": {
            "order_id": "#W2378156",
            "payment_method_id": "credit_card_1234567",
        },
    }
    trajectory[-1]["tool_calls"] = [call]
    trajectory[18]["content"] = (
        "For order #W2378156, change payment method from credit_card_9513926 to "
        "credit_card_1234567 (credit card, visa ending 4567). Please confirm."
    )
    trajectory[19]["content"] = (
        "Yes, that's correct. Proceed with the payment method described."
    )
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
    trajectory[14]["content"] = (
        "Item ID 7706410293 is a full-size, clicky keyboard with no backlight. "
        "Item ID 7747408585 is a black Google Assistant-compatible thermostat."
    )
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
    assert result["checked"]["assistant_variant_claims_match_catalog"] is True


def test_tau2_adapter_blocks_catalog_option_claim_that_misstates_selected_variant() -> None:
    trajectory, call = _trajectory_and_call()
    call["arguments"]["new_item_ids"] = ["6342039236", "7747408585"]
    trajectory[-1]["tool_calls"] = [call]
    trajectory[14]["content"] = (
        "I found item ID 6342039236, which is a full-size, RGB-backlit, "
        "clicky mechanical keyboard. Item ID 7747408585 is a black, "
        "Google Assistant-compatible thermostat."
    )
    trajectory[15]["content"] = (
        "Yes, I want those exact replacements."
    )
    trajectory[16]["content"] = (
        "To confirm order #W2378156: exchange old item 1151293680 for 6342039236 "
        "and old item 4983901480 for 7747408585. The total price difference is "
        "a $40.88 refund to credit_card_9513926. Please confirm."
    )
    trajectory[17]["content"] = (
        "Yes, I confirm both exchanges and the refund to credit_card_9513926."
    )

    result = evaluate_tau2_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert result["allowed"] is False
    assert result["checked"]["new_items_are_verified_available_variants"] is True
    assert result["checked"]["new_items_match_the_corresponding_old_product_types"] is True
    assert result["checked"]["assistant_variant_claims_match_catalog"] is False
    assert "assistant_variant_claims_match_catalog" in result["blocking_checks"]


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


def test_tau2_adapter_blocks_affirmative_reply_that_names_a_different_gift_card() -> None:
    trajectory, call = _trajectory_and_call()
    trajectory[16]["content"] = (
        "To confirm order #W2378156: exchange old item 1151293680 for 7706410293 "
        "and old item 4983901480 for 7747408585. The total price difference is "
        "a $16.63 refund to credit_card_9513926. Please confirm."
    )
    # No "instead" or other negative language: the conflicting instrument ID alone
    # must be enough to reject the confirmation.
    trajectory[17]["content"] = "Yes, use gift_card_1234567 for this exchange."

    result = evaluate_tau2_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert result["evidence_summary"]["user_affirmed_after_disclosure"] is False


def test_tau2_adapter_blocks_confirmation_for_other_order_number_wording() -> None:
    trajectory, call = _trajectory_and_call()
    trajectory[16]["content"] = (
        "To confirm order #W2378156: exchange old item 1151293680 for 7706410293 "
        "and old item 4983901480 for 7747408585. The total price difference is "
        "a $16.63 refund to credit_card_9513926. Please confirm."
    )
    trajectory[17]["content"] = "Yes, for order number W9999999, proceed with the exchange."

    result = evaluate_tau2_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
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


def test_tau2_adapter_accepts_labeled_pairs_with_prices_between_item_ids() -> None:
    trajectory, call = _trajectory_and_call()
    trajectory[16]["content"] = (
        "To confirm order #W2378156 and exchange these exact items: "
        "1. Old Item: 1151293680 (Mechanical Keyboard, RGB, linear, full size; $272.33). "
        "New Item: 7706410293 (Mechanical Keyboard, no backlight, clicky, full size; $269.16). "
        "2. Old Item: 4983901480 (Smart Thermostat, black, Apple HomeKit; $262.47). "
        "New Item: 7747408585 (Smart Thermostat, black, Google Assistant; $249.01). "
        "The total price difference is -$16.63, a refund of $16.63 to credit_card_9513926. "
        "Please confirm both old-to-new item pairs for this exchange."
    )
    trajectory[17]["content"] = (
        "Yes, I confirm both exchanges and the $16.63 refund to credit_card_9513926."
    )

    result = evaluate_tau2_prewrite(trajectory, call)

    assert result["decision"] == "GO"
    assert result["checked"]["customer_disclosed_item_pairs_match_requested_exchange"] is True
    assert result["checked"]["exact_price_difference_and_direction_disclosed"] is True


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


def test_tau2_adapter_blocks_confirmation_with_swapped_replacement_pairing() -> None:
    trajectory, call = _trajectory_and_call()
    # The tool call pairs old item 115... with 770... and old item 498... with 774...,
    # but the customer-facing disclosure presents the two replacements in reverse.
    trajectory[16]["content"] = (
        "To confirm order #W2378156: exchange old item 1151293680 for 7747408585 "
        "and old item 4983901480 for 7706410293. The total price difference is "
        "a $16.63 refund to credit_card_9513926. Please confirm."
    )
    trajectory[17]["content"] = (
        "Yes, exchange both items as described and use credit_card_9513926."
    )

    result = evaluate_tau2_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert "customer_disclosed_item_pairs_match_requested_exchange" in result["blocking_checks"]
    assert result["evidence_summary"]["assistant_disclosed_exact_order_items_and_payment"] is False


def test_tau2_adapter_blocks_unexpected_item_id_in_confirmation_disclosure() -> None:
    trajectory, call = _trajectory_and_call()
    trajectory[16]["content"] = (
        "To confirm order #W2378156: exchange old item 1151293680 for 7706410293 "
        "and old item 4983901480 for 7747408585. Also item 9999999999 was included. "
        "The total price difference is a $16.63 refund to credit_card_9513926. Please confirm."
    )
    trajectory[17]["content"] = (
        "Yes, exchange both items as described and use credit_card_9513926."
    )

    result = evaluate_tau2_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert "customer_disclosed_item_pairs_match_requested_exchange" in result["blocking_checks"]


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
        "To confirm order #W2378156: exchange item 1151293680 for 7706410293 "
        "and item 1151293680 for 6342039236. The total price difference is a $30.59 "
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
    assert "user_reconfirmed_after_latest_blocked_attempt" in result["blocking_checks"]
    assert "explicit_confirmation_does_not_match_action" not in result["blocking_checks"]


def test_tau2_adapter_blocks_incomplete_reconfirmation_after_no_go() -> None:
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
        "content": "AWA_PREWRITE_NO_GO: the previous write was blocked.",
        "error": True,
    })
    trajectory.append({
        "role": "assistant",
        "content": "To confirm order #W2378156, please proceed with the exchange.",
    })
    trajectory.append({"role": "user", "content": "Yes, I confirm."})
    retry_call = {
        "id": "retry-with-incomplete-disclosure",
        "name": first_call["name"],
        "arguments": dict(first_call["arguments"]),
    }
    trajectory.append({"role": "assistant", "tool_calls": [retry_call]})

    result = evaluate_tau2_prewrite(trajectory, retry_call)

    assert result["decision"] == "NO_GO"
    assert result["evidence_summary"]["user_reconfirmed_after_latest_blocked_attempt"] is True
    assert result["checked"]["complete_customer_facing_exchange_disclosure"] is False
    assert "complete_customer_facing_exchange_disclosure" in result["blocking_checks"]


def test_tau2_adapter_blocks_retry_with_unavailable_variant_after_fresh_confirmation() -> None:
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
        "content": "AWA_PREWRITE_NO_GO: the previous write was blocked.",
        "error": True,
    })

    retry_arguments = dict(first_call["arguments"])
    retry_arguments["new_item_ids"] = ["9025753381", "7747408585"]
    trajectory.append({
        "role": "assistant",
        "content": (
            "To confirm order #W2378156: exchange old item 1151293680 for "
            "9025753381 (a full-size, clicky, RGB-backlit keyboard) and old item "
            "4983901480 for 7747408585 (a black Google Assistant-compatible "
            "thermostat). The total price difference is a $54.21 refund to "
            "credit_card_9513926. Please confirm."
        ),
    })
    trajectory.append({
        "role": "user",
        "content": "Yes, that's correct. Proceed with the exchange as described.",
    })
    retry_call = {
        "id": "retry-with-unavailable-variant",
        "name": first_call["name"],
        "arguments": retry_arguments,
    }
    trajectory.append({"role": "assistant", "tool_calls": [retry_call]})

    result = evaluate_tau2_prewrite(trajectory, retry_call)

    assert result["decision"] == "NO_GO"
    assert result["evidence_summary"]["user_reconfirmed_after_latest_blocked_attempt"] is True
    assert result["checked"]["new_items_are_verified_available_variants"] is False
    assert "new_items_are_verified_available_variants" in result["blocking_checks"]


def test_tau2_cancel_adapter_allows_pending_order_after_exact_refund_disclosure() -> None:
    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_cancel_prewrite

    trajectory, call = _cancel_trajectory_and_call()

    result = evaluate_tau2_cancel_prewrite(trajectory, call)

    assert result["decision"] == "GO"
    assert result["allowed"] is True
    assert result["evidence_summary"]["refund_total"] == 1819.92
    assert result["evidence_summary"]["identity_and_order_ownership_verified"] is True


def test_tau2_cancel_accepts_normalized_currency_and_refund_timing() -> None:
    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_cancel_prewrite

    trajectory, call = _cancel_trajectory_and_call()
    trajectory[16]["content"] = (
        "To cancel order #W2378156 because it is No longer needed, you will receive "
        "a refund of $1,819.92 to credit_card_9513926 in 5–7 business days. Please confirm."
    )

    result = evaluate_tau2_cancel_prewrite(trajectory, call)

    assert result["decision"] == "GO"
    assert result["allowed"] is True
    assert result["evidence_summary"]["refund_total"] == 1819.92


def test_tau2_cancel_adapter_blocks_confirmation_for_other_order_number_wording() -> None:
    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_cancel_prewrite

    trajectory, call = _cancel_trajectory_and_call()
    trajectory[17]["content"] = "Yes, for order number W9999999, proceed as described."

    result = evaluate_tau2_cancel_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert "user_confirmed_after_disclosure" in result["blocking_checks"]


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


def test_tau2_address_adapter_allows_pending_order_after_exact_address_disclosure() -> None:
    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_address_prewrite

    trajectory, call = _address_trajectory_and_call()

    result = evaluate_tau2_address_prewrite(trajectory, call)

    assert result["decision"] == "GO"
    assert result["allowed"] is True
    assert result["evidence_summary"]["identity_and_order_ownership_verified"] is True


def test_tau2_address_adapter_blocks_confirmation_for_other_order_id_wording() -> None:
    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_address_prewrite

    trajectory, call = _address_trajectory_and_call()
    trajectory[17]["content"] = "Yes, use the stated address for order ID: W9999999."

    result = evaluate_tau2_address_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert "user_confirmed_after_disclosure" in result["blocking_checks"]


def test_tau2_address_adapter_blocks_non_pending_order() -> None:
    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_address_prewrite

    trajectory, call = _address_trajectory_and_call()
    order = _tool_result_json(trajectory, "order-read-1")
    order["status"] = "delivered"
    _replace_tool_result_json(trajectory, "order-read-1", order)

    result = evaluate_tau2_address_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert "order_is_pending" in result["blocking_checks"]


def test_tau2_address_adapter_blocks_conflicting_zip_in_user_confirmation() -> None:
    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_address_prewrite

    trajectory, call = _address_trajectory_and_call()
    trajectory[17]["content"] = "Yes, use ZIP 99999 instead."

    result = evaluate_tau2_address_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert "user_confirmed_after_disclosure" in result["blocking_checks"]


def test_tau2_address_adapter_blocks_no_op_address_change() -> None:
    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_address_prewrite

    trajectory, call = _address_trajectory_and_call()
    order = _tool_result_json(trajectory, "order-read-1")
    call["arguments"].update(order["address"])

    trajectory[16]["content"] = (
        "To confirm order #W2378156, change the shipping address to 763 Broadway, "
        "Suite 135, Philadelphia, PA, USA, ZIP 19122. Please confirm."
    )

    result = evaluate_tau2_address_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert "address_differs_from_current_order" in result["blocking_checks"]


def test_tau2_payment_adapter_allows_known_new_method_after_disclosure() -> None:
    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_payment_prewrite

    trajectory, call = _payment_trajectory_and_call()

    result = evaluate_tau2_payment_prewrite(trajectory, call)

    assert result["decision"] == "GO"
    assert result["allowed"] is True
    assert result["evidence_summary"]["old_payment_method_id"] == "credit_card_9513926"
    assert result["evidence_summary"]["new_payment_method_id"] == "credit_card_1234567"


def test_tau2_payment_adapter_blocks_confirmation_for_other_order_number_wording() -> None:
    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_payment_prewrite

    trajectory, call = _payment_trajectory_and_call()
    trajectory[19]["content"] = (
        "Yes, proceed with the payment method for order number W9999999 as described."
    )

    result = evaluate_tau2_payment_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert "user_confirmed_after_disclosure" in result["blocking_checks"]


def test_tau2_payment_adapter_blocks_method_not_in_user_details() -> None:
    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_payment_prewrite

    trajectory, call = _payment_trajectory_and_call()
    call["arguments"]["payment_method_id"] = "credit_card_9999999"
    trajectory[18]["content"] = (
        "For order #W2378156, change payment method from credit_card_9513926 to "
        "credit_card_9999999. Please confirm."
    )
    trajectory[19]["content"] = "Yes, change the payment method as stated."

    result = evaluate_tau2_payment_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert "new_payment_method_belongs_to_order_owner" in result["blocking_checks"]


def test_tau2_payment_adapter_blocks_same_as_current_method() -> None:
    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_payment_prewrite

    trajectory, call = _payment_trajectory_and_call()
    call["arguments"]["payment_method_id"] = "credit_card_9513926"
    trajectory[18]["content"] = (
        "For order #W2378156, keep payment method credit_card_9513926. Please confirm."
    )

    result = evaluate_tau2_payment_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert "payment_method_is_changed" in result["blocking_checks"]


def _pending_items_trajectory_and_call(*, single_item: bool = True) -> tuple[list[dict], dict]:
    trajectory, _ = _trajectory_and_call()
    order = _tool_result_json(trajectory, "order-read-1")
    order["status"] = "pending"
    _replace_tool_result_json(trajectory, "order-read-1", order)
    old_items = ["1151293680"] if single_item else ["1151293680", "4983901480"]
    new_items = ["7706410293"] if single_item else ["7706410293", "7747408585"]
    refund = "$3.17" if single_item else "$16.63"
    pairs = (
        "exchange old item 1151293680 for 7706410293"
        if single_item else
        "exchange old item 1151293680 for 7706410293 and old item 4983901480 for 7747408585"
    )
    call = {
        "id": "pending-items-call-001",
        "name": "modify_pending_order_items",
        "arguments": {
            "order_id": "#W2378156",
            "item_ids": old_items,
            "new_item_ids": new_items,
            "payment_method_id": "credit_card_9513926",
        },
    }
    trajectory[-1]["tool_calls"] = [call]
    trajectory[16]["content"] = (
        f"To confirm order #W2378156: {pairs}. The total price difference is "
        f"a {refund} refund to credit_card_9513926. Please confirm."
    )
    trajectory[17]["content"] = "Yes, that's correct. Please proceed with the item update."
    return trajectory, call


def test_tau2_pending_items_adapter_allows_supported_pending_order_modification() -> None:
    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_pending_items_prewrite

    trajectory, call = _pending_items_trajectory_and_call()

    result = evaluate_tau2_pending_items_prewrite(trajectory, call)

    assert result["decision"] == "GO"
    assert result["allowed"] is True
    assert result["evidence_summary"]["order_status"] == "pending"
    assert result["evidence_summary"]["pending_order_item_modification_not_previously_attempted"] is True


def test_tau2_pending_items_adapter_blocks_multi_item_modification() -> None:
    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_pending_items_prewrite

    trajectory, call = _pending_items_trajectory_and_call(single_item=False)
    result = evaluate_tau2_pending_items_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert result["allowed"] is False
    assert result["blocking_checks"] == ["single_item_modification_only"]


def test_tau2_pending_items_adapter_blocks_delivered_order() -> None:
    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_pending_items_prewrite

    trajectory, call = _pending_items_trajectory_and_call()
    order = _tool_result_json(trajectory, "order-read-1")
    order["status"] = "delivered"
    _replace_tool_result_json(trajectory, "order-read-1", order)

    result = evaluate_tau2_pending_items_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert "order_status_matches_required_state" in result["blocking_checks"]


def test_tau2_pending_items_adapter_blocks_prior_attempt_even_after_fresh_read() -> None:
    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_pending_items_prewrite

    trajectory, call = _pending_items_trajectory_and_call()
    prior_call = {
        "id": "prior-pending-items-call",
        "name": "modify_pending_order_items",
        "arguments": dict(call["arguments"]),
    }
    order_read_index = next(
        index for index, message in enumerate(trajectory)
        if any(tool_call.get("id") == "order-read-1" for tool_call in message.get("tool_calls", []))
    )
    trajectory.insert(order_read_index, {"role": "assistant", "tool_calls": [prior_call]})
    trajectory.insert(order_read_index + 1, {
        "role": "tool",
        "id": "prior-pending-items-call",
        "content": json.dumps({"status": "pending"}),
    })

    result = evaluate_tau2_pending_items_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert "pending_order_item_modification_already_attempted" in result["blocking_checks"]


def _user_address_trajectory_and_call() -> tuple[list[dict], dict]:
    trajectory, _ = _trajectory_and_call()
    order = _tool_result_json(trajectory, "order-read-1")
    owner_id = order["user_id"]
    user_details = {
        "user_id": owner_id,
        "name": "Customer Example",
        "email": "customer@example.com",
        "address": order["address"],
        "payment_methods": {},
    }
    trajectory.insert(16, {
        "role": "assistant",
        "tool_calls": [{
            "id": "user-profile-read-1",
            "name": "get_user_details",
            "arguments": {"user_id": owner_id},
        }],
    })
    trajectory.insert(17, {
        "role": "tool",
        "id": "user-profile-read-1",
        "content": json.dumps(user_details),
    })
    call = {
        "id": "user-address-call-001",
        "name": "modify_user_address",
        "arguments": {
            "user_id": owner_id,
            "address1": "100 Main Street",
            "address2": "Unit 4",
            "city": "Boston",
            "state": "MA",
            "country": "USA",
            "zip": "02108",
        },
    }
    trajectory[-1]["tool_calls"] = [call]
    trajectory[18]["content"] = (
        "For Customer Example, update your default address to 100 Main Street, Unit 4, "
        "Boston, MA, USA, ZIP 02108. Please confirm."
    )
    trajectory[19]["content"] = "Yes, update my default address as stated."
    return trajectory, call


def test_tau2_user_address_adapter_allows_verified_default_address_change() -> None:
    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_user_address_prewrite

    trajectory, call = _user_address_trajectory_and_call()

    result = evaluate_tau2_user_address_prewrite(trajectory, call)

    assert result["decision"] == "GO"
    assert result["allowed"] is True
    assert result["evidence_summary"]["identity_matches_user_details"] is True


def test_tau2_user_address_adapter_blocks_conflicting_postal_code() -> None:
    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_user_address_prewrite

    trajectory, call = _user_address_trajectory_and_call()
    trajectory[19]["content"] = "Yes, use postal code 99999 instead."

    result = evaluate_tau2_user_address_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert "user_confirmed_after_disclosure" in result["blocking_checks"]


def test_tau2_user_address_adapter_blocks_identity_mismatch() -> None:
    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_user_address_prewrite

    trajectory, call = _user_address_trajectory_and_call()
    user = _tool_result_json(trajectory, "user-profile-read-1")
    user["user_id"] = "different_user_id"
    _replace_tool_result_json(trajectory, "user-profile-read-1", user)

    result = evaluate_tau2_user_address_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert "identity_matches_user_details" in result["blocking_checks"]


def _return_trajectory_and_call() -> tuple[list[dict], dict]:
    trajectory, _ = _trajectory_and_call()
    order = _tool_result_json(trajectory, "order-read-1")
    owner_id = order["user_id"]
    user_details = {
        "user_id": owner_id,
        "name": "Customer Example",
        "email": "customer@example.com",
        "address": order["address"],
        "payment_methods": {
            "credit_card_9513926": {
                "id": "credit_card_9513926",
                "source": "credit_card",
                "brand": "visa",
                "last_four": "3926",
            },
            "gift_card_1234567": {
                "id": "gift_card_1234567",
                "source": "gift_card",
            },
            "credit_card_1234567": {
                "id": "credit_card_1234567",
                "source": "credit_card",
                "brand": "visa",
                "last_four": "4567",
            },
        },
    }
    trajectory.insert(16, {
        "role": "assistant",
        "tool_calls": [{
            "id": "return-user-read-1",
            "name": "get_user_details",
            "arguments": {"user_id": owner_id},
        }],
    })
    trajectory.insert(17, {
        "role": "tool",
        "id": "return-user-read-1",
        "content": json.dumps(user_details),
    })
    call = {
        "id": "return-call-001",
        "name": "return_delivered_order_items",
        "arguments": {
            "order_id": "#W2378156",
            "item_ids": ["1151293680"],
            "payment_method_id": "credit_card_9513926",
        },
    }
    trajectory[-1]["tool_calls"] = [call]
    trajectory[18]["content"] = (
        "For order #W2378156, request return of item 1151293680 using "
        "credit_card_9513926 (credit card, visa ending 3926). This will create a "
        "return request, and you will receive a follow-up email with return instructions. "
        "Please confirm."
    )
    trajectory[19]["content"] = "Yes, I confirm the return request as described."
    return trajectory, call


def test_tau2_return_adapter_allows_verified_return_request() -> None:
    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_return_prewrite

    trajectory, call = _return_trajectory_and_call()

    result = evaluate_tau2_return_prewrite(trajectory, call)

    assert result["decision"] == "GO"
    assert result["allowed"] is True
    assert result["evidence_summary"]["order_status"] == "delivered"


def test_tau2_return_adapter_blocks_confirmation_for_other_order_number_wording() -> None:
    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_return_prewrite

    trajectory, call = _return_trajectory_and_call()
    trajectory[19]["content"] = (
        "Yes, submit the return request for order number W9999999 as described."
    )

    result = evaluate_tau2_return_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert "user_confirmed_after_disclosure" in result["blocking_checks"]


def test_tau2_return_adapter_blocks_unrelated_non_gift_card_payment_method() -> None:
    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_return_prewrite

    trajectory, call = _return_trajectory_and_call()
    call["arguments"]["payment_method_id"] = "credit_card_1234567"
    trajectory[18]["content"] = (
        "For order #W2378156, request return of item 1151293680 using "
        "credit_card_1234567 (credit card, visa ending 4567). This will create a "
        "return request, and you will receive a follow-up email with return instructions. "
        "Please confirm."
    )

    result = evaluate_tau2_return_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert "payment_method_is_original_or_verified_gift_card" in result["blocking_checks"]


def test_tau2_return_adapter_blocks_item_not_in_order() -> None:
    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_return_prewrite

    trajectory, call = _return_trajectory_and_call()
    call["arguments"]["item_ids"] = ["9999999999"]
    trajectory[18]["content"] = (
        "For order #W2378156, request return of item 9999999999 using "
        "credit_card_9513926 (credit card, visa ending 3926). This will create a "
        "return request, and you will receive a follow-up email with return instructions. "
        "Please confirm."
    )

    result = evaluate_tau2_return_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert "requested_items_belong_to_order_quantity" in result["blocking_checks"]


def test_tau2_exchange_blocks_disclosure_that_lists_ids_without_naming_exchange() -> None:
    trajectory, call = _trajectory_and_call()
    trajectory[16]["content"] = (
        "Order #W2378156 contains old item 1151293680, new item 7706410293, old item "
        "4983901480, new item 7747408585. The total price difference is a $16.63 "
        "refund to credit_card_9513926. Please confirm."
    )
    trajectory[17]["content"] = "Yes, that's correct. Please proceed."

    result = evaluate_tau2_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"


def test_tau2_cancel_blocks_refund_disclosure_that_omits_cancellation_action() -> None:
    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_cancel_prewrite

    trajectory, call = _cancel_trajectory_and_call()
    trajectory[16]["content"] = (
        "For order #W2378156, the reason is no longer needed. You will receive a "
        "refund of 1819.92 to credit_card_9513926 in 5-7 business days. Please confirm."
    )

    result = evaluate_tau2_cancel_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert "exact_cancellation_and_refund_disclosure_valid" in result["blocking_checks"]


def test_tau2_order_address_blocks_address_values_without_update_action() -> None:
    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_address_prewrite

    trajectory, call = _address_trajectory_and_call()
    trajectory[16]["content"] = (
        "For order #W2378156: 100 Main Street, Unit 4, Boston, MA, USA, ZIP 02108. "
        "Please confirm."
    )

    result = evaluate_tau2_address_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert "exact_new_address_disclosed" in result["blocking_checks"]


def test_tau2_payment_blocks_method_ids_without_describing_payment_change() -> None:
    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_payment_prewrite

    trajectory, call = _payment_trajectory_and_call()
    trajectory[18]["content"] = (
        "For order #W2378156, credit_card_9513926 to credit_card_1234567 "
        "(credit card, visa ending 4567). Please confirm."
    )

    result = evaluate_tau2_payment_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert "exact_old_and_new_payment_details_disclosed" in result["blocking_checks"]


def test_tau2_user_address_blocks_address_values_without_default_address_action() -> None:
    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_user_address_prewrite

    trajectory, call = _user_address_trajectory_and_call()
    trajectory[18]["content"] = (
        "Customer Example: 100 Main Street, Unit 4, Boston, MA, USA, ZIP 02108. "
        "Please confirm."
    )

    result = evaluate_tau2_user_address_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert "exact_new_address_and_customer_disclosed" in result["blocking_checks"]



@pytest.mark.parametrize(
    ("builder", "evaluator"),
    [
        (_fully_disclosed_exchange_trajectory_and_call, evaluate_tau2_prewrite),
        (_cancel_trajectory_and_call, evaluate_tau2_cancel_prewrite),
        (_address_trajectory_and_call, evaluate_tau2_address_prewrite),
        (_payment_trajectory_and_call, evaluate_tau2_payment_prewrite),
        (_pending_items_trajectory_and_call, evaluate_tau2_pending_items_prewrite),
        (_user_address_trajectory_and_call, evaluate_tau2_user_address_prewrite),
        (_return_trajectory_and_call, evaluate_tau2_return_prewrite),
    ],
)
def test_every_write_policy_rejects_hedged_confirmation(builder, evaluator) -> None:
    trajectory, call = builder()
    valid_reply = next(
        message for message in reversed(trajectory) if message.get("role") == "user"
    )
    assert evaluator(trajectory, call)["decision"] == "GO"

    valid_reply["content"] = "Not sure. Go ahead."
    result = evaluator(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert result["allowed"] is False
    summary = result.get("evidence_summary", {})
    if "user_affirmed_after_disclosure" in summary:
        assert summary["user_affirmed_after_disclosure"] is False
