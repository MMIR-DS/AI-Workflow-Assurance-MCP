from __future__ import annotations

import pytest

from ai_workflow_assurance_mcp.tau2_prewrite_common import _contains_all, _is_affirmative


@pytest.mark.parametrize(
    "text",
    [
        "Can you confirm the price difference first?",
        "Can you confirm the price difference first",
        "Right, can you confirm the price difference first",
        "Yes, can you confirm the price difference first",
        "Yes, do you want me to proceed",
        "Yes, is that the one",
        "Can we proceed with this?",
        "Is that correct? I'm not sure about the second item.",
        "Do I need to confirm anything?",
        "Do I need to confirm anything",
        "Not sure. Go ahead.",
        "I'm unsure, but proceed.",
        "Maybe yes.",
        "I think so, go ahead.",
    ],
)
def test_questions_and_hedged_replies_are_not_affirmative(text: str) -> None:
    assert _is_affirmative(text) is False


@pytest.mark.parametrize(
    ("text", "action"),
    [
        (
            "Yes, that's correct. Go ahead and use credit_card_9513926 for this exchange.",
            "exchange",
        ),
        ("Confirmed, please proceed.", "exchange"),
        ("Yes, do it", "exchange"),
        ("Yes, that is the one", "exchange"),
        ("ok go ahead", "exchange"),
        ("Okay, proceed", "exchange"),
        ("okay", "exchange"),
        ("Sure, do it.", "exchange"),
        ("Yes, cancel this order because it is no longer needed.", "cancel"),
    ],
)
def test_explicit_unhedged_confirmation_remains_affirmative(
    text: str, action: str
) -> None:
    assert _is_affirmative(text, action=action) is True


def test_identifier_matching_rejects_prefix_collisions() -> None:
    assert _contains_all("Use credit_card_1234567 for the refund.", ["credit_card_1234567"])
    assert not _contains_all("Use credit_card_12345678 for the refund.", ["credit_card_1234567"])
    assert _contains_all("Order #W1234 is ready.", ["#W1234"])
    assert not _contains_all("Order #W12345 is ready.", ["#W1234"])
