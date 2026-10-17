"""Restrict the pinned Tau2 task-0 agent to a reviewed minimal retail tool surface.

This is scoped to the manual single-task smoke, not a general retail-agent profile.
The policy text and AWA pre-write guard remain unchanged.
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

EXPECTED_TAU2_COMMIT = "4ce7c0397c1eb65c9bbe59aeacfe1ca44a1cd699"
PATCH_MARKER = "AWA_RETAIL_TASK0_TOOL_ALLOWLIST_V1"
AGENT_FILE = Path("src/tau2/agent/llm_agent.py")

ORIGINAL_FACTORY = '''def create_llm_agent(tools, domain_policy, **kwargs):
    """Factory function for LLMAgent.

    Args:
        tools: Environment tools the agent can call.
        domain_policy: Policy text the agent must follow.
        **kwargs: Additional arguments. Supports:
            - llm (str): Model name.
            - llm_args (dict): Additional arguments for the LLM.
    """
    return LLMAgent(
        tools=tools,
        domain_policy=domain_policy,
        llm=kwargs.get("llm"),
        llm_args=kwargs.get("llm_args"),
    )'''

REPLACEMENT_FACTORY = '''def create_llm_agent(tools, domain_policy, **kwargs):
    """Factory function for LLMAgent."""
    # AWA_RETAIL_TASK0_TOOL_ALLOWLIST_V1: trim unrelated schemas for fixed task 0.
    required_tool_names = (
        "calculate",
        "find_user_id_by_name_zip",
        "get_order_details",
        "get_product_details",
        "exchange_delivered_order_items",
        "transfer_to_human_agents",
    )
    tools_by_name = {tool.name: tool for tool in tools}
    missing_tools = [name for name in required_tool_names if name not in tools_by_name]
    if missing_tools:
        raise ValueError(
            "Missing reviewed task-0 retail tools: " + ", ".join(missing_tools)
        )
    selected_tools = [tools_by_name[name] for name in required_tool_names]
    return LLMAgent(
        tools=selected_tools,
        domain_policy=domain_policy,
        llm=kwargs.get("llm"),
        llm_args=kwargs.get("llm_args"),
    )'''


def patch_agent_source(source: str) -> str:
    """Patch only the pinned LLMAgent factory; reject unexpected source changes."""
    if PATCH_MARKER in source:
        if (
            source.count(PATCH_MARKER) != 1
            or source.count(REPLACEMENT_FACTORY) != 1
            or ORIGINAL_FACTORY in source
        ):
            raise ValueError(
                "Found the task-0 tool allowlist marker, but its factory block is not intact."
            )
        return source

    if source.count(ORIGINAL_FACTORY) != 1:
        raise ValueError(
            "Expected exactly one reviewed create_llm_agent factory in pinned Tau2; "
            f"found {source.count(ORIGINAL_FACTORY)}."
        )
    return source.replace(ORIGINAL_FACTORY, REPLACEMENT_FACTORY, 1)


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

    path = root / AGENT_FILE
    original = path.read_text(encoding="utf-8")
    patched = patch_agent_source(original)
    if patched != original:
        path.write_text(patched, encoding="utf-8")
        print(f"Applied {PATCH_MARKER} to {path}")
    else:
        print(f"{PATCH_MARKER} already present in {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
