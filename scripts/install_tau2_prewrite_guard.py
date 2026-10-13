"""Install a narrowly scoped guard into the pinned Tau2 orchestrator source."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

EXPECTED_TAU2_COMMIT = "4ce7c0397c1eb65c9bbe59aeacfe1ca44a1cd699"
PATCH_MARKER = "AWA_PREWRITE_GUARD_PATCH_V6"
REPLAY_PATCH_MARKER = "AWA_PREWRITE_REPLAY_NOOP_V1"

REPLAY_ORIGINAL = """            if not self._is_mutating_tool(tool_call.name):
                continue
            response = self.get_response(tool_call)
            try:
                content = json.loads(response.content)"""

REPLAY_REPLACEMENT = """            if not self._is_mutating_tool(tool_call.name):
                continue
            # AWA_PREWRITE_REPLAY_NOOP_V1: denied writes must be replayed as no-ops.
            recorded_content = expected_response.content
            if (
                expected_response.error
                and isinstance(recorded_content, str)
                and recorded_content.startswith("AWA_PREWRITE_NO_GO:")
            ):
                logger.debug("Skipping AWA-blocked mutating tool during evaluator replay.")
                continue
            response = self.get_response(tool_call)
            try:
                content = json.loads(response.content)"""
ORIGINAL = """        tool_results = []
        for tool_call in tool_calls:
            tool_result = self.environment.get_response(tool_call)
            if tool_result.error:
                self.num_errors += 1
            tool_results.append(tool_result)
        return tool_results"""

REPLACEMENT = """        tool_results = []
        # One dispatch batch is evaluated against one trajectory snapshot.
        awa_write_orders_seen = set()

        # Import shared policy once per dispatch method, then classify every
        # mutating tool through this single reviewed table.
        from ai_workflow_assurance_mcp.tau2_constants import WRITE_TOOLS as awa_shared_write_tools
        from ai_workflow_assurance_mcp.tau2_constants import TAU2_PASSTHROUGH_TOOLS as awa_shared_passthrough_tools
        from ai_workflow_assurance_mcp.tau2_prewrite import (
            evaluate_tau2_prewrite,
            evaluate_tau2_address_prewrite,
            evaluate_tau2_user_address_prewrite,
            evaluate_tau2_payment_prewrite,
            evaluate_tau2_cancel_prewrite,
            evaluate_tau2_return_prewrite,
        )

        def awa_blocked_result(tool_call, message):
            return ToolMessage(
                id=tool_call.id,
                role="tool",
                requestor=tool_call.requestor,
                error=True,
                content=message,
            )

        def awa_duplicate_message(entity_kind):
            if entity_kind == "user":
                return (
                    "AWA_PREWRITE_NO_GO: a second write for the same user in one "
                    "dispatch batch is blocked. Re-read the user profile and retry "
                    "in a new turn."
                )
            return (
                "AWA_PREWRITE_NO_GO: a second write for the same order in one "
                "dispatch batch is blocked. Re-read the order and retry in a new turn."
            )

        # validator=None is intentional only for the permanently disabled
        # pending-order item mutation path. It remains fail-closed until a
        # transactional executor and independent per-item verification exist.
        awa_write_policies = {
            "exchange_delivered_order_items": {
                "validator": evaluate_tau2_prewrite,
                "entity_argument": "order_id",
                "entity_kind": "order",
                "blocked_message": (
                    "AWA_PREWRITE_NO_GO: exchange blocked before execution. "
                    "Blocking checks: {blocking}. Do not repeat the write attempt. "
                    "Check every named replacement item against the latest catalog response; "
                    "if any option was described incorrectly, correct it and select a variant "
                    "whose actual options match the customer's request. The disclosure must "
                    "include the exact order ID, every old-to-new item pair, payment method ID, "
                    "and a labeled price difference with refund/charge direction. Ask for fresh "
                    "confirmation only after correcting all issues."
                ),
            },
            "modify_pending_order_address": {
                "validator": evaluate_tau2_address_prewrite,
                "entity_argument": "order_id",
                "entity_kind": "order",
                "blocked_message": (
                    "AWA_PREWRITE_NO_GO: address change blocked before execution. "
                    "Blocking checks: {blocking}. Disclose the exact new address "
                    "and obtain fresh confirmation before retrying."
                ),
            },
            "modify_user_address": {
                "validator": evaluate_tau2_user_address_prewrite,
                "entity_argument": "user_id",
                "entity_prefix": "user:",
                "entity_kind": "user",
                "blocked_message": (
                    "AWA_PREWRITE_NO_GO: user default-address change blocked before "
                    "execution. Disclose the exact new address and obtain fresh "
                    "confirmation. Blocking checks: {blocking}."
                ),
            },
            "modify_pending_order_items": {
                "validator": None,
                "entity_argument": "order_id",
                "entity_kind": "order",
                "disabled_message": (
                    "AWA_PREWRITE_NO_GO: pending-order item modification is disabled "
                    "before execution. Public reports describe a possible Tau2 bug "
                    "that can copy the final replacement variant's price/options to "
                    "other items in a multi-item update. The pinned executor has not "
                    "passed independent per-item post-state verification; no write "
                    "was executed."
                ),
            },
            "modify_pending_order_payment": {
                "validator": evaluate_tau2_payment_prewrite,
                "entity_argument": "order_id",
                "entity_kind": "order",
                "blocked_message": (
                    "AWA_PREWRITE_NO_GO: payment-method change blocked before "
                    "execution. Disclose the exact current and new payment methods "
                    "and obtain fresh confirmation. Blocking checks: {blocking}."
                ),
            },
            "cancel_pending_order": {
                "validator": evaluate_tau2_cancel_prewrite,
                "entity_argument": "order_id",
                "entity_kind": "order",
                "blocked_message": (
                    "AWA_PREWRITE_NO_GO: cancellation blocked before execution. "
                    "Blocking checks: {blocking}. Disclose the exact cancellation "
                    "reason, refund amount, payment method, and refund timing, then "
                    "obtain fresh confirmation."
                ),
            },
            "return_delivered_order_items": {
                "validator": evaluate_tau2_return_prewrite,
                "entity_argument": "order_id",
                "entity_kind": "order",
                "blocked_message": (
                    "AWA_PREWRITE_NO_GO: return request blocked before execution. "
                    "Disclose the exact return items, payment method, and follow-up "
                    "process, then obtain fresh confirmation. Blocking checks: {blocking}."
                ),
            },
        }

        # New-order creation has no reviewed policy. Including it in the write set
        # ensures it is denied by the same default-deny branch as future mutations.
        awa_write_tools = set(awa_shared_write_tools) | {"create_order"}
        awa_passthrough_tools = set(awa_shared_passthrough_tools)

        for tool_call in tool_calls:
            # AWA_PREWRITE_GUARD_PATCH_V6: new/renamed tools are denied by default.
            if tool_call.name in awa_write_tools:
                policy = awa_write_policies.get(tool_call.name)
                if policy is None:
                    tool_result = awa_blocked_result(
                        tool_call,
                        "AWA_PREWRITE_NO_GO: this retail write tool has no reviewed "
                        "AWA policy adapter and is blocked before execution.",
                    )
                else:
                    arguments = (
                        tool_call.arguments
                        if isinstance(tool_call.arguments, dict)
                        else {}
                    )
                    raw_entity_id = arguments.get(policy["entity_argument"])
                    normalized_entity_id = (
                        raw_entity_id.casefold()
                        if isinstance(raw_entity_id, str) and raw_entity_id
                        else None
                    )
                    if normalized_entity_id and policy.get("entity_prefix"):
                        normalized_entity_id = (
                            policy["entity_prefix"] + normalized_entity_id
                        )

                    if (
                        normalized_entity_id
                        and normalized_entity_id in awa_write_orders_seen
                    ):
                        tool_result = awa_blocked_result(
                            tool_call,
                            awa_duplicate_message(policy["entity_kind"]),
                        )
                    else:
                        if normalized_entity_id:
                            # Reserve the entity even on NO_GO so another mutation in
                            # this batch cannot reuse the same pre-write snapshot.
                            awa_write_orders_seen.add(normalized_entity_id)

                        if policy.get("disabled_message"):
                            tool_result = awa_blocked_result(
                                tool_call,
                                policy["disabled_message"],
                            )
                        else:
                            preflight = policy["validator"](
                                self.trajectory,
                                tool_call,
                            )
                            if preflight["decision"] == "GO":
                                tool_result = self.environment.get_response(tool_call)
                            else:
                                blocking = (
                                    ", ".join(preflight["blocking_checks"])
                                    or "unspecified"
                                )
                                tool_result = awa_blocked_result(
                                    tool_call,
                                    policy["blocked_message"].format(
                                        blocking=blocking
                                    ),
                                )
            elif tool_call.name in awa_passthrough_tools:
                tool_result = self.environment.get_response(tool_call)
            else:
                tool_result = awa_blocked_result(
                    tool_call,
                    "AWA_PREWRITE_NO_GO: unrecognized or unreviewed tool name is "
                    "blocked before execution. Add it to the explicit passthrough "
                    "allowlist or give it a reviewed operation-specific write policy.",
                )

            if tool_result.error:
                self.num_errors += 1
            tool_results.append(tool_result)
        return tool_results"""


def patch_orchestrator_source(source: str) -> str:
    """Patch only the expected dispatch loop and verify idempotent installations."""
    if PATCH_MARKER in source:
        if (
            source.count(PATCH_MARKER) != 1
            or source.count(REPLACEMENT) != 1
            or ORIGINAL in source
        ):
            raise ValueError(
                "Found the AWA patch marker, but the complete reviewed dispatcher "
                "replacement is not intact. Refusing to trust a partial or modified guard."
            )
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
