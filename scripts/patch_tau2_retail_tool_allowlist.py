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
        tools: Environment tools for the agent.
        domain_policy: Policy text the agent must follow.
        **kwargs: Additional arguments. Supports:
            - llm (str): model name.
            - llm_args (dict): Additional arguments for the LLM.
    """
    return LLMAgent(
        tools=tools,
        domain_policy=domain_policy,
        llm=kwargs.get("llm"),
        llm_args=kwargs.get("llm_args"),
    )'''

ORIGINAL_RETURN = '''    return LLMAgent(
        tools=tools,
        domain_policy=domain_policy,
        llm=kwargs.get("llm"),
        llm_args=kwargs.get("llm_args"),
    )'''

REPLACEMENT_RETURN = '''    # AWA_RETAIL_TASK0_TOOL_ALLOWLIST_V1: trim unrelated schemas for fixed task 0.
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
    marker_count = source.count(PATCH_MARKER)
    if marker_count:
        if (
            marker_count != 1
            or source.count(REPLACEMENT_RETURN) != 1
            or source.count(ORIGINAL_RETURN) != 0
        ):
            raise ValueError(
                "Found the task-0 tool allowlist marker, but its factory block is not intact."
            )
        return source

    factory_start = source.find("def create_llm_agent(tools, domain_policy, **kwargs):")
    if factory_start < 0:
        raise ValueError("Could not find the reviewed create_llm_agent factory in pinned Tau2.")
    next_factory = source.find("\ndef create_llm_gt_agent(", factory_start)
    if next_factory < 0:
        next_factory = len(source)
    factory = source[factory_start:next_factory]

    if factory.count(ORIGINAL_RETURN) != 1:
        raise ValueError(
            "Expected exactly one reviewed LLMAgent return block inside create_llm_agent; "
            f"found {factory.count(ORIGINAL_RETURN)}."
        )
    if "domain_policy=domain_policy" not in factory or 'llm=kwargs.get("llm")' not in factory:
        raise ValueError("The create_llm_agent factory differs from the reviewed baseline.")

    patched_factory = factory.replace(ORIGINAL_RETURN, REPLACEMENT_RETURN, 1)
    return source[:factory_start] + patched_factory + source[next_factory:]


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
