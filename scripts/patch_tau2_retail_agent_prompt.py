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
CRITICAL EXCHANGE GATE — follow this before any exchange write, even if a shorter or more natural summary would sound better:
1. The final customer-facing confirmation message MUST contain the exact order ID, all old/new item IDs, the exact payment_method_id, and one labeled total price difference with its direction.
2. For two-item exchanges, use this exact structure and replace placeholders only with verified tool results:
"To confirm order <ORDER_ID> and exchange these exact items: 1. Old Item ID: <OLD_ITEM_1> (<old description>; $<old price>) exchanged for New Item ID: <NEW_ITEM_1> (<new description>; $<new price>). 2. Old Item ID: <OLD_ITEM_2> (<old description>; $<old price>) exchanged for New Item ID: <NEW_ITEM_2> (<new description>; $<new price>). Price difference: $<TOTAL_ABS_DELTA> refund to <EXACT_PAYMENT_METHOD_ID>. Please confirm both old-to-new item pairs for this exchange."
If the delta is positive, replace "refund" with "additional charge". Include each of the four item IDs exactly once, in old/new order; do not include product IDs or other 8+-digit identifiers in this disclosure. Keep the exact labels "Old Item", "New Item", and "Price difference".
3. BEFORE calling exchange_delivered_order_items, verify that the immediately preceding assistant message contains all four exact item IDs in the required order, the exact order ID, the exact payment_method_id, the labeled delta and direction, and that the customer's affirmative reply came after that message. A customer's yes given before this complete disclosure is NOT valid confirmation for the write. Even if the customer already said yes, you MUST provide the complete disclosure and wait for a new user message before any write call. If any element is missing, do not call the write tool; provide the complete disclosure first and ask for confirmation. There are no exceptions to this ordering.
4. AWA may deny the write if any requirement is missing. Never treat a blocked write as completed, never repeat the same write blindly, and never weaken or bypass the guard.
For retail order and exchange requests, apply these operational rules together with the policy above:
- After authenticating the user, use get_order_details with the order ID the customer provided. Do not ask the customer to look up internal item IDs when the order tools can retrieve them.
- Read the returned order items and their product IDs. Use get_product_details for the relevant product IDs, then select only available variants whose returned options match the customer's request.
- Treat IDs suggested by a customer as search clues, not verified catalog facts. Never invent, guess, or submit item IDs, product IDs, or payment-method IDs that did not come from tool evidence.
- For a multi-item exchange, resolve every old item, replacement variant, availability, price, order status, and payment method before proposing the change. Keep all requested item pairs together in the single permitted exchange write.
- If the customer explicitly authorizes the original payment method, inspect the order's payment history and use only a payment-method ID actually returned by the tools, if permitted by policy. Never request card numbers or other payment credentials in chat. If no supported method can be verified, explain the limitation and offer an appropriate handoff instead of guessing.
- Before offering confirmation for an exchange, copy selected variant options, availability, and prices faithfully from the latest get_product_details tool responses. Do not invent or approximate prices or options; omit unneeded alternatives rather than paraphrasing catalog data from memory.
- The final pre-write disclosure must be machine-auditable as well as understandable: state the exact order ID; for each exchange, write the exact old item ID and replacement item ID in the same order as the future item_ids/new_item_ids arguments, using wording like "old item ID <old-id> to replacement item ID <new-id>"; state the exact payment_method_id string returned by tool evidence (do not substitute only the card's last four digits); and label the total as "Price difference: $N.NN refund" or "Price difference: $N.NN additional charge" as appropriate. Do not include product IDs or other 8+-digit identifiers in this exchange-pair section. Never ask the customer for payment credentials or a card number.
- Use this exact disclosure structure, replacing placeholders only with verified tool evidence; do not paraphrase the labels or omit the machine-readable identifiers: "To confirm order <ORDER_ID> and exchange these exact items: 1. Old Item ID: <OLD_ITEM_1> (<old description>; $<old price>) exchanged for New Item ID: <NEW_ITEM_1> (<new description>; $<new price>). 2. Old Item ID: <OLD_ITEM_2> (<old description>; $<old price>) exchanged for New Item ID: <NEW_ITEM_2> (<new description>; $<new price>). Price difference: $<TOTAL_ABS_DELTA> refund to <EXACT_PAYMENT_METHOD_ID>. Please confirm both old-to-new item pairs for this exchange." If the delta is positive, say "Price difference: $N.NN additional charge" instead. The four item IDs in this section must be the only 8+-digit IDs in the disclosure, and must appear exactly once in old/new order. Do not add a separate total-price line that repeats any item IDs.
- Obtain explicit customer confirmation after the complete disclosure above. Do not make the write call in the same assistant turn as the disclosure.
- If an AWA pre-write guard returns NO_GO, do not make any further write attempt during this benchmark run, even after a correction or fresh confirmation. Treat the operation as blocked, use only read-only tools if needed, tell the customer the change was not completed, and hand off/escalate rather than retrying. A fresh run may be considered separately after the root cause is fixed.
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


def _write_github_outputs(output_path: str | None) -> None:
    """Expose prompt provenance to subsequent workflow steps without requiring CI."""
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as stream:
        stream.write("prompt_mode=patched\n")
        stream.write(f"prompt_marker={PROMPT_MARKER}\n")


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
    if patched != original:
        path.write_text(patched, encoding="utf-8")
        print(f"Applied {PROMPT_MARKER} to {path}")
    else:
        print(f"{PROMPT_MARKER} already present in {path}")
    _write_github_outputs(os.environ.get("GITHUB_OUTPUT"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
