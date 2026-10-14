from __future__ import annotations

from copy import deepcopy

from ai_workflow_assurance_mcp.prewrite_guard import evaluate_prewrite


def _valid_inputs() -> tuple[dict, dict]:
    action = {
        "order_id": "ORD-1001",
        "old_item_ids": ["ITEM-11", "ITEM-21"],
        "new_item_ids": ["ITEM-12", "ITEM-22"],
        "payment_method_id": "PAY-1",
    }
    evidence = {
        "identity_verified": True,
        "verified_user_id": "USER-7",
        "order_owner_id": "USER-7",
        "order_id": "ORD-1001",
        "order_status": "delivered",
        "confirmation": {
            "confirmed": True,
            "order_id": "ORD-1001",
            "old_item_ids": ["ITEM-11", "ITEM-21"],
            "new_item_ids": ["ITEM-12", "ITEM-22"],
            "payment_method_id": "PAY-1",
            "confirmation_id": "CONF-1",
        },
        "customer_facing_confirmation": {
            "order_id": "ORD-1001",
            "old_item_ids": ["ITEM-11", "ITEM-21"],
            "new_item_ids": ["ITEM-12", "ITEM-22"],
            "payment_method_id": "PAY-1",
            "payment_method_disclosed": True,
        },
        "confirmation_event_sequence": 3,
        "proposed_write_sequence": 4,
    }
    return action, evidence


def test_matching_verified_action_and_prior_confirmation_allows_preflight() -> None:
    action, evidence = _valid_inputs()
    result = evaluate_prewrite(action, evidence)
    assert result["decision"] == "GO"
    assert result["allowed"] is True
    assert result["blocking_checks"] == []
    assert result["scope"] == "reference_preflight_only_not_a_write_interceptor"
    assert result["evidence_trust_boundary"] == "caller_supplied_not_authenticated"


def test_missing_exact_payment_disclosure_fails_closed() -> None:
    action, evidence = _valid_inputs()
    evidence["customer_facing_confirmation"]["payment_method_disclosed"] = False
    result = evaluate_prewrite(action, evidence)
    assert result["decision"] == "NO_GO"
    assert result["allowed"] is False
    assert "exact_action_or_payment_method_not_disclosed_to_customer" in result["blocking_checks"]


def test_payment_method_mismatch_between_action_and_confirmation_fails_closed() -> None:
    action, evidence = _valid_inputs()
    evidence["confirmation"]["payment_method_id"] = "PAY-OTHER"
    result = evaluate_prewrite(action, evidence)
    assert result["decision"] == "NO_GO"
    assert "explicit_confirmation_does_not_match_action" in result["blocking_checks"]


def test_confirmation_after_proposed_write_fails_closed() -> None:
    action, evidence = _valid_inputs()
    evidence["confirmation_event_sequence"] = 5
    evidence["proposed_write_sequence"] = 4
    result = evaluate_prewrite(action, evidence)
    assert result["decision"] == "NO_GO"
    assert "confirmation_not_proven_to_precede_write" in result["blocking_checks"]


def test_identity_mismatch_and_non_delivered_order_fail_closed() -> None:
    action, evidence = _valid_inputs()
    evidence["verified_user_id"] = "USER-OTHER"
    evidence["order_status"] = "cancelled"
    result = evaluate_prewrite(action, evidence)
    assert result["decision"] == "NO_GO"
    assert "identity_or_order_ownership_not_verified" in result["blocking_checks"]
    assert "order_not_confirmed_delivered" in result["blocking_checks"]


def test_empty_action_item_id_fails_closed() -> None:
    action, evidence = _valid_inputs()
    action["new_item_ids"] = ["ITEM-12", " "]
    result = evaluate_prewrite(action, evidence)
    assert result["decision"] == "NO_GO"
    assert "action_incomplete_or_invalid" in result["blocking_checks"]


def test_repeated_item_ids_are_supported_when_old_and_new_counts_match() -> None:
    action, evidence = _valid_inputs()
    action["old_item_ids"] = ["ITEM-11", "ITEM-11"]
    action["new_item_ids"] = ["ITEM-12", "ITEM-12"]
    evidence["confirmation"]["old_item_ids"] = ["ITEM-11", "ITEM-11"]
    evidence["confirmation"]["new_item_ids"] = ["ITEM-12", "ITEM-12"]
    evidence["customer_facing_confirmation"]["old_item_ids"] = ["ITEM-11", "ITEM-11"]
    evidence["customer_facing_confirmation"]["new_item_ids"] = ["ITEM-12", "ITEM-12"]
    result = evaluate_prewrite(action, evidence)
    assert result["decision"] == "GO"


def test_missing_evidence_and_wrong_types_fail_closed() -> None:
    assert evaluate_prewrite({}, None)["decision"] == "NO_GO"
    action, evidence = _valid_inputs()
    evidence["identity_verified"] = 1  # bool/int confusion must not pass
    result = evaluate_prewrite(action, evidence)
    assert result["decision"] == "NO_GO"
    assert "identity_or_order_ownership_not_verified" in result["blocking_checks"]


def test_preflight_does_not_mutate_caller_inputs() -> None:
    action, evidence = _valid_inputs()
    original_action, original_evidence = deepcopy(action), deepcopy(evidence)
    evaluate_prewrite(action, evidence)
    assert action == original_action
    assert evidence == original_evidence
