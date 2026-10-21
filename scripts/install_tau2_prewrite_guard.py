"""Install a narrowly scoped guard into the pinned Tau2 orchestrator source."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

EXPECTED_TAU2_COMMIT = "4ce7c0397c1eb65c9bbe59aeacfe1ca44a1cd699"
PATCH_MARKER = "AWA_PREWRITE_GUARD_PATCH_V7"
REPLAY_PATCH_MARKER = "AWA_PREWRITE_REPLAY_NOOP_V1"
USER_EMPTY_RESPONSE_PATCH_MARKER = "AWA_USER_EMPTY_RESPONSE_RETRY_V1"

USER_GENERATE_ORIGINAL = """        assistant_message = generate(
            model=self.llm,
            messages=messages,
            tools=self.tools,
            call_name="user_simulator_response",
            **self.llm_args,
        )"""

USER_GENERATE_REPLACEMENT = """        # AWA_USER_EMPTY_RESPONSE_RETRY_V1: do not turn an empty provider reply
        # into an invalid UserMessage. Retry once; never synthesize user content.
        assistant_message = None
        for attempt in range(2):
            assistant_message = generate(
                model=self.llm,
                messages=messages,
                tools=self.tools,
                call_name="user_simulator_response",
                **self.llm_args,
            )
            response_content = assistant_message.content
            has_text = isinstance(response_content, str) and bool(response_content.strip())
            has_tool_calls = bool(assistant_message.tool_calls)
            if has_text or has_tool_calls:
                break
            if attempt == 0:
                logger.warning(
                    "User simulator returned an empty response with no tool calls; "
                    "retrying once without inventing user content."
                )
        if assistant_message is None or not (
            (isinstance(assistant_message.content, str) and assistant_message.content.strip())
            or bool(assistant_message.tool_calls)
        ):
            raise ValueError(
                "User simulator returned an empty response with no tool calls "
                "after one retry; refusing to synthesize a user message."
            )"""

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
            evaluate_tau2_pending_items_prewrite,
        )
        from ai_workflow_assurance_mcp.tau2_postwrite import (
            audit_tau2_single_pending_item_write_response,
        )

        def awa_blocked_result(tool_call, message):
            # Persist NO_GO for this benchmark episode. Prompt instructions alone
            # are not a reliable control against a second write attempt.
            if message.startswith("AWA_PREWRITE_NO_GO:"):
                self._awa_prewrite_no_go_latched = True
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

        def awa_audit_single_item_response(tool_call, tool_result):
            audit = audit_tau2_single_pending_item_write_response(
                self.trajectory, tool_call, tool_result
            )
            if audit.get("decision") == "PASS":
                return tool_result
            blocking = ", ".join(audit.get("blocking_checks", [])) or "unspecified"
            return ToolMessage(
                id=tool_call.id,
                role="tool",
                requestor=tool_call.requestor,
                error=True,
                content=(
                    "AWA_POSTWRITE_AUDIT_NOT_PASS: the pending-item write was already "
                    "executed, but its independent post-write audit did not PASS "
                    f"(decision={audit.get('decision')}; checks={blocking}). "
                    "Do not retry this write. Inspect the current order state."
                ),
            )

        # Pending-item mutation is restricted to one old/new pair. The pinned
        # executor has a known multi-item bug; the single-row result is audited
        # against catalog price/options and unchanged non-target rows after execution.
        awa_write_policies = {
            "exchange_delivered_order_items": {
                "validator": evaluate_tau2_prewrite,
                "entity_argument": "order_id",
                "entity_kind": "order",
                "blocked_message": (
                    "AWA_PREWRITE_NO_GO: exchange blocked before execution. "
                    "Blocking checks: {blocking}. Do not make any further write attempt "
                    "during this benchmark run, even after refreshing evidence or receiving "
                    "new confirmation. The operation remains blocked; do not describe it as "
                    "completed. Tell the customer the change was not made and hand off or "
                    "escalate rather than retrying. A later independent run may be considered "
                    "only after the root cause has been fixed."
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
                "validator": evaluate_tau2_pending_items_prewrite,
                "entity_argument": "order_id",
                "entity_kind": "order",
                "single_item_only": True,
                "blocked_message": (
                    "AWA_PREWRITE_NO_GO: pending-item modification was blocked before "
                    "execution. Exactly one old item and one replacement are supported; "
                    "multi-item mutations remain disabled. Refresh order/catalog evidence "
                    "and obtain complete fresh confirmation. Blocking checks: {blocking}."
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
            # Enforce the run-level fail-closed latch in code, not only in the prompt.
            # A prior AWA_PREWRITE_NO_GO blocks later writes even in a separate dispatch batch.
            if (
                tool_call.name in awa_write_tools
                and getattr(self, "_awa_prewrite_no_go_latched", False)
            ):
                tool_result = awa_blocked_result(
                    tool_call,
                    "AWA_PREWRITE_NO_GO: a prior write was blocked earlier in this benchmark run. "
                    "No further write attempt is permitted during this run. The operation remains "
                    "blocked; do not describe it as completed. Tell the customer the change was "
                    "not made and hand off or escalate.",
                )
            # AWA_PREWRITE_GUARD_PATCH_V7: new/renamed tools are denied by default.
            elif tool_call.name in awa_write_tools:
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

                        if policy.get("single_item_only") and not (
                            isinstance(arguments.get("item_ids"), list)
                            and len(arguments["item_ids"]) == 1
                            and isinstance(arguments["item_ids"][0], str)
                            and bool(arguments["item_ids"][0])
                            and isinstance(arguments.get("new_item_ids"), list)
                            and len(arguments["new_item_ids"]) == 1
                            and isinstance(arguments["new_item_ids"][0], str)
                            and bool(arguments["new_item_ids"][0])
                            and arguments["item_ids"][0] != arguments["new_item_ids"][0]
                        ):
                            tool_result = awa_blocked_result(
                                tool_call,
                                "AWA_PREWRITE_NO_GO: pending-item modifications support "
                                "exactly one distinct old/new item pair. Multi-item writes "
                                "remain blocked before execution; no write was executed.",
                            )
                        elif policy.get("disabled_message"):
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
                                if (
                                    tool_call.name == "modify_pending_order_items"
                                    and not tool_result.error
                                ):
                                    tool_result = awa_audit_single_item_response(
                                        tool_call, tool_result
                                    )
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


def patch_environment_replay_source(source: str) -> str:
    """Keep explicitly blocked AWA writes as no-ops during Tau2 state replay."""
    if REPLAY_PATCH_MARKER in source:
        if source.count(REPLAY_PATCH_MARKER) != 1 or source.count(REPLAY_REPLACEMENT) != 1:
            raise ValueError(
                "Found the AWA replay marker, but the complete reviewed replay replacement is not intact."
            )
        return source
    if source.count(REPLAY_ORIGINAL) != 1:
        raise ValueError(
            "Expected exactly one unmodified mutating-tool replay block; refusing to patch an unreviewed source version."
        )
    return source.replace(REPLAY_ORIGINAL, REPLAY_REPLACEMENT, 1)

def patch_user_empty_response_source(source: str) -> str:
    """Retry one empty simulated-user response without inventing conversation content."""
    if USER_EMPTY_RESPONSE_PATCH_MARKER in source:
        if (
            source.count(USER_EMPTY_RESPONSE_PATCH_MARKER) != 1
            or source.count(USER_GENERATE_REPLACEMENT) != 1
            or USER_GENERATE_ORIGINAL in source
        ):
            raise ValueError(
                "Found the empty-response patch marker, but the complete reviewed "
                "replacement is not intact. Refusing to trust a partial patch."
            )
        return source
    if source.count(USER_GENERATE_ORIGINAL) != 1:
        raise ValueError(
            "Expected exactly one unmodified Tau2 user-simulator generation block; "
            "the upstream source may have changed. Refusing to patch."
        )
    return source.replace(USER_GENERATE_ORIGINAL, USER_GENERATE_REPLACEMENT, 1)


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
    replay_target = tau2_root / "src" / "tau2" / "environment" / "environment.py"
    user_target = tau2_root / "src" / "tau2" / "user" / "user_simulator.py"
    original_source = target.read_text(encoding="utf-8")
    replay_source = replay_target.read_text(encoding="utf-8")
    user_source = user_target.read_text(encoding="utf-8")

    # Validate all upstream source blocks before writing any file.
    patched_source = patch_orchestrator_source(original_source)
    patched_replay_source = patch_environment_replay_source(replay_source)
    patched_user_source = patch_user_empty_response_source(user_source)

    if patched_source != original_source:
        target.write_text(patched_source, encoding="utf-8")
    if patched_replay_source != replay_source:
        replay_target.write_text(patched_replay_source, encoding="utf-8")
    if patched_user_source != user_source:
        user_target.write_text(patched_user_source, encoding="utf-8")
    print(f"Installed {PATCH_MARKER} in {target}")
    print(f"Installed {REPLAY_PATCH_MARKER} in {replay_target}")
    print(f"Installed {USER_EMPTY_RESPONSE_PATCH_MARKER} in {user_target}")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tau2-root", type=Path, required=True)
    args = parser.parse_args()
    path = install(args.tau2_root.resolve())
    print(f"Verified Tau2 guard patches at {path} and the environment replay hook.")


if __name__ == "__main__":
    main()
