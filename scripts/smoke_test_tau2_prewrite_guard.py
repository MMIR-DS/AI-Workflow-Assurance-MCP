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
        "and old item 4983901480 for 7747408585. Use payment method "
        "credit_card_9513926 for any price difference. Please confirm."
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
        "and old item 4983901480 for 7747408585. Use payment method "
        "credit_card_9513926 for any price difference. Please confirm."
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

    # Every write tool without its own reviewed adapter must be denied before dispatch.
    unsupported_write_tools = [
        "cancel_pending_order",
        "modify_pending_order_address",
        "modify_pending_order_items",
        "modify_pending_order_payment",
        "modify_user_address",
        "return_delivered_order_items",
    ]
    for index, tool_name in enumerate(unsupported_write_tools):
        trajectory, _ = _setup()
        unsupported_write = ToolCall(
            id=f"unsupported-write-{index:03d}",
            name=tool_name,
            arguments={"order_id": "#W2378156"},
            requestor="assistant",
        )
        results, environment, orchestrator = _dispatch(trajectory, unsupported_write)
        assert len(results) == 1 and results[0].error, tool_name
        assert environment.calls == [], f"{tool_name} must not reach the environment"
        assert "no reviewed AWA policy adapter" in (results[0].content or ""), tool_name
        assert orchestrator.num_errors == 1, tool_name
    print("PASS: exchange GO/NO_GO, same-batch duplicate blocking, and default-deny for all six unsupported retail writes.")


if __name__ == "__main__":
    main()
