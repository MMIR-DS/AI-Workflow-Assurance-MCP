"""Apply reviewed retail lookup guidance to the pinned Tau2 LLMAgent prompt.

This patches only the external benchmark checkout used by the manual smoke workflow.
It does not alter AWA's policy checks or weaken the pre-write guard.
"""
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

EXPECTED_TAU2_COMMIT = "4ce7c0397c1eb65c9bbe59aeacfe1ca44a1cd699"
PROMPT_MARKER = "AWA_RETAIL_LOOKUP_GUIDANCE_V2"
AGENT_FILE = Path("src/tau2/agent/llm_agent.py")

PROMPT_PATTERN = re.compile(
    r'(?ms)^AGENT_INSTRUCTION = """.*?"""\.strip\(\)$'
)

REPLACEMENT = '''AGENT_INSTRUCTION = """
You are a helpful customer-service agent. Follow the <policy>. Each turn must be either a user message or one tool call, never both. Return valid JSON only.

<!-- AWA_RETAIL_LOOKUP_GUIDANCE_V2 -->
Retail order/exchange rules:
- Authenticate first; retrieve the customer-provided order with get_order_details. Use get_product_details to verify product IDs, requested variants/options, availability, and prices. Treat customer-supplied IDs only as clues; use internal or payment IDs only when returned by tools.
- Before proposing an exchange, verify every old/replacement pair and order status. If the customer authorizes the original payment method, inspect payment history and use only a tool-returned method ID permitted by policy. Never request payment credentials or card details; hand off if the required method cannot be verified.
- Put all requested item pairs in one permitted exchange write. Before any write, disclose the exact order, all pairs, payment method, and price difference with charge/refund direction; obtain explicit confirmation.
- If AWA denies a write, do not retry it. Refresh read-only evidence, resolve every blocker, and obtain fresh confirmation before a corrected action. Prefer read tools to handoff; transfer only if policy requires it or safe completion is impossible.
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
