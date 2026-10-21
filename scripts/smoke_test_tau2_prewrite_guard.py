"""No-model smoke test for the patched Tau2 write-dispatch method.

Run inside the pinned Tau2 virtual environment after applying the source patch:
PYTHONPATH=../src uv run python ../scripts/smoke_test_tau2_prewrite_guard.py
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from tau2.data_model.message import AssistantMessage, ToolCall, ToolMessage
from tau2.domains.retail.environment import get_environment
from tau2.orchestrator.orchestrator import BaseOrchestrator

from ai_workflow_assurance_mcp.tau2_constants import (
    TAU2_PASSTHROUGH_TOOLS,
    WRITE_TOOLS,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "tau2_task0_trace_minimal.json"


class CountingEnvironment:
    def __init__(self, response_overrides: dict[str, str] | None = None) -> None:
        self.calls: list[str] = []
        self.response_overrides = response_overrides or {}

    def get_response(self, tool_call: ToolCall) -> ToolMessage:
        self.calls.append(tool_call.name)
        return ToolMessage(
            id=tool_call.id,
            role="tool",
            requestor=tool_call.requestor,
            content=self.response_overrides.get(tool_call.id, "SIMULATED_WRITE_EXECUTED"),
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


def _dispatch(
    trajectory: list[dict[str, Any]],
    call: ToolCall,
    response_overrides: dict[str, str] | None = None,
) -> tuple[list[ToolMessage], CountingEnvironment, Any]:
    return _dispatch_many(trajectory, [call], response_overrides)


def _dispatch_many(
    trajectory: list[dict[str, Any]],
    calls: list[ToolCall],
    response_overrides: dict[str, str] | None = None,
) -> tuple[list[ToolMessage], CountingEnvironment, Any]:
    environment = CountingEnvironment(response_overrides)
    orchestrator = SimpleNamespace(environment=environment, trajectory=trajectory, num_errors=0)
    results = BaseOrchestrator._execute_tool_calls(orchestrator, calls)
    return results, environment, orchestrator



def _setup_retry_after_no_go(
    *, disclosure: str | None, confirmation: str | None
) -> tuple[list[dict[str, Any]], ToolCall]:
    """Build a second exchange attempt after a recorded AWA denial."""
    trajectory, first_call = _setup()
    trajectory.append({
        "role": "tool",
        "id": first_call.id,
        "requestor": "assistant",
        "error": True,
        "content": "AWA_PREWRITE_NO_GO: the previous exchange was blocked before execution.",
    })
    if disclosure is not None:
        trajectory.append({"role": "assistant", "content": disclosure})
    if confirmation is not None:
        trajectory.append({"role": "user", "content": confirmation})

    retry_call = ToolCall(
        id="retry-after-no-go",
        name=first_call.name,
        arguments=dict(first_call.arguments),
        requestor="assistant",
    )
    trajectory.append({
        "role": "assistant",
        "tool_calls": [{
            "id": retry_call.id,
            "name": retry_call.name,
            "arguments": retry_call.arguments,
        }],
    })
    return trajectory, retry_call


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


def _setup_pending_items(*, single_item: bool = False) -> tuple[list[dict[str, Any]], ToolCall]:
    trajectory, _ = _setup()
    order_result = next(
        message for message in trajectory
        if message.get("role") == "tool" and message.get("id") == "order-read-1"
    )
    order = json.loads(order_result["content"])
    order["status"] = "pending"
    order_result["content"] = json.dumps(order)
    old_items = ["1151293680"] if single_item else ["1151293680", "4983901480"]
    new_items = ["7706410293"] if single_item else ["7706410293", "7747408585"]
    pairs = (
        "exchange old item 1151293680 for 7706410293"
        if single_item else
        "exchange old item 1151293680 for 7706410293 and old item 4983901480 for 7747408585"
    )
    refund = "$3.17" if single_item else "$16.63"
    raw_call = {
        "id": "pending-items-call-001",
        "name": "modify_pending_order_items",
        "arguments": {
            "order_id": "#W2378156",
            "item_ids": old_items,
            "new_item_ids": new_items,
            "payment_method_id": "credit_card_9513926",
        },
    }
    trajectory[-1]["tool_calls"] = [raw_call]
    trajectory[16]["content"] = (
        f"To confirm order #W2378156: {pairs}. The total price difference is "
        f"a {refund} refund to credit_card_9513926. Please confirm."
    )
    trajectory[17]["content"] = "Yes, that's correct. Please proceed with the item update."
    call = ToolCall(
        id=raw_call["id"],
        name=raw_call["name"],
        arguments=raw_call["arguments"],
        requestor="assistant",
    )
    return trajectory, call


def _single_item_postwrite_snapshot(
    trajectory: list[dict[str, Any]], call: ToolCall
) -> dict[str, Any]:
    order_result = next(
        message for message in trajectory
        if message.get("role") == "tool" and message.get("id") == "order-read-1"
    )
    order = json.loads(order_result["content"])
    catalog_result = next(
        message for message in trajectory
        if message.get("role") == "tool" and message.get("id") == "keyboard-product-1"
    )
    catalog = json.loads(catalog_result["content"])
    old_item_id = call.arguments["item_ids"][0]
    new_item_id = call.arguments["new_item_ids"][0]
    old_rows = [item for item in order["items"] if item.get("item_id") == old_item_id]
    if len(old_rows) != 1:
        raise AssertionError("The fake pre-write order must contain exactly one selected old item.")
    variant = catalog.get("variants", {}).get(new_item_id)
    if not isinstance(variant, dict):
        raise AssertionError("The fake catalog does not contain the requested replacement variant.")
    row = old_rows[0]
    row["item_id"] = new_item_id
    row["product_id"] = catalog["product_id"]
    row["price"] = variant["price"]
    row["options"] = variant["options"]
    order["status"] = "pending (item modified)"
    return order


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


def _assert_pinned_tool_coverage() -> None:
    """Fail if a pinned Tau2 tool is neither explicitly allowed nor classified as a write."""
    environment = get_environment()
    toolkit = environment.tools
    if toolkit is None:
        raise AssertionError("Pinned Tau2 retail environment has no toolkit.")
    actual_names = set(toolkit.get_tools())
    classified_names = set(WRITE_TOOLS) | set(TAU2_PASSTHROUGH_TOOLS)
    missing = sorted(actual_names - classified_names)
    if missing:
        raise AssertionError(
            "Pinned Tau2 retail tools lack an explicit AWA dispatcher classification: "
            f"{missing}"
        )

    actual_mutating = {
        name for name in actual_names if toolkit.tool_mutates_state(name)
    }
    unreviewed_mutating = sorted(actual_mutating - set(WRITE_TOOLS))
    falsely_classified_nonmutating = sorted(set(WRITE_TOOLS) & actual_names - actual_mutating)
    if unreviewed_mutating:
        raise AssertionError(
            f"Tau2 marks unclassified AWA tools as state-mutating: {unreviewed_mutating}"
        )
    if falsely_classified_nonmutating:
        raise AssertionError(
            "The shared AWA write inventory includes pinned tools Tau2 does not mark "
            f"state-mutating: {falsely_classified_nonmutating}"
        )

    print(
        "PASS: pinned Tau2 retail toolkit classification covers "
        f"{len(actual_names)} tools ({len(actual_mutating)} mutating)."
    )


def main() -> None:
    _assert_pinned_tool_coverage()
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

    # A previous AWA_PREWRITE_NO_GO invalidates the old disclosure/confirmation.
    trajectory, retry_call = _setup_retry_after_no_go(disclosure=None, confirmation=None)
    results, environment, orchestrator = _dispatch(trajectory, retry_call)
    assert len(results) == 1 and results[0].error
    assert environment.calls == [], "replayed confirmation must not execute a retry"
    assert "user_reconfirmed_after_latest_blocked_attempt" in (results[0].content or "")
    assert orchestrator.num_errors == 1

    # A new affirmative reply is insufficient when the new disclosure is incomplete.
    trajectory, retry_call = _setup_retry_after_no_go(
        disclosure="To confirm order #W2378156, please proceed with the exchange.",
        confirmation="Yes, I confirm.",
    )
    results, environment, orchestrator = _dispatch(trajectory, retry_call)
    assert len(results) == 1 and results[0].error
    assert environment.calls == [], "incomplete re-disclosure must not execute a retry"
    assert "complete_customer_facing_exchange_disclosure" in (results[0].content or "")
    assert orchestrator.num_errors == 1

    # Even a complete new disclosure and affirmative reply cannot clear a prior NO_GO
    # within the same benchmark episode. Reuse the same orchestrator across dispatch batches.
    trajectory, first_call = _setup()
    first_results, environment, orchestrator = _dispatch(trajectory, first_call)
    assert len(first_results) == 1 and first_results[0].error
    assert environment.calls == []
    assert getattr(orchestrator, "_awa_prewrite_no_go_latched", False)

    trajectory.append({
        "role": "tool",
        "id": first_call.id,
        "requestor": "assistant",
        "error": True,
        "content": first_results[0].content,
    })
    disclosure = (
        "To confirm order #W2378156: exchange old item 1151293680 for 7706410293 "
        "and old item 4983901480 for 7747408585. The total price difference is "
        "a $16.63 refund to credit_card_9513926. Please confirm."
    )
    confirmation = (
        "Yes, that's correct. Go ahead and use credit_card_9513926 for this exchange."
    )
    trajectory.append({"role": "assistant", "content": disclosure})
    trajectory.append({"role": "user", "content": confirmation})
    retry_call = ToolCall(
        id="sticky-no-go-retry",
        name=first_call.name,
        arguments=dict(first_call.arguments),
        requestor="assistant",
    )
    trajectory.append({
        "role": "assistant",
        "tool_calls": [{
            "id": retry_call.id,
            "name": retry_call.name,
            "arguments": retry_call.arguments,
        }],
    })
    results = BaseOrchestrator._execute_tool_calls(orchestrator, [retry_call])
    assert len(results) == 1 and results[0].error
    assert environment.calls == [], "a fresh confirmation must not clear the run-level NO_GO latch"
    assert "prior write was blocked earlier in this benchmark run" in (results[0].content or "")
    assert orchestrator.num_errors == 2

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

    # The shared batch reservation also blocks a different write tool on the same order.
    trajectory, cancel_call = _setup_cancel()
    _, exchange_template = _setup()
    cross_tool_exchange = ToolCall(
        id="cross-tool-same-order-exchange",
        name="exchange_delivered_order_items",
        arguments=dict(exchange_template.arguments),
        requestor="assistant",
    )
    results, environment, orchestrator = _dispatch_many(
        trajectory, [cancel_call, cross_tool_exchange]
    )
    assert len(results) == 2
    assert not results[0].error and results[1].error
    assert environment.calls == ["cancel_pending_order"]
    assert "second write for the same order" in (results[1].content or "")
    assert orchestrator.num_errors == 1

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

    # Multi-item pending changes are rejected before the environment callback.
    trajectory, pending_items_call = _setup_pending_items()
    results, environment, orchestrator = _dispatch(trajectory, pending_items_call)
    assert len(results) == 1 and results[0].error
    assert environment.calls == [], "multi-item pending writes must never reach the environment"
    assert "AWA_PREWRITE_NO_GO" in (results[0].content or "")
    assert "exactly one distinct old/new item pair" in (results[0].content or "")
    assert orchestrator.num_errors == 1

    # A single-item pending change requires both preflight GO and an independent
    # post-write catalog audit before the successful result is returned.
    trajectory, pending_items_call = _setup_pending_items(single_item=True)
    good_postwrite = _single_item_postwrite_snapshot(trajectory, pending_items_call)
    results, environment, orchestrator = _dispatch(
        trajectory, pending_items_call,
        {pending_items_call.id: json.dumps(good_postwrite)},
    )
    assert len(results) == 1 and not results[0].error
    assert environment.calls == ["modify_pending_order_items"]
    result_order = json.loads(results[0].content)
    assert sum(item.get("item_id") == "7706410293" for item in result_order["items"]) == 1
    assert orchestrator.num_errors == 0

    # A catalog mismatch is reported after execution and must never look like a
    # pre-write denial, because the mutation already happened and must not retry.
    trajectory, pending_items_call = _setup_pending_items(single_item=True)
    bad_postwrite = _single_item_postwrite_snapshot(trajectory, pending_items_call)
    bad_target = next(
        item for item in bad_postwrite["items"]
        if item.get("item_id") == "7706410293"
    )
    bad_target["price"] = 1.23
    results, environment, orchestrator = _dispatch(
        trajectory, pending_items_call,
        {pending_items_call.id: json.dumps(bad_postwrite)},
    )
    assert len(results) == 1 and results[0].error
    assert environment.calls == ["modify_pending_order_items"]
    assert "AWA_POSTWRITE_AUDIT_NOT_PASS" in (results[0].content or "")
    assert "Do not retry this write" in (results[0].content or "")
    assert "AWA_PREWRITE_NO_GO" not in (results[0].content or "")
    assert orchestrator.num_errors == 1

    # A blocked multi-item update latches NO_GO for all later writes in this run.
    trajectory, pending_items_call = _setup_pending_items()
    _, exchange_call = _setup()
    results, environment, orchestrator = _dispatch_many(
        trajectory, [pending_items_call, exchange_call]
    )
    assert len(results) == 2 and all(result.error for result in results)
    assert environment.calls == []
    assert "exactly one distinct old/new item pair" in (results[0].content or "")
    assert "prior write was blocked earlier in this benchmark run" in (results[1].content or "")
    assert orchestrator.num_errors == 2

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
    # New-order creation is a write but has no reviewed AWA policy; it must fail closed.
    trajectory, _ = _setup()
    create_order_call = ToolCall(
        id="unreviewed-create-order",
        name="create_order",
        arguments={},
        requestor="assistant",
    )
    results, environment, orchestrator = _dispatch(trajectory, create_order_call)
    assert len(results) == 1 and results[0].error
    assert environment.calls == [], "unreviewed create_order must never reach the environment"
    assert "AWA_PREWRITE_NO_GO" in (results[0].content or "")
    assert "no reviewed AWA policy adapter" in (results[0].content or "")
    assert orchestrator.num_errors == 1

    # A known read tool remains explicitly allowed through the normal dispatcher.
    trajectory, _ = _setup()
    read_call = ToolCall(
        id="known-read-only-probe",
        name="get_order_details",
        arguments={"order_id": "#W2378156"},
        requestor="assistant",
    )
    results, environment, orchestrator = _dispatch(trajectory, read_call)
    assert len(results) == 1 and not results[0].error
    assert environment.calls == ["get_order_details"]
    assert results[0].content == "SIMULATED_WRITE_EXECUTED"
    assert orchestrator.num_errors == 0

    # Unknown/new tool names are default-denied rather than falling through to environment.
    trajectory, _ = _setup()
    unknown_call = ToolCall(
        id="unknown-write-probe",
        name="future_unreviewed_write",
        arguments={"order_id": "#W2378156"},
        requestor="assistant",
    )
    results, environment, orchestrator = _dispatch(trajectory, unknown_call)
    assert len(results) == 1 and results[0].error
    assert environment.calls == [], "unreviewed tool names must never reach the environment"
    assert "AWA_PREWRITE_NO_GO" in (results[0].content or "")
    assert "unrecognized or unreviewed tool name" in (results[0].content or "")
    assert orchestrator.num_errors == 1

    # Evaluator state reconstruction must treat a recorded AWA denial as a no-op.
    # Otherwise Tau2 re-executes the mutating tool while grading and reports a
    # false infrastructure error because the environment result differs from NO_GO.
    replay_environment = get_environment()
    db_hash_before = replay_environment.get_db_hash()
    replay_call = ToolCall(
        id="replay-blocked-exchange",
        name="exchange_delivered_order_items",
        arguments={
            "order_id": "#W2378156",
            "item_ids": ["1151293680", "4983901480"],
            "new_item_ids": ["7706410293", "7747408585"],
            "payment_method_id": "credit_card_9513926",
        },
        requestor="assistant",
    )
    replay_denial = ToolMessage(
        id=replay_call.id,
        role="tool",
        requestor="assistant",
        content="AWA_PREWRITE_NO_GO: exchange blocked before execution. Blocking checks: exact_price_difference_and_direction_disclosed.",
        error=True,
    )
    replay_environment.set_state(
        initialization_data=None,
        initialization_actions=None,
        message_history=[
            AssistantMessage(role="assistant", tool_calls=[replay_call]),
            replay_denial,
        ],
        strict=True,
    )
    assert replay_environment.get_db_hash() == db_hash_before, (
        "Tau2 evaluator replay mutated DB for a tool call recorded as AWA_PREWRITE_NO_GO"
    )

    print("PASS: dispatch guard and evaluator replay both preserve NO_GO as a no-op.")


if __name__ == "__main__":
    main()
