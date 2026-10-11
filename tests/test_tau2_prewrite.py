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
        "and old item 4983901480 for 7747408585. Use payment method "
        "credit_card_9513926 for any price difference. Please confirm."
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
        "and old item 4983901480 for 7747408585. Use payment method "
        "credit_card_9513926 for any price difference. Please confirm."
    )
    trajectory[17]["content"] = "No, don't go ahead. I need to change the selections."

    result = evaluate_tau2_prewrite(trajectory, call)

    assert result["decision"] == "NO_GO"
    assert result["evidence_summary"]["user_affirmed_after_disclosure"] is False


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
