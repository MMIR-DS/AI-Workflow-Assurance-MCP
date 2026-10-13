from __future__ import annotations

from ai_workflow_assurance_mcp.tau2_prewrite import (
    TAU2_WRITE_TOOLS,
    _exchange_pairing_disclosed,
    _price_difference_disclosed,
)
from scripts.adapt_tau2_results import WRITE_TOOLS as ADAPTER_WRITE_TOOLS
from scripts.verify_tau2_independent_db import WRITE_TOOLS as INDEPENDENT_DB_WRITE_TOOLS


def test_refund_direction_is_not_inferred_from_credit_card_identifier() -> None:
    text = (
        "The price difference is $16.63; you will be charged $16.63 "
        "on credit_card_9513926."
    )
    assert _price_difference_disclosed(text, -16.63) is False


def test_explicit_refund_disclosure_accepts_currency_and_thousands_separators() -> None:
    assert _price_difference_disclosed(
        "The price difference is a $16.63 refund to credit_card_9513926.",
        -16.63,
    )
    assert _price_difference_disclosed(
        "The price difference is a $1,819.92 refund to credit_card_9513926.",
        -1819.92,
    )


def test_posthoc_and_independent_audits_share_one_write_tool_set() -> None:
    assert ADAPTER_WRITE_TOOLS is TAU2_WRITE_TOOLS
    assert INDEPENDENT_DB_WRITE_TOOLS is TAU2_WRITE_TOOLS
    assert "modify_pending_order_payment" in TAU2_WRITE_TOOLS
    assert "exchange_delivered_order_items" in TAU2_WRITE_TOOLS


def test_item_pair_disclosure_accepts_explicit_arrows() -> None:
    assert _exchange_pairing_disclosed(
        "Exchange 11111111 → 22222222 and 33333333 → 44444444.",
        ["11111111", "33333333"],
        ["22222222", "44444444"],
    )
