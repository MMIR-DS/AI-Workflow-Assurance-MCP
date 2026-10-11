"""Install a narrowly scoped guard into the pinned Tau2 orchestrator source."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

EXPECTED_TAU2_COMMIT = "4ce7c0397c1eb65c9bbe59aeacfe1ca44a1cd699"
PATCH_MARKER = "AWA_PREWRITE_GUARD_PATCH_V2"

ORIGINAL = """        tool_results = []
        for tool_call in tool_calls:
            tool_result = self.environment.get_response(tool_call)
            if tool_result.error:
                self.num_errors += 1
            tool_results.append(tool_result)
        return tool_results"""

REPLACEMENT = """        tool_results = []
        # One dispatch batch is evaluated against one trajectory snapshot. Never
        # allow two writes for the same order to reuse that snapshot.
        awa_write_orders_seen = set()
        for tool_call in tool_calls:
            # AWA_PREWRITE_GUARD_PATCH_V2: fail closed for every retail write tool.
            awa_write_tools = {
                "cancel_pending_order",
                "exchange_delivered_order_items",
                "modify_pending_order_address",
                "modify_pending_order_items",
                "modify_pending_order_payment",
                "modify_user_address",
                "return_delivered_order_items",
            }
            if tool_call.name in awa_write_tools:
                if tool_call.name == "exchange_delivered_order_items":
                    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_prewrite

                    raw_order_id = (
                        tool_call.arguments.get("order_id")
                        if isinstance(tool_call.arguments, dict)
                        else None
                    )
                    normalized_order_id = (
                        raw_order_id.casefold()
                        if isinstance(raw_order_id, str) and raw_order_id
                        else None
                    )
                    if normalized_order_id and normalized_order_id in awa_write_orders_seen:
                        tool_result = ToolMessage(
                            id=tool_call.id,
                            role="tool",
                            requestor=tool_call.requestor,
                            error=True,
                            content=(
                                "AWA_PREWRITE_NO_GO: a second write for the same order "
                                "in one dispatch batch is blocked. Re-read the order and "
                                "retry in a new turn."
                            ),
                        )
                    else:
                        if normalized_order_id:
                            # Reserve even on NO_GO: a second same-order action in this
                            # batch must wait for a new trajectory/snapshot.
                            awa_write_orders_seen.add(normalized_order_id)
                        preflight = evaluate_tau2_prewrite(self.trajectory, tool_call)
                        if preflight["decision"] == "GO":
                            tool_result = self.environment.get_response(tool_call)
                        else:
                            blocking = ", ".join(preflight["blocking_checks"]) or "unspecified"
                            tool_result = ToolMessage(
                                id=tool_call.id,
                                role="tool",
                                requestor=tool_call.requestor,
                                error=True,
                                content=(
                                    "AWA_PREWRITE_NO_GO: exchange blocked before execution. "
                                    f"Blocking checks: {blocking}. Ask the customer to confirm "
                                    "the exact order, old/new item IDs, and payment method, then retry."
                                ),
                            )
                elif tool_call.name == "modify_pending_order_address":
                    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_address_prewrite

                    raw_order_id = (
                        tool_call.arguments.get("order_id")
                        if isinstance(tool_call.arguments, dict)
                        else None
                    )
                    normalized_order_id = (
                        raw_order_id.casefold()
                        if isinstance(raw_order_id, str) and raw_order_id
                        else None
                    )
                    if normalized_order_id and normalized_order_id in awa_write_orders_seen:
                        tool_result = ToolMessage(
                            id=tool_call.id,
                            role="tool",
                            requestor=tool_call.requestor,
                            error=True,
                            content=(
                                "AWA_PREWRITE_NO_GO: a second write for the same order "
                                "in one dispatch batch is blocked. Re-read the order and "
                                "retry in a new turn."
                            ),
                        )
                    else:
                        if normalized_order_id:
                            awa_write_orders_seen.add(normalized_order_id)
                        preflight = evaluate_tau2_address_prewrite(self.trajectory, tool_call)
                        if preflight["decision"] == "GO":
                            tool_result = self.environment.get_response(tool_call)
                        else:
                            blocking = ", ".join(preflight["blocking_checks"]) or "unspecified"
                            tool_result = ToolMessage(
                                id=tool_call.id,
                                role="tool",
                                requestor=tool_call.requestor,
                                error=True,
                                content=(
                                    "AWA_PREWRITE_NO_GO: address change blocked before execution. "
                                    f"Blocking checks: {blocking}. Disclose the exact new address "
                                    "and obtain fresh confirmation before retrying."
                                ),
                            )
                elif tool_call.name == "modify_user_address":
                    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_user_address_prewrite

                    raw_user_id = (
                        tool_call.arguments.get("user_id")
                        if isinstance(tool_call.arguments, dict)
                        else None
                    )
                    normalized_user_id = (
                        "user:" + raw_user_id.casefold()
                        if isinstance(raw_user_id, str) and raw_user_id
                        else None
                    )
                    if normalized_user_id and normalized_user_id in awa_write_orders_seen:
                        tool_result = ToolMessage(
                            id=tool_call.id,
                            role="tool",
                            requestor=tool_call.requestor,
                            error=True,
                            content=(
                                "AWA_PREWRITE_NO_GO: a second write for the same user "
                                "in one dispatch batch is blocked. Re-read the user profile "
                                "and retry in a new turn."
                            ),
                        )
                    else:
                        if normalized_user_id:
                            awa_write_orders_seen.add(normalized_user_id)
                        preflight = evaluate_tau2_user_address_prewrite(self.trajectory, tool_call)
                        if preflight["decision"] == "GO":
                            tool_result = self.environment.get_response(tool_call)
                        else:
                            blocking = ", ".join(preflight["blocking_checks"]) or "unspecified"
                            tool_result = ToolMessage(
                                id=tool_call.id,
                                role="tool",
                                requestor=tool_call.requestor,
                                error=True,
                                content=(
                                    "AWA_PREWRITE_NO_GO: user default-address change blocked before "
                                    "execution. Disclose the exact new address and obtain fresh "
                                    f"confirmation. Blocking checks: {blocking}."
                                ),
                            )
                elif tool_call.name == "modify_pending_order_items":
                    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_pending_items_prewrite

                    raw_order_id = (
                        tool_call.arguments.get("order_id")
                        if isinstance(tool_call.arguments, dict)
                        else None
                    )
                    normalized_order_id = (
                        raw_order_id.casefold()
                        if isinstance(raw_order_id, str) and raw_order_id
                        else None
                    )
                    if normalized_order_id and normalized_order_id in awa_write_orders_seen:
                        tool_result = ToolMessage(
                            id=tool_call.id,
                            role="tool",
                            requestor=tool_call.requestor,
                            error=True,
                            content=(
                                "AWA_PREWRITE_NO_GO: a second write for the same order "
                                "in one dispatch batch is blocked. Re-read the order and "
                                "retry in a new turn."
                            ),
                        )
                    else:
                        if normalized_order_id:
                            awa_write_orders_seen.add(normalized_order_id)
                        preflight = evaluate_tau2_pending_items_prewrite(self.trajectory, tool_call)
                        if preflight["decision"] == "GO":
                            tool_result = self.environment.get_response(tool_call)
                        else:
                            blocking = ", ".join(preflight["blocking_checks"]) or "unspecified"
                            tool_result = ToolMessage(
                                id=tool_call.id,
                                role="tool",
                                requestor=tool_call.requestor,
                                error=True,
                                content=(
                                    "AWA_PREWRITE_NO_GO: pending item modification blocked before "
                                    "execution. Disclose the exact old/new item IDs, price delta, "
                                    "payment method, and obtain fresh confirmation."
                                    f" Blocking checks: {blocking}."
                                ),
                            )
                elif tool_call.name == "modify_pending_order_payment":
                    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_payment_prewrite

                    raw_order_id = (
                        tool_call.arguments.get("order_id")
                        if isinstance(tool_call.arguments, dict)
                        else None
                    )
                    normalized_order_id = (
                        raw_order_id.casefold()
                        if isinstance(raw_order_id, str) and raw_order_id
                        else None
                    )
                    if normalized_order_id and normalized_order_id in awa_write_orders_seen:
                        tool_result = ToolMessage(
                            id=tool_call.id,
                            role="tool",
                            requestor=tool_call.requestor,
                            error=True,
                            content=(
                                "AWA_PREWRITE_NO_GO: a second write for the same order "
                                "in one dispatch batch is blocked. Re-read the order and "
                                "retry in a new turn."
                            ),
                        )
                    else:
                        if normalized_order_id:
                            awa_write_orders_seen.add(normalized_order_id)
                        preflight = evaluate_tau2_payment_prewrite(self.trajectory, tool_call)
                        if preflight["decision"] == "GO":
                            tool_result = self.environment.get_response(tool_call)
                        else:
                            blocking = ", ".join(preflight["blocking_checks"]) or "unspecified"
                            tool_result = ToolMessage(
                                id=tool_call.id,
                                role="tool",
                                requestor=tool_call.requestor,
                                error=True,
                                content=(
                                    "AWA_PREWRITE_NO_GO: payment-method change blocked before "
                                    "execution. Disclose the exact current and new payment "
                                    "methods and obtain fresh confirmation."
                                    f" Blocking checks: {blocking}."
                                ),
                            )
                elif tool_call.name == "cancel_pending_order":
                    from ai_workflow_assurance_mcp.tau2_prewrite import evaluate_tau2_cancel_prewrite

                    raw_order_id = (
                        tool_call.arguments.get("order_id")
                        if isinstance(tool_call.arguments, dict)
                        else None
                    )
                    normalized_order_id = (
                        raw_order_id.casefold()
                        if isinstance(raw_order_id, str) and raw_order_id
                        else None
                    )
                    if normalized_order_id and normalized_order_id in awa_write_orders_seen:
                        tool_result = ToolMessage(
                            id=tool_call.id,
                            role="tool",
                            requestor=tool_call.requestor,
                            error=True,
                            content=(
                                "AWA_PREWRITE_NO_GO: a second write for the same order "
                                "in one dispatch batch is blocked. Re-read the order and "
                                "retry in a new turn."
                            ),
                        )
                    else:
                        if normalized_order_id:
                            awa_write_orders_seen.add(normalized_order_id)
                        preflight = evaluate_tau2_cancel_prewrite(self.trajectory, tool_call)
                        if preflight["decision"] == "GO":
                            tool_result = self.environment.get_response(tool_call)
                        else:
                            blocking = ", ".join(preflight["blocking_checks"]) or "unspecified"
                            tool_result = ToolMessage(
                                id=tool_call.id,
                                role="tool",
                                requestor=tool_call.requestor,
                                error=True,
                                content=(
                                    "AWA_PREWRITE_NO_GO: cancellation blocked before execution. "
                                    f"Blocking checks: {blocking}. Disclose the exact cancellation "
                                    "reason, refund amount, payment method, and refund timing, "
                                    "then obtain fresh confirmation."
                                ),
                            )
                else:
                    tool_result = ToolMessage(
                        id=tool_call.id,
                        role="tool",
                        requestor=tool_call.requestor,
                        error=True,
                        content=(
                            "AWA_PREWRITE_NO_GO: this retail write tool has no reviewed "
                            "AWA policy adapter and is blocked before execution."
                        ),
                    )
            else:
                tool_result = self.environment.get_response(tool_call)
            if tool_result.error:
                self.num_errors += 1
            tool_results.append(tool_result)
        return tool_results"""


def patch_orchestrator_source(source: str) -> str:
    """Patch only the expected dispatch loop; reject unknown source layouts."""
    if PATCH_MARKER in source:
        return source
    if source.count(ORIGINAL) != 1:
        raise ValueError(
            "Expected exactly one unmodified Tau2 tool-dispatch loop; "
            "the upstream source may have changed. Refusing to patch."
        )
    return source.replace(ORIGINAL, REPLACEMENT, 1)


def install(tau2_root: Path) -> Path:
    """Verify the pinned checkout and install the guard into its orchestrator."""
    revision = subprocess.run(
        ["git", "-C", str(tau2_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if revision != EXPECTED_TAU2_COMMIT:
        raise RuntimeError(
            f"Unexpected Tau2 revision {revision}; expected {EXPECTED_TAU2_COMMIT}. "
            "Refusing to patch an unreviewed source version."
        )

    target = tau2_root / "src" / "tau2" / "orchestrator" / "orchestrator.py"
    original_source = target.read_text(encoding="utf-8")
    patched_source = patch_orchestrator_source(original_source)
    if patched_source != original_source:
        target.write_text(patched_source, encoding="utf-8")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tau2-root", type=Path, required=True)
    args = parser.parse_args()
    path = install(args.tau2_root.resolve())
    print(f"Installed {PATCH_MARKER} in {path}")


if __name__ == "__main__":
    main()
