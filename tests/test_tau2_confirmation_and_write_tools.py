from __future__ import annotations

import re

from ai_workflow_assurance_mcp.tau2_constants import WRITE_TOOLS
from ai_workflow_assurance_mcp.tau2_prewrite import (
    _WRITE_TOOLS,
    _evaluate_exchange_confirmation_context,
    _exchange_pairing_disclosed,
    _is_affirmative,
    _price_difference_disclosed,
)
from scripts.adapt_tau2_results import WRITE_TOOLS as ADAPTER_WRITE_TOOLS
from scripts.install_tau2_prewrite_guard import REPLACEMENT
from scripts.verify_tau2_independent_db import WRITE_TOOLS as DB_WRITE_TOOLS


def test_negative_price_difference_requires_refund_direction_near_amount() -> None:
    assert _price_difference_disclosed(
        "The total price difference is a $16.63 refund to credit_card_9513926.",
        -16.63,
    )
    assert not _price_difference_disclosed(
        "The total price difference is $16.63. You will be charged $16.63 "
        "on credit_card_9513926.",
        -16.63,
    )
    assert _price_difference_disclosed(
        "The total price difference of $1,819.92 will be refunded to the card.",
        -1819.92,
    )
    assert not _price_difference_disclosed(
        "The total price difference is $1,016.63, refunded to the card.",
        -16.63,
    )


def test_cancellation_confirmation_allows_affirmative_natural_phrasing() -> None:
    assert _is_affirmative("Yes, cancel it.", action="cancel")
    assert _is_affirmative("Yes, it's no longer needed.", action="cancel")
    assert not _is_affirmative("No, let's not cancel it.", action="cancel")
    assert not _is_affirmative("Yes, cancel the exchange.", action="exchange")


def test_shared_exchange_confirmation_requires_full_prewrite_disclosure() -> None:
    incomplete = _evaluate_exchange_confirmation_context(
        "To confirm: keyboard 7706410293 and thermostat 7747408585. "
        "Your original payment method is credit_card_9513926. "
        "Would you like to use it for the price difference?",
        "Yes, that's exactly right. Go ahead and use credit_card_9513926.",
        "#W2378156",
        ["1151293680", "4983901480"],
        ["7706410293", "7747408585"],
        "credit_card_9513926",
        -16.63,
    )
    assert incomplete["confirmation_valid"] is False
    assert incomplete["disclosure_valid"] is False
    assert incomplete["price_difference_disclosed"] is False

    complete = _evaluate_exchange_confirmation_context(
        "To confirm order #W2378156: exchange old item 1151293680 for 7706410293 "
        "and old item 4983901480 for 7747408585. The total price difference is "
        "a $16.63 refund to credit_card_9513926. Please confirm.",
        "Yes, that's correct. Go ahead and use credit_card_9513926 for this exchange.",
        "#W2378156",
        ["1151293680", "4983901480"],
        ["7706410293", "7747408585"],
        "credit_card_9513926",
        -16.63,
    )
    assert complete["confirmation_valid"] is True
    assert complete["disclosure_valid"] is True
    assert complete["price_difference_disclosed"] is True


def test_all_tau2_write_paths_share_one_complete_inventory() -> None:
    expected = {
        "cancel_pending_order",
        "exchange_delivered_order_items",
        "modify_pending_order_address",
        "modify_pending_order_items",
        "modify_pending_order_payment",
        "modify_user_address",
        "return_delivered_order_items",
    }
    assert WRITE_TOOLS == expected
    assert ADAPTER_WRITE_TOOLS is WRITE_TOOLS
    assert DB_WRITE_TOOLS is WRITE_TOOLS
    assert _WRITE_TOOLS is WRITE_TOOLS
    assert "from ai_workflow_assurance_mcp.tau2_constants import WRITE_TOOLS as awa_shared_write_tools" in REPLACEMENT
    assert 'set(awa_shared_write_tools) | {"create_order"}' in REPLACEMENT


def test_exchange_pair_disclosure_accepts_arrow_typography_after_normalization() -> None:
    assert _exchange_pairing_disclosed(
        "To confirm: exchange item 1151293680 → 7706410293 and item "
        "4983901480 → 7747408585.",
        ["1151293680", "4983901480"],
        ["7706410293", "7747408585"],
    )


def test_price_disclosure_fails_closed_when_charge_and_refund_directions_conflict() -> None:
    contradictory = (
        "The price difference is $16.63 refund, but you will also be charged $16.63 "
        "on credit_card_9513926."
    )
    assert _price_difference_disclosed(contradictory, -16.63) is False
    assert _price_difference_disclosed(contradictory, 16.63) is False


def test_dispatch_policy_table_covers_every_reviewed_write_tool() -> None:
    policy_names = set(
        re.findall(r'^\s{12}"([a-z_]+)": \{$', REPLACEMENT, re.MULTILINE)
    )
    assert policy_names == WRITE_TOOLS
    assert 'tool_call.name in awa_write_tools' in REPLACEMENT
    assert "this retail write tool has no reviewed " in REPLACEMENT
    assert '"validator": evaluate_tau2_pending_items_prewrite' in REPLACEMENT
    assert '"single_item_only": True' in REPLACEMENT
    assert "audit_tau2_single_pending_item_write_response" in REPLACEMENT
    assert "AWA_POSTWRITE_AUDIT_NOT_PASS" in REPLACEMENT
    assert "multi-item mutations remain disabled" in REPLACEMENT
