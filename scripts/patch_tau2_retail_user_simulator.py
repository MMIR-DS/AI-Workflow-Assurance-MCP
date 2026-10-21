"""Patch Tau2's simulated-customer stop rule for state-changing retail tasks.

The customer confirmation authorizes an operation. It does not mean that the
operation has happened. Apply this narrow patch only to the pinned Tau2 checkout
used by the retail smoke workflow.
"""
from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

EXPECTED_TAU2_COMMIT = "4ce7c0397c1eb65c9bbe59aeacfe1ca44a1cd699"
PROMPT_MARKER = "AWA_RETAIL_USER_COMPLETION_GATE_V1"
GUIDELINES_FILE = Path("data/tau2/user_simulator/simulation_guidelines.md")
BASELINE_ANCHOR = (
    "## Task Completion\n"
    "- The goal is to continue the conversation until the task is complete."
)

COMPLETION_GATE = """<!-- AWA_RETAIL_USER_COMPLETION_GATE_V1 -->
## AWA retail state-change completion rule

For a retail scenario that asks for an exchange, cancellation, return, or another
state-changing operation, a customer's confirmation gives the agent permission
to act. It does not prove that the operation happened.

- Do not output the `###STOP###` token in the same message as the customer's
  confirmation for an operation that is still pending.
- After confirmation, continue the conversation until the agent has attempted
  the requested operation and communicated its result. An offer, plan, item
  disclosure, or customer confirmation alone does not complete the task.
- If the agent reports that the operation succeeded, the customer may end the
  conversation after that result is communicated.
- If the agent reports that the operation was blocked or failed, do not claim
  that the operation succeeded. Follow a clear handoff or escalation, or end
  only after the outcome is clear. Never encourage the agent to bypass a guard.

This rule overrides the general stop-on-goal rule when a requested state change
has not yet received an outcome.
"""


def patch_guidelines_source(source: str) -> str:
    """Add the completion rule once and reject unexpected or partial patches."""
    if PROMPT_MARKER in source:
        if source.count(PROMPT_MARKER) != 1 or COMPLETION_GATE.strip() not in source:
            raise ValueError(
                "Found the AWA user-completion marker, but the complete reviewed "
                "rule is not intact. Refusing to trust a partial or modified patch."
            )
        return source

    if source.count(BASELINE_ANCHOR) != 1:
        raise ValueError(
            "Expected the reviewed Tau2 user-simulation Task Completion section; "
            "the upstream source may have changed. Refusing to patch."
        )
    return source.rstrip() + "\n\n" + COMPLETION_GATE.strip() + "\n"


def _write_github_outputs(output_path: str | None) -> None:
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as stream:
        stream.write("prompt_mode=patched\n")
        stream.write(f"prompt_marker={PROMPT_MARKER}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tau2-root", type=Path, required=True)
    parser.add_argument(
        "--expected-commit",
        default=EXPECTED_TAU2_COMMIT,
        help="Pinned Tau2 checkout commit; other revisions are rejected.",
    )
    args = parser.parse_args()

    root = args.tau2_root.resolve()
    actual_commit = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if actual_commit != args.expected_commit:
        raise SystemExit(
            f"Refusing to patch unexpected Tau2 revision: {actual_commit}; "
            f"expected {args.expected_commit}"
        )

    path = root / GUIDELINES_FILE
    original = path.read_text(encoding="utf-8")
    patched = patch_guidelines_source(original)
    if patched != original:
        path.write_text(patched, encoding="utf-8")
        print(f"Applied {PROMPT_MARKER} to {path}")
    else:
        print(f"{PROMPT_MARKER} already present in {path}")

    _write_github_outputs(os.environ.get("GITHUB_OUTPUT"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
