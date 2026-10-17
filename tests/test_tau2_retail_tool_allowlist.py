from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.patch_tau2_retail_tool_allowlist import (
    ORIGINAL_FACTORY,
    PATCH_MARKER,
    REPLACEMENT_FACTORY,
    patch_agent_source,
)

BASELINE = ORIGINAL_FACTORY
EXPECTED_TOOLS = [
    "calculate",
    "find_user_id_by_name_zip",
    "get_order_details",
    "get_product_details",
    "exchange_delivered_order_items",
    "transfer_to_human_agents",
]


def _factory(source: str):
    namespace = {"LLMAgent": lambda **kwargs: kwargs}
    exec(compile(source, "pinned_tau2_llm_agent.py", "exec"), namespace)
    return namespace["create_llm_agent"]


def test_patch_exposes_only_reviewed_task0_tools() -> None:
    patched = patch_agent_source(BASELINE)
    factory = _factory(patched)
    names = EXPECTED_TOOLS + [
        "find_user_id_by_email",
        "get_item_details",
        "get_user_details",
        "cancel_pending_order",
        "modify_pending_order_items",
        "return_delivered_order_items",
    ]
    tools = [SimpleNamespace(name=name) for name in names]

    result = factory(
        tools=tools,
        domain_policy="original retail policy",
        llm="test-model",
        llm_args={"temperature": 0.0},
    )

    assert [tool.name for tool in result["tools"]] == EXPECTED_TOOLS
    assert result["domain_policy"] == "original retail policy"
    assert result["llm"] == "test-model"
    assert result["llm_args"] == {"temperature": 0.0}


def test_patch_fails_closed_if_a_required_tool_is_missing() -> None:
    factory = _factory(patch_agent_source(BASELINE))
    tools = [SimpleNamespace(name=name) for name in EXPECTED_TOOLS if name != "get_product_details"]

    with pytest.raises(ValueError, match="get_product_details"):
        factory(tools=tools, domain_policy="policy")


def test_patch_is_idempotent_and_validates_marker_integrity() -> None:
    once = patch_agent_source(BASELINE)
    assert patch_agent_source(once) == once
    assert once.count(PATCH_MARKER) == 1
    assert once.count(REPLACEMENT_FACTORY) == 1
    assert ORIGINAL_FACTORY not in once


def test_patch_rejects_an_unreviewed_factory_shape() -> None:
    with pytest.raises(ValueError, match="create_llm_agent"):
        patch_agent_source(BASELINE.replace("tools=tools", "tools=[]"))
