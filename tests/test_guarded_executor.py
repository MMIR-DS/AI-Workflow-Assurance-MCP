from __future__ import annotations

from copy import deepcopy

from ai_workflow_assurance_mcp.guarded_executor import execute_if_prewrite_allowed


def _valid_inputs() -> tuple[dict, dict]:
    action = {
        "order_id": "ORD-1001",
        "old_item_ids": ["ITEM-11"],
        "new_item_ids": ["ITEM-12"],
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
            "old_item_ids": ["ITEM-11"],
            "new_item_ids": ["ITEM-12"],
            "payment_method_id": "PAY-1",
            "confirmation_id": "CONF-1",
        },
        "customer_facing_confirmation": {
            "order_id": "ORD-1001",
            "old_item_ids": ["ITEM-11"],
            "new_item_ids": ["ITEM-12"],
            "payment_method_id": "PAY-1",
            "payment_method_disclosed": True,
        },
        "confirmation_event_sequence": 3,
        "proposed_write_sequence": 4,
    }
    return action, evidence


def test_denied_preflight_never_invokes_write_callback() -> None:
    action, evidence = _valid_inputs()
    evidence["customer_facing_confirmation"]["payment_method_disclosed"] = False
    calls: list[dict] = []

    result = execute_if_prewrite_allowed(action, evidence, calls.append)

    assert result["decision"] == "NO_GO"
    assert result["executed"] is False
    assert calls == []
    assert "exact_action_or_payment_method_not_disclosed_to_customer" in result["blocking_checks"]


def test_allowed_preflight_invokes_callback_exactly_once_with_action_copy() -> None:
    action, evidence = _valid_inputs()
    calls: list[dict] = []

    result = execute_if_prewrite_allowed(
        action,
        evidence,
        lambda value: calls.append(value) or {"write_id": "WRITE-1"},
    )

    assert result["decision"] == "GO"
    assert result["executed"] is True
    assert calls == [action]
    assert result["write_result"] == {"write_id": "WRITE-1"}
    assert calls[0] is not action


def test_invalid_action_never_invokes_write_callback() -> None:
    action, evidence = _valid_inputs()
    action["payment_method_id"] = " "
    calls: list[dict] = []

    result = execute_if_prewrite_allowed(action, evidence, calls.append)

    assert result["decision"] == "NO_GO"
    assert result["executed"] is False
    assert calls == []


def test_non_callable_write_operation_fails_closed() -> None:
    action, evidence = _valid_inputs()

    result = execute_if_prewrite_allowed(action, evidence, None)  # type: ignore[arg-type]

    assert result["decision"] == "NO_GO"
    assert result["executed"] is False
    assert result["blocking_checks"] == ["write_operation_not_callable"]


def test_write_exception_propagates_without_being_misreported_as_success() -> None:
    action, evidence = _valid_inputs()

    def fail_write(_: dict) -> None:
        raise RuntimeError("simulated database failure")

    try:
        execute_if_prewrite_allowed(action, evidence, fail_write)
    except RuntimeError as exc:
        assert str(exc) == "simulated database failure"
    else:
        raise AssertionError("write failure should propagate")
