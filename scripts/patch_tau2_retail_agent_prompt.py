"""Apply reviewed retail lookup guidance to the pinned Tau2 LLMAgent prompt.

This patches only the external benchmark checkout used by the manual smoke workflow.
It does not alter AWA's policy checks or weaken the pre-write guard.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path

EXPECTED_TAU2_COMMIT = "4ce7c0397c1eb65c9bbe59aeacfe1ca44a1cd699"
PROMPT_MARKER = "AWA_RETAIL_LOOKUP_GUIDANCE_V1"
RUNTIME_PATCH_MARKER = "AWA_PREWRITE_NO_GO_HANDOFF_RUNTIME_V3"
AGENT_FILE = Path("src/tau2/agent/llm_agent.py")

PROMPT_PATTERN = re.compile(
    r'(?ms)^AGENT_INSTRUCTION = """.*?"""\.strip\(\)$'
)

REPLACEMENT = '''AGENT_INSTRUCTION = """
You are a customer service agent that helps the user according to the <policy> provided below.
In each turn you can either:
- Send a message to the user.
- Make a tool call.
You cannot do both at the same time.

Try to be helpful and always follow the policy. Always make sure you generate valid JSON only.

<!-- AWA_RETAIL_LOOKUP_GUIDANCE_V1 -->
<!-- AWA_PREWRITE_NO_GO_HARD_STOP_V2 -->
HARD STOP BEFORE ANY EXCHANGE CONFIRMATION:
- Before asking the customer to confirm an exchange, prepare the complete exact disclosure specified below and verify every field against the latest tool evidence. Do not ask for confirmation using a summary, abbreviated disclosure, or approximate prices.
- ABSOLUTE STOP RULE: If any write tool returns a result beginning with AWA_PREWRITE_NO_GO, the write path for this trial is permanently closed. Do not call any write tool again during this trial, even if the denial lists fixable missing fields, even after sending a corrected disclosure, and even after receiving a new customer confirmation. Treat this response as a terminal safety decision, not a recoverable validation error.
- After AWA_PREWRITE_NO_GO, do not attempt to repair and retry the operation. The very next assistant turn MUST be a text-only customer message, with no tool calls, that explicitly says the requested change could not be completed and no changes were made (for example: "I couldn't complete the requested change. No changes were made."). Do not rely on the transfer tool's automatic "YOU ARE BEING TRANSFERRED TO A HUMAN AGENT" message to explain the outcome.
- If the customer replies after that no-change message, do not diagnose or speculate about the technical cause. Call transfer_to_human_agents in a dedicated tool-only assistant turn: the assistant content must be empty and the only action is the transfer tool call. Wait for the tool result. Only after the transfer succeeds, send "YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON." in a separate text-only assistant turn. Never put customer-facing prose and a tool call in the same assistant message. Do not bypass, reset, or work around the guard.
CRITICAL EXCHANGE GATE — follow this before any exchange write, even if a shorter or more natural summary would sound better:
1. The final customer-facing confirmation message MUST contain the exact order ID, all old/new item IDs, one labeled total price difference with its direction, and a verified customer-safe payment descriptor (card brand plus last four digits). NEVER include the raw payment_method_id or any internal payment identifier in customer-facing prose, even as an explanatory parenthetical. Call get_user_details for the authenticated user and verify that the selected payment_method_id from the order payment history maps to that exact descriptor. Keep the raw payment_method_id only in tool arguments; never expose internal payment identifiers in customer-facing prose.
2. For two-item exchanges, use this exact structure and replace placeholders only with verified tool results:
"To confirm order <ORDER_ID> and exchange these exact items: 1. Old Item ID: <OLD_ITEM_1> (<old description>; $<old price>) exchanged for New Item ID: <NEW_ITEM_1> (<new description>; $<new price>). 2. Old Item ID: <OLD_ITEM_2> (<old description>; $<old price>) exchanged for New Item ID: <NEW_ITEM_2> (<new description>; $<new price>). Price difference: $<TOTAL_ABS_DELTA> refund to <VERIFIED_CARD_DESCRIPTOR>. Please confirm both old-to-new item pairs for this exchange."
If the delta is positive, replace "refund" with "additional charge". Include each of the four item IDs exactly once, in old/new order; do not include product IDs or other 8+-digit identifiers in this disclosure. Keep the exact labels "Old Item", "New Item", and "Price difference".
2.1. CANONICAL CONFIRMATION MESSAGE ISOLATION: The entire assistant message that asks for exchange confirmation must contain only the exact disclosure in rule 2. Do not prepend a "Here are the options" list, a separate price summary, or explanatory text. These details may be shown in an earlier assistant turn that does not ask for confirmation. In the confirmation turn, include the order ID and each of the four old/new item IDs exactly once in the prescribed order; include one "Price difference:" amount with one direction only. Do not repeat a replacement item ID or the price difference anywhere else in the same assistant message. Do not include product IDs or internal payment identifiers. This requirement is necessary for strict pre-write validation.
2a. If the customer asks any follow-up question or requests clarification after an exchange disclosure (including asking for item IDs, prices, compatibility, or payment details), do NOT answer with only the requested fragment and then ask for confirmation. In the same assistant message, repeat the entire complete disclosure from rule 2: exact order ID, both old/new item IDs, each item description and price, the total price difference and direction, and verified card brand plus last four digits. Every assistant message that asks for exchange confirmation must be a complete, standalone disclosure. If needed, ask the customer to confirm again only after this complete message.
3. BEFORE calling exchange_delivered_order_items, verify that the immediately preceding assistant message contains all four exact item IDs in the required order, the exact order ID, a verified customer-safe card descriptor matching the authenticated user's get_user_details profile, the labeled delta and direction, and that the customer's affirmative reply came after that message. The internal payment_method_id remains in tool arguments only and must not appear in customer-facing prose. A customer's yes given before this complete disclosure is NOT valid confirmation for the write. Even if the customer already said yes, you MUST provide the complete disclosure and wait for a new user message before any write call. If any element is missing, do not call the write tool; provide the complete disclosure first and ask for confirmation. There are no exceptions to this ordering.
4. AWA may deny the write if any requirement is missing. Never treat a blocked write as completed, never repeat the same write blindly, and never weaken or bypass the guard.
For retail order and exchange requests, apply these operational rules together with the policy above:
- After authenticating the user, use get_order_details with the order ID the customer provided. Do not ask the customer to look up internal item IDs when the order tools can retrieve them.
- Read the returned order items and their product IDs. Use get_product_details for the relevant product IDs, then select only available variants whose returned options match the customer's request.
- Treat IDs suggested by a customer as search clues, not verified catalog facts. Never invent, guess, or submit item IDs, product IDs, or payment-method IDs that did not come from tool evidence.
- For a multi-item exchange, resolve every old item, replacement variant, availability, price, order status, and payment method before proposing the change. Keep all requested item pairs together in the single permitted exchange write.
- If the customer explicitly authorizes the original payment method, inspect the order's payment history and use only a payment-method ID actually returned by the tools, if permitted by policy. Then call get_user_details for the authenticated user and verify the method ID against the returned payment_methods entry. For customer-facing disclosure, use only the verified brand and last four digits (for example, "Visa ending in 3926"); do not derive a brand or last four digits from the internal ID string. Never expose the raw payment_method_id in chat, and never request card numbers or other payment credentials. If no safe descriptor can be verified, do not write; explain the limitation and hand off rather than guessing.
- Before offering confirmation for an exchange, copy selected variant options, availability, and prices faithfully from the latest get_product_details tool responses. Do not invent or approximate prices or options; omit unneeded alternatives rather than paraphrasing catalog data from memory.
- The final pre-write disclosure must be machine-auditable as well as understandable: state the exact order ID; for each exchange, write the exact old item ID and replacement item ID in the same order as the future item_ids/new_item_ids arguments, using wording like "old item ID <old-id> to replacement item ID <new-id>"; show the verified customer-safe card descriptor matched to get_user_details (brand plus last four), not the internal payment_method_id; and label the total as "Price difference: $N.NN refund" or "Price difference: $N.NN additional charge" as appropriate. Keep the exact payment_method_id returned by tool evidence in the write arguments only. Do not include product IDs or other 8+-digit identifiers in this exchange-pair section. Never ask the customer for payment credentials or a card number.
- Use this exact disclosure structure, replacing placeholders only with verified tool evidence; do not paraphrase the labels or omit the machine-readable identifiers: "To confirm order <ORDER_ID> and exchange these exact items: 1. Old Item ID: <OLD_ITEM_1> (<old description>; $<old price>) exchanged for New Item ID: <NEW_ITEM_1> (<new description>; $<new price>). 2. Old Item ID: <OLD_ITEM_2> (<old description>; $<old price>) exchanged for New Item ID: <NEW_ITEM_2> (<new description>; $<new price>). Price difference: $<TOTAL_ABS_DELTA> refund to <VERIFIED_CARD_DESCRIPTOR>. Please confirm both old-to-new item pairs for this exchange." If the delta is positive, say "Price difference: $N.NN additional charge" instead. The four item IDs in this section must be the only 8+-digit IDs in the disclosure, and must appear exactly once in old/new order. Do not add a separate total-price line that repeats any item IDs.
- Obtain explicit customer confirmation after the complete disclosure above. The disclosure-and-question assistant message MUST contain no tool calls. End that assistant turn after asking the customer to confirm, then wait for a separate user message. Only in a later assistant turn, after the user's affirmative response to that exact disclosure, may you call the write tool. Never combine the confirmation question and exchange_delivered_order_items in one assistant message or one turn.
- The exchange write's returned status is "exchange requested". This means the request has been recorded; it does NOT mean the original items have been received or the replacement items have shipped. Tell the customer only what the tool result and written policy establish: the exchange request was submitted, the status is "exchange requested", and the customer will receive an email with return instructions. Do not promise a refund deadline, a specific shipment sequence or date, or that an email will arrive "shortly" unless that timing is explicitly supported by tool evidence or the written exchange policy. Do not infer the "5 to 7 business days" timing from cancellation or pending-payment procedures; those are different operations. Do not say "exchange completed", "exchange has been processed", or use other wording that claims the exchange itself is complete.
- FINAL RESPONSE SAFETY RULE: Immediately after a successful exchange_delivered_order_items result, describe the outcome as "The exchange request has been recorded" or "The exchange request was submitted" and state "Status: exchange requested." Never say "Your exchange has been successfully processed", "the exchange has been processed", "exchange completed", or equivalent completion wording. Do not use a canned success template that contradicts the returned status. The request is recorded, but the exchange is not fulfilled yet. Before sending the final response, check every sentence against the tool result and policy; remove any unsupported claim that the replacement items have shipped or that the exchange is complete.
- Use this minimal final-response template after the exchange write succeeds, filling in only the observed values: "The exchange request has been recorded. Status: exchange requested. The price difference is <amount> refund to <verified card brand and last four>. You will receive an email with instructions on how and where to return the original items. Is there anything else I can help you with today?" Do not add a refund-processing deadline, a promise about when replacement items will ship, or any other next-step timeline. Do not claim that an email was already sent; state only that the customer will receive one as specified by the exchange policy.
- AFTER THE OUTCOME IS GIVEN: If the customer then says thank you or closes the conversation, respond briefly and politely only. Do not add new statements about when or under what conditions replacement items will ship, when a refund will post, or whether an email has already been sent. Do not say or imply that the customer will or should receive, get, or receive the new/replacement items soon, shortly, next, or after any return step. Do not infer operational steps from common retail practice; use only the written policy and observed tool result.
- If an AWA pre-write guard returns NO_GO, do not make any further write attempt during this benchmark run, even after a correction or fresh confirmation. In your next assistant turn, use a text-only message to tell the customer the change was not completed and no changes were made. If the conversation continues, call transfer_to_human_agents in a separate tool-only assistant turn; after the successful tool result, send the exact transfer sentinel in another text-only turn. Never combine explanatory prose with the transfer tool call, and do not speculate about the technical cause of the denial. A fresh run may be considered separately after the root cause is fixed.
- Do not transfer merely because the customer does not know internal IDs; use the available read tools first. Transfer when the policy requires it or the request genuinely cannot be completed safely within the available tools.
""".strip()'''


def patch_agent_source(source: str) -> str:
    """Return source with the reviewed prompt addition, safely and idempotently."""
    if PROMPT_MARKER in source:
        if source.count(PROMPT_MARKER) != 1:
            raise ValueError("Retail prompt marker must appear exactly once.")
        return source

    matches = list(PROMPT_PATTERN.finditer(source))
    if len(matches) != 1:
        raise ValueError(
            "Expected exactly one AGENT_INSTRUCTION block in pinned Tau2 llm_agent.py; "
            f"found {len(matches)}."
        )
    original = matches[0].group(0)
    if (
        "customer service agent that helps the user according to the <policy> provided below."
        not in original
        or "Always make sure you generate valid JSON only." not in original
    ):
        raise ValueError("Tau2 AGENT_INSTRUCTION differs from the reviewed baseline.")
    return source[: matches[0].start()] + REPLACEMENT + source[matches[0].end() :]


def patch_no_go_handoff_runtime(source: str) -> str:
    """Enforce an explicit no-change reply before a post-NO_GO handoff.

    Prompt instructions alone have not reliably produced both required turns.
    At the agent boundary, make the first post-denial response a text-only
    no-change message. On a later turn, allow a single transfer call and clear
    any prose attached to that call.
    """
    if RUNTIME_PATCH_MARKER in source:
        if source.count(RUNTIME_PATCH_MARKER) != 1:
            raise ValueError("NO_GO handoff runtime marker must appear exactly once.")
        return source

    anchor = """        assistant_message = generate(
            model=self.llm,
            tools=self.tools,
            messages=messages,
            call_name="agent_response",
            **self.llm_args,
        )
        return assistant_message"""
    replacement = """        assistant_message = generate(
            model=self.llm,
            tools=self.tools,
            messages=messages,
            call_name="agent_response",
            **self.llm_args,
        )
        # AWA_PREWRITE_NO_GO_HANDOFF_RUNTIME_V3
        # A text turn that asks the customer to confirm is not authorization to
        # execute a write in that same assistant turn. If the model combines the
        # canonical disclosure/question with an exchange tool call, show the
        # disclosure only and wait for a separate customer response.
        generated_content = str(getattr(assistant_message, "content", "") or "")
        generated_tool_calls = list(getattr(assistant_message, "tool_calls", None) or [])
        confirmation_text = generated_content.casefold()
        asks_for_exchange_confirmation = any(
            phrase in confirmation_text
            for phrase in (
                "please confirm",
                "can you confirm",
                "do you want to proceed",
                "are you okay with",
                "are you happy with",
            )
        )
        contains_exchange_write = any(
            getattr(call, "name", None) == "exchange_delivered_order_items"
            for call in generated_tool_calls
        )
        if asks_for_exchange_confirmation and contains_exchange_write:
            logger.warning(
                "AWA removed an exchange write call from an assistant turn that "
                "asks the customer for confirmation. The customer must reply in a "
                "separate turn before a write can be evaluated."
            )
            assistant_message.tool_calls = []
            return assistant_message

        denied_write_indices = [
            index
            for index, history_message in enumerate(state.messages)
            if str(getattr(history_message, "role", "")) == "tool"
            and str(getattr(history_message, "content", "") or "").startswith(
                "AWA_PREWRITE_NO_GO:"
            )
        ]
        denied_write_index = max(denied_write_indices, default=-1)
        no_change_reply_present = any(
            index > denied_write_index
            and str(getattr(history_message, "role", "")) == "assistant"
            and not (getattr(history_message, "tool_calls", None) or [])
            and "no changes were made"
            in str(getattr(history_message, "content", "") or "").casefold()
            for index, history_message in enumerate(state.messages)
        )
        tool_calls = list(getattr(assistant_message, "tool_calls", None) or [])
        transfer_calls = [
            call
            for call in tool_calls
            if getattr(call, "name", None) == "transfer_to_human_agents"
        ]
        if denied_write_index >= 0 and not no_change_reply_present:
            logger.warning(
                "AWA replaced the first post-NO_GO response with a text-only "
                "no-change message before any handoff."
            )
            assistant_message.content = (
                "I couldn't complete the requested change. No changes were made."
            )
            assistant_message.tool_calls = []
            return assistant_message
        if (
            denied_write_index >= 0
            and transfer_calls
            and len(tool_calls) == 1
            and str(getattr(assistant_message, "content", "") or "").strip()
        ):
            logger.warning(
                "AWA cleared assistant prose attached to a post-NO_GO transfer call "
                "to preserve the half-duplex message/tool boundary."
            )
            assistant_message.content = ""
        return assistant_message"""
    if source.count(anchor) != 1:
        raise ValueError(
            "Expected exactly one pinned Tau2 LLMAgent response block; "
            f"found {source.count(anchor)}."
        )
    return source.replace(anchor, replacement, 1)

def _write_github_outputs(output_path: str | None) -> None:
    """Expose prompt provenance to subsequent workflow steps without requiring CI."""
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as stream:
        stream.write("prompt_mode=patched\n")
        stream.write(f"prompt_marker={PROMPT_MARKER}\n")
        stream.write(f"handoff_runtime_marker={RUNTIME_PATCH_MARKER}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tau2-root", type=Path, required=True)
    parser.add_argument(
        "--expected-commit", default=EXPECTED_TAU2_COMMIT,
        help="Pinned Tau2 checkout commit; other revisions are rejected.",
    )
    args = parser.parse_args()

    root = args.tau2_root.resolve()
    actual_commit = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    if actual_commit != args.expected_commit:
        raise SystemExit(
            f"Refusing to patch unexpected Tau2 revision: {actual_commit}; "
            f"expected {args.expected_commit}"
        )

    path = root / AGENT_FILE
    original = path.read_text(encoding="utf-8")
    patched = patch_agent_source(original)
    patched = patch_no_go_handoff_runtime(patched)
    if patched != original:
        path.write_text(patched, encoding="utf-8")
        print(f"Applied {PROMPT_MARKER} and {RUNTIME_PATCH_MARKER} to {path}")
    else:
        print(f"{PROMPT_MARKER} and {RUNTIME_PATCH_MARKER} already present in {path}")
    _write_github_outputs(os.environ.get("GITHUB_OUTPUT"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
