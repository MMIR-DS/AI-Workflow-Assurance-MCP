from __future__ import annotations

from scripts.patch_tau2_retail_agent_prompt import (
    PROMPT_MARKER,
    RUNTIME_PATCH_MARKER,
    _write_github_outputs,
    patch_agent_source,
    patch_no_go_handoff_runtime,
)

BASELINE = '''from typing import Optional

AGENT_INSTRUCTION = """
You are a customer service agent that helps the user according to the <policy> provided below.
In each turn you can either:
- Send a message to the user.
- Make a tool call.
You cannot do both at the same time.

Try to be helpful and always follow the policy. Always make sure you generate valid JSON only.
""".strip()

SYSTEM_PROMPT = "unchanged"
'''


def test_patch_adds_retail_lookup_guidance_without_removing_base_policy() -> None:
    patched = patch_agent_source(BASELINE)

    assert PROMPT_MARKER in patched
    assert "get_order_details" in patched
    assert "get_product_details" in patched
    assert "never request card numbers" in patched
    assert "single permitted exchange write" in patched
    assert "exact old item ID and replacement item ID" in patched
    assert "verified customer-safe payment descriptor" in patched
    assert "never expose internal payment identifiers" in patched
    assert "credit_card_9513926" not in patched
    assert "<EXACT_PAYMENT_METHOD_ID>" not in patched
    assert "refund to <VERIFIED_CARD_DESCRIPTOR>" in patched
    assert "MUST contain no tool calls" in patched
    assert "wait for a separate user message" in patched
    assert "Never combine the confirmation question and exchange_delivered_order_items" in patched
    assert "never expose internal payment identifiers" in patched
    assert "returned status is \"exchange requested\"" in patched
    assert "Do not say \"exchange completed\"" in patched
    assert "Do not promise a refund deadline" in patched
    assert "Do not promise a refund deadline, a specific shipment sequence or date" in patched
    assert "AFTER THE OUTCOME IS GIVEN" in patched
    assert "Do not infer operational steps from common retail practice" in patched
    assert "will or should receive, get, or receive the new/replacement items soon" in patched
    assert "Do not infer the \"5 to 7 business days\" timing" in patched
    assert "Price difference:" in patched
    assert "Use this exact disclosure structure" in patched
    assert "CRITICAL EXCHANGE GATE" in patched
    # Rule 3 must be a real prompt line break, not the literal characters "\\n".
    assert "\\n3. BEFORE calling exchange_delivered_order_items" not in patched
    assert "\n3. BEFORE calling exchange_delivered_order_items" in patched
    assert "BEFORE calling exchange_delivered_order_items" in patched
    assert "contains all four exact item IDs in the required order" in patched
    assert "is NOT valid confirmation for the write" in patched
    assert "wait for a new user message before any write call" in patched
    assert "There are no exceptions to this ordering" in patched
    assert "do not make any further write attempt during this benchmark run" in patched
    assert "tell the customer the change was not completed" in patched
    assert "AWA_PREWRITE_NO_GO_HARD_STOP_V2" in patched
    assert "The very next assistant turn MUST be a text-only customer message" in patched
    assert "Do not rely on the transfer tool's automatic" in patched
    assert "the assistant content must be empty and the only action is the transfer tool call" in patched
    assert "Never put customer-facing prose and a tool call in the same assistant message" in patched
    assert "after the successful tool result" in patched
    assert "The entire assistant message that asks for exchange confirmation must contain only the exact disclosure in rule 2" in patched
    assert 'Do not prepend a "Here are the options" list, a separate price summary, or explanatory text' in patched
    assert "each of the four old/new item IDs exactly once in the prescribed order" in patched
    assert "Old Item ID: <OLD_ITEM_1>" in patched
    assert "Please confirm both old-to-new item pairs" in patched
    assert "Do not include product IDs or other 8+-digit identifiers" in patched
    assert "do not make any further write attempt during this benchmark run" in patched.lower()
    assert "Try to be helpful and always follow the policy." in patched
    assert 'SYSTEM_PROMPT = "unchanged"' in patched


def test_patch_is_idempotent() -> None:
    once = patch_agent_source(BASELINE)
    twice = patch_agent_source(once)

    assert twice == once
    assert twice.count(PROMPT_MARKER) == 1


def test_patch_rejects_unknown_agent_prompt_shape() -> None:
    try:
        patch_agent_source('AGENT_INSTRUCTION = "changed"')
    except ValueError as exc:
        assert "AGENT_INSTRUCTION" in str(exc)
    else:
        raise AssertionError("Unexpected prompt shape must be rejected.")


def test_patch_writes_prompt_provenance_to_github_step_outputs(tmp_path) -> None:
    output_path = tmp_path / "github-output.txt"

    _write_github_outputs(str(output_path))

    assert output_path.read_text(encoding="utf-8").splitlines() == [
        "prompt_mode=patched",
        f"prompt_marker={PROMPT_MARKER}",
        f"handoff_runtime_marker={RUNTIME_PATCH_MARKER}",
    ]


def test_prompt_output_helper_is_optional_outside_github_actions(tmp_path) -> None:
    _write_github_outputs(None)
    assert list(tmp_path.iterdir()) == []


RUNTIME_BASELINE = '''class LLMAgent:
    def _generate_next_message(self, message, state):
        assistant_message = generate(
            model=self.llm,
            tools=self.tools,
            messages=messages,
            call_name="agent_response",
            **self.llm_args,
        )
        return assistant_message
'''


def test_no_go_runtime_patch_inserts_no_change_reply_before_handoff() -> None:
    patched = patch_no_go_handoff_runtime(RUNTIME_BASELINE)

    assert RUNTIME_PATCH_MARKER in patched
    assert '"AWA_PREWRITE_NO_GO:"' in patched
    assert '"no changes were made"' in patched
    assert "no_change_reply_present" in patched
    assert "assistant_message.tool_calls = []" in patched
    assert "I couldn't complete the requested change. No changes were made." in patched
    assert 'getattr(call, "name", None) == "transfer_to_human_agents"' in patched
    assert 'assistant_message.content = ""' in patched
    assert "preserve the half-duplex message/tool boundary" in patched


def test_no_go_runtime_patch_is_idempotent() -> None:
    once = patch_no_go_handoff_runtime(RUNTIME_BASELINE)
    twice = patch_no_go_handoff_runtime(once)

    assert twice == once
    assert twice.count(RUNTIME_PATCH_MARKER) == 1


def test_no_go_runtime_patch_rejects_unknown_llm_agent_shape() -> None:
    try:
        patch_no_go_handoff_runtime("class LLMAgent: pass")
    except ValueError as exc:
        assert "LLMAgent response block" in str(exc)
    else:
        raise AssertionError("Unexpected pinned agent structure must be rejected.")
