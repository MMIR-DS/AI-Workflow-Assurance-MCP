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
For retail order and exchange requests, apply these operational rules together with the policy above:
- After authenticating the user, use get_order_details with the order ID the customer provided. Do not ask the customer to look up internal item IDs when the order tools can retrieve them.
- Read the returned order items and their product IDs. Use get_product_details for the relevant product IDs, then select only available variants whose returned options match the customer's request.
- Treat IDs suggested by a customer as search clues, not verified catalog facts. Never invent, guess, or submit item IDs, product IDs, or payment-method IDs that did not come from tool evidence.
- For a multi-item exchange, resolve every old item, replacement variant, availability, price, order status, and payment method before proposing the change. Keep all requested item pairs together in the single permitted exchange write.
- If the customer explicitly authorizes the original payment method, inspect the order's payment history and use only a payment-method ID actually returned by the tools, if permitted by policy. Never request card numbers or other payment credentials in chat. If no supported method can be verified, explain the limitation and offer an appropriate handoff instead of guessing.
- Before any write, disclose the exact order, every old-to-new item pair, the payment method, and the price difference with charge/refund direction; obtain explicit confirmation after that disclosure.
- If an AWA pre-write guard denies a write, do not repeat the write attempt. Refresh read-only evidence, address every stated blocker, and obtain fresh confirmation only after correcting the proposed action.
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
