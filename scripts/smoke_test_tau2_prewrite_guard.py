"""No-model smoke test for the patched Tau2 write-dispatch method.

Run inside the pinned Tau2 virtual environment after applying the source patch:
PYTHONPATH=../src uv run python ../scripts/smoke_test_tau2_prewrite_guard.py
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from tau2.data_model.message import ToolCall, ToolMessage
from tau2.orchestrator.orchestrator import BaseOrchestrator

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "tau2_task0_trace_minimal.json"


class CountingEnvironment:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_response(self, tool_call: ToolCall) -> ToolMessage:
        self.calls.append(tool_call.name)
        return ToolMessage(
            id=tool_call.id,
            role="tool",
            requestor=tool_call.requestor,
            content="SIMULATED_WRITE_EXECUTED",
            error=False,
        )


def _setup() -> tuple[list[dict[str, Any]], ToolCall]:
    results = json.loads(FIXTURE.read_text(encoding="utf-8"))
    trajectory = results["simulations"][0]["messages"][:19]
    raw_call = trajectory[-1]["tool_calls"][0]
    call = ToolCall(
        id=raw_call["id"],
        name=raw_call["name"],
        arguments=raw_call["arguments"],
        requestor="assistant",
    )
    return trajectory, call


def _dispatch(trajectory: list[dict[str, Any]], call: ToolCall) -> tuple[list[ToolMessage], CountingEnvironment, Any]:
    return _dispatch_many(trajectory, [call])


def _dispatch_many(
    trajectory: list[dict[str, Any]], calls: list[ToolCall]
) -> tuple[list[ToolMessage], CountingEnvironment, Any]:
    environment = CountingEnvironment()
    orchestrator = SimpleNamespace(environment=environment, trajectory=trajectory, num_errors=0)
    results = BaseOrchestrator._execute_tool_calls(orchestrator, calls)
    return results, environment, orchestrator


def _setup_cancel() -> tuple[list[dict[str, Any]], ToolCall]:
    trajectory, _ = _setup()
    order_result = next(
        message for message in trajectory
        if message.get("role") == "tool" and message.get("id") == "order-read-1"
    )
    order = json.loads(order_result["content"])
    order["status"] = "pending"
    order_result["content"] = json.dumps(order)
    raw_call = {
        "id": "cancel-call-001",
        "name": "cancel_pending_order",
        "arguments": {
            "order_id": "#W2378156",
            "reason": "no longer needed",
        },
    }
    trajectory[-1]["tool_calls"] = [raw_call]
    trajectory[16]["content"] = (
        "To cancel order #W2378156 because it is no longer needed, you will receive "
        "a refund of 1819.92 to credit_card_9513926 in 5-7 business days. Please confirm."
    )
    trajectory[17]["content"] = "Yes, I confirm the cancellation and refund as described."
    call = ToolCall(
        id=raw_call["id"],
        name=raw_call["name"],
        arguments=raw_call["arguments"],
        requestor="assistant",
    )
    return trajectory, call


def _setup_address() -> tuple[list[dict[str, Any]], ToolCall]:
    trajectory, _ = _setup()
    order_result = next(
        message for message in trajectory
        if message.get("role") == "tool" and message.get("id") == "order-read-1"
    )
    order = json.loads(order_result["content"])
    order["status"] = "pending"
    order_result["content"] = json.dumps(order)
    raw_call = {
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
    trajectory[-1]["tool_calls"] = [raw_call]
    trajectory[16]["content"] = (
        "To confirm order #W2378156, change the shipping address to 100 Main Street, "
        "Unit 4, Boston, MA, USA, ZIP 02108. Please confirm."
    )
    trajectory[17]["content"] = "Yes, update the shipping address as stated."
    call = ToolCall(
        id=raw_call["id"],
        name=raw_call["name"],
        arguments=raw_call["arguments"],
        requestor="assistant",
    )
    return trajectory, call


def _setup_payment() -> tuple[list[dict[str, Any]], ToolCall]:
    trajectory, _ = _setup()
    order_result = next(
        message for message in trajectory
        if message.get("role") == "tool" and message.get("id") == "order-read-1"
    )
    order = json.loads(order_result["content"])
    order["status"] = "pending"
    order_result["content"] = json.dumps(order)
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
    raw_call = {
        "id": "payment-call-001",
        "name": "modify_pending_order_payment",
        "arguments": {
            "order_id": "#W2378156",
            "payment_method_id": "credit_card_1234567",
        },
    }
    trajectory[-1]["tool_calls"] = [raw_call]
    trajectory[18]["content"] = (
        "For order #W2378156, change payment method from credit_card_9513926 to "
        "credit_card_1234567 (credit card, visa ending 4567). Please confirm."
    )
    trajectory[19]["content"] = (
        "Yes, that's correct. Proceed with the payment method described."
    )
    call = ToolCall(
        id=raw_call["id"],
        name=raw_call["name"],
        arguments=raw_call["arguments"],
        requestor="assistant",
    )
    return trajectory, call


def _setup_pending_items() -> tuple[list[dict[str, Any]], ToolCall]:
    trajectory, _ = _setup()
    order_result = next(
        message for message in trajectory
        if message.get("role") == "tool" and message.get("id") == "order-read-1"
    )
    order = json.loads(order_result["content"])
    order["status"] = "pending"
    order_result["content"] = json.dumps(order)
    raw_call = {
        "id": "pending-items-call-001",
        "name": "modify_pending_order_items",
        "arguments": {
            "order_id": "#W2378156",
            "item_ids": ["1151293680", "4983901480"],
            "new_item_ids": ["7706410293", "7747408585"],
            "payment_method_id": "credit_card_9513926",
        },
    }
    trajectory[-1]["tool_calls"] = [raw_call]
    trajectory[16]["content"] = (
        "To confirm order #W2378156: exchange old item 1151293680 for 7706410293 "
        "and old item 4983901480 for 7747408585. The total price difference is "
        "a $16.63 refund to credit_card_9513926. Please confirm."
    )
    trajectory[17]["content"] = "Yes, that's correct. Please proceed with the item update."
    call = ToolCall(
        id=raw_call["id"],
        name=raw_call["name"],
        arguments=raw_call["arguments"],
        requestor="assistant",
    )
    return trajectory, call


def _setup_user_address() -> tuple[list[dict[str, Any]], ToolCall]:
    trajectory, _ = _setup()
    order_result = next(
        message for message in trajectory
        if message.get("role") == "tool" and message.get("id") == "order-read-1"
    )
    order = json.loads(order_result["content"])
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
    raw_call = {
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
    trajectory[-1]["tool_calls"] = [raw_call]
    trajectory[18]["content"] = (
        "For Customer Example, update your default address to 100 Main Street, Unit 4, "
        "Boston, MA, USA, ZIP 02108. Please confirm."
    )
    trajectory[19]["content"] = "Yes, update my default address as stated."
    call = ToolCall(
        id=raw_call["id"],
        name=raw_call["name"],
        arguments=raw_call["arguments"],
        requestor="assistant",
    )
    return trajectory, call


def _setup_return() -> tuple[list[dict[str, Any]], ToolCall]:
    trajectory, _ = _setup()
    order_result = next(
        message for message in trajectory
        if message.get("role") == "tool" and message.get("id") == "order-read-1"
    )
    order = json.loads(order_result["content"])
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
    raw_call = {
        "id": "return-call-001",
        "name": "return_delivered_order_items",
        "arguments": {
            "order_id": "#W2378156",
            "item_ids": ["1151293680"],
            "payment_method_id": "credit_card_9513926",
        },
    }
    trajectory[-1]["tool_calls"] = [raw_call]
    trajectory[18]["content"] = (
        "For order #W2378156, request return of item 1151293680 using "
        "credit_card_9513926 (credit card, visa ending 3926). This will create a "
        "return request, and you will receive a follow-up email with return instructions. "
        "Please confirm."
    )
    trajectory[19]["content"] = "Yes, I confirm the return request as described."
    call = ToolCall(
        id=raw_call["id"],
        name=raw_call["name"],
        arguments=raw_call["arguments"],
        requestor="assistant",
    )
    return trajectory, call


def main() -> None:
    # The recorded baseline omits the order ID and old item IDs in the final
    # customer-facing confirmation. The patched dispatch must block before
    # the environment/write callback is called.
    trajectory, call = _setup()
    results, environment, orchestrator = _dispatch(trajectory, call)
    assert len(results) == 1 and results[0].error
    assert environment.calls == [], "NO_GO must never reach the environment write callback"
    assert "AWA_PREWRITE_NO_GO" in (results[0].content or "")
    assert orchestrator.num_errors == 1

    # A complete confirmation plus an affirmative customer reply allows the
    # fake write callback exactly once. This does not touch a real Tau2 DB.
    trajectory, call = _setup()
    trajectory[16]["content"] = (
        "To confirm order #W2378156: exchange old item 1151293680 for 7706410293 "
        "and old item 4983901480 for 7747408585. The total price difference is "
        "a $16.63 refund to credit_card_9513926. Please confirm."
    )
    trajectory[17]["content"] = (
        "Yes, that's correct. Go ahead and use credit_card_9513926 for this exchange."
    )
    results, environment, orchestrator = _dispatch(trajectory, call)
    assert len(results) == 1 and not results[0].error
    assert environment.calls == ["exchange_delivered_order_items"]
    assert results[0].content == "SIMULATED_WRITE_EXECUTED"
    assert orchestrator.num_errors == 0

    # Two exchanges for the same order in one batch must not reuse the same
    # preflight snapshot. The first reaches the fake callback; the second is blocked.
    trajectory, first_call = _setup()
    trajectory[16]["content"] = (
        "To confirm order #W2378156: exchange old item 1151293680 for 7706410293 "
        "and old item 4983901480 for 7747408585. The total price difference is "
        "a $16.63 refund to credit_card_9513926. Please confirm."
    )
    trajectory[17]["content"] = (
        "Yes, that's correct. Go ahead and use credit_card_9513926 for this exchange."
    )
    second_call = ToolCall(
        id="duplicate-same-order-exchange",
        name=first_call.name,
        arguments=dict(first_call.arguments),
        requestor="assistant",
    )
    results, environment, orchestrator = _dispatch_many(trajectory, [first_call, second_call])
    assert len(results) == 2
    assert not results[0].error and results[1].error
    assert environment.calls == ["exchange_delivered_order_items"]
    assert "second write for the same order" in (results[1].content or "")
    assert orchestrator.num_errors == 1

    # A valid pending-order cancellation must pass through the same actual dispatcher.
    trajectory, cancel_call = _setup_cancel()
    results, environment, orchestrator = _dispatch(trajectory, cancel_call)
    assert len(results) == 1 and not results[0].error
    assert environment.calls == ["cancel_pending_order"]
    assert results[0].content == "SIMULATED_WRITE_EXECUTED"
    assert orchestrator.num_errors == 0

    # Without exact refund amount and timing disclosure, cancellation is blocked pre-dispatch.
    trajectory, cancel_call = _setup_cancel()
    trajectory[16]["content"] = (
        "To cancel order #W2378156 because it is no longer needed. "
        "Please confirm."
    )
    results, environment, orchestrator = _dispatch(trajectory, cancel_call)
    assert len(results) == 1 and results[0].error
    assert environment.calls == []
    assert "AWA_PREWRITE_NO_GO" in (results[0].content or "")
    assert orchestrator.num_errors == 1

    # A valid pending-order address change must pass through the actual dispatcher.
    trajectory, address_call = _setup_address()
    results, environment, orchestrator = _dispatch(trajectory, address_call)
    assert len(results) == 1 and not results[0].error
    assert environment.calls == ["modify_pending_order_address"]
    assert results[0].content == "SIMULATED_WRITE_EXECUTED"
    assert orchestrator.num_errors == 0

    # A missing address detail must block before the environment callback.
    trajectory, address_call = _setup_address()
    trajectory[16]["content"] = (
        "To confirm order #W2378156, change the shipping address to 100 Main Street, "
        "Unit 4, Boston, MA, USA. Please confirm."
    )
    results, environment, orchestrator = _dispatch(trajectory, address_call)
    assert len(results) == 1 and results[0].error
    assert environment.calls == []
    assert "AWA_PREWRITE_NO_GO" in (results[0].content or "")
    assert orchestrator.num_errors == 1

    # A valid pending-order payment-method change must pass through the actual dispatcher.
    trajectory, payment_call = _setup_payment()
    results, environment, orchestrator = _dispatch(trajectory, payment_call)
    assert len(results) == 1 and not results[0].error
    assert environment.calls == ["modify_pending_order_payment"]
    assert results[0].content == "SIMULATED_WRITE_EXECUTED"
    assert orchestrator.num_errors == 0

    # A payment-method change without exact method disclosure is blocked pre-dispatch.
    trajectory, payment_call = _setup_payment()
    trajectory[18]["content"] = (
        "For order #W2378156, change the payment method. Please confirm."
    )
    results, environment, orchestrator = _dispatch(trajectory, payment_call)
    assert len(results) == 1 and results[0].error
    assert environment.calls == []
    assert "AWA_PREWRITE_NO_GO" in (results[0].content or "")
    assert orchestrator.num_errors == 1

    # A valid pending-order item modification must pass through the actual dispatcher.
    trajectory, pending_items_call = _setup_pending_items()
    results, environment, orchestrator = _dispatch(trajectory, pending_items_call)
    assert len(results) == 1 and not results[0].error
    assert environment.calls == ["modify_pending_order_items"]
    assert results[0].content == "SIMULATED_WRITE_EXECUTED"
    assert orchestrator.num_errors == 0

    # Missing exact price disclosure blocks pending item modification.
    trajectory, pending_items_call = _setup_pending_items()
    trajectory[16]["content"] = (
        "To confirm order #W2378156, exchange the selected items and use "
        "credit_card_9513926. Please confirm."
    )
    results, environment, orchestrator = _dispatch(trajectory, pending_items_call)
    assert len(results) == 1 and results[0].error
    assert environment.calls == []
    assert "AWA_PREWRITE_NO_GO" in (results[0].content or "")
    assert orchestrator.num_errors == 1

    # A verified user default-address change must pass through the actual dispatcher.
    trajectory, user_address_call = _setup_user_address()
    results, environment, orchestrator = _dispatch(trajectory, user_address_call)
    assert len(results) == 1 and not results[0].error
    assert environment.calls == ["modify_user_address"]
    assert results[0].content == "SIMULATED_WRITE_EXECUTED"
    assert orchestrator.num_errors == 0

    # Missing exact address disclosure blocks before the environment callback.
    trajectory, user_address_call = _setup_user_address()
    trajectory[18]["content"] = "For Customer Example, update your default address. Please confirm."
    results, environment, orchestrator = _dispatch(trajectory, user_address_call)
    assert len(results) == 1 and results[0].error
    assert environment.calls == []
    assert "AWA_PREWRITE_NO_GO" in (results[0].content or "")
    assert orchestrator.num_errors == 1

    # A valid delivered-item return request must pass through the actual dispatcher.
    trajectory, return_call = _setup_return()
    results, environment, orchestrator = _dispatch(trajectory, return_call)
    assert len(results) == 1 and not results[0].error
    assert environment.calls == ["return_delivered_order_items"]
    assert results[0].content == "SIMULATED_WRITE_EXECUTED"
    assert orchestrator.num_errors == 0

    # Missing return-process disclosure blocks before the environment callback.
    trajectory, return_call = _setup_return()
    trajectory[18]["content"] = (
        "For order #W2378156, request return of item 1151293680 using "
        "credit_card_9513926. Please confirm."
    )
    results, environment, orchestrator = _dispatch(trajectory, return_call)
    assert len(results) == 1 and results[0].error
    assert environment.calls == []
    assert "AWA_PREWRITE_NO_GO" in (results[0].content or "")
    assert orchestrator.num_errors == 1
    print("PASS: all seven pinned retail write policies enforce GO/NO_GO through the actual dispatcher; same-batch duplicate blocking is verified.")


if __name__ == "__main__":
    main()
