"""Patch the pinned Tau2 LiteLLM call to support bounded provider retries.

The manual OpenRouter smoke sets TAU2_LITELLM_NUM_RETRIES=0 so a provider
in-flight-budget rejection does not trigger LiteLLM's hidden per-call retries.
Outside that workflow, unset configuration preserves Tau2's own default.
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

EXPECTED_TAU2_COMMIT = "4ce7c0397c1eb65c9bbe59aeacfe1ca44a1cd699"
PATCH_MARKER = "AWA_LITELLM_RETRY_OVERRIDE_V1"
LLM_FILE = Path("src/tau2/utils/llm_utils.py")

ORIGINAL = '''    if kwargs.get("num_retries") is None:
        kwargs["num_retries"] = DEFAULT_MAX_RETRIES'''

REPLACEMENT = '''    # AWA_LITELLM_RETRY_OVERRIDE_V1: bounded workflows may override hidden retries.
    retry_override = os.environ.get("TAU2_LITELLM_NUM_RETRIES")
    if retry_override is not None:
        try:
            configured_retries = int(retry_override)
        except ValueError as exc:
            raise ValueError(
                "TAU2_LITELLM_NUM_RETRIES must be a non-negative integer."
            ) from exc
        if configured_retries < 0:
            raise ValueError(
                "TAU2_LITELLM_NUM_RETRIES must be a non-negative integer."
            )
        kwargs["num_retries"] = configured_retries
    elif kwargs.get("num_retries") is None:
        kwargs["num_retries"] = DEFAULT_MAX_RETRIES'''


def patch_llm_source(source: str) -> str:
    """Patch the expected default retry block; reject unexpected source revisions."""
    if PATCH_MARKER in source:
        if source.count(PATCH_MARKER) != 1 or source.count(REPLACEMENT) != 1 or ORIGINAL in source:
            raise ValueError("Found retry patch marker, but the patched block is not intact.")
        return source

    if source.count(ORIGINAL) != 1:
        raise ValueError(
            "Expected exactly one reviewed LiteLLM retry-default block in "
            f"{LLM_FILE}; found {source.count(ORIGINAL)}."
        )
    if "import os" not in source or "from litellm import completion" not in source:
        raise ValueError("Tau2 LLM utility source differs from the reviewed baseline.")
    return source.replace(ORIGINAL, REPLACEMENT, 1)


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

    path = root / LLM_FILE
    original = path.read_text(encoding="utf-8")
    patched = patch_llm_source(original)
    if patched != original:
        path.write_text(patched, encoding="utf-8")
        print(f"Applied {PATCH_MARKER} to {path}")
    else:
        print(f"{PATCH_MARKER} already present in {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
