from __future__ import annotations

import pytest

from scripts.patch_tau2_retail_agent_prompt import PROMPT_MARKER, patch_agent_source


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
    assert "Never request card numbers" in patched
    assert "one permitted exchange write" in patched
    assert "Always follow the policy" not in patched  # exact baseline is preserved below
    assert "Try to be helpful and always follow the policy." in patched
    assert 'SYSTEM_PROMPT = "unchanged"' in patched


def test_patch_is_idempotent() -> None:
    once = patch_agent_source(BASELINE)
    twice = patch_agent_source(once)

    assert twice == once
    assert twice.count(PROMPT_MARKER) == 1


def test_patch_rejects_unknown_agent_prompt_shape() -> None:
    with pytest.raises(ValueError, match="AGENT_INSTRUCTION"):
        patch_agent_source('AGENT_INSTRUCTION = "changed"')
