from __future__ import annotations

from scripts.patch_tau2_retail_agent_prompt import (
    PROMPT_MARKER,
    _write_github_outputs,
    patch_agent_source,
)

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
    assert "single permitted exchange write" in patched
    assert "exact old item ID and replacement item ID" in patched
    assert "exact payment_method_id string" in patched
    assert "Price difference:" in patched
    assert "Do not include product IDs or other 8+-digit identifiers" in patched
    assert "Do not repeat the write attempt" in patched
    assert "Try to be helpful and always follow the policy." in patched
    assert 'SYSTEM_PROMPT = "unchanged"' in patched


def test_patch_is_idempotent() -> None:
    once = patch_agent_source(BASELINE)
    twice = patch_agent_source(once)

    assert twice == once
    assert twice.count(PROMPT_MARKER) == 1


def test_patch_rejects_unknown_agent_prompt_shape() -> None:
    try:
        patch_agent_source('AGENT_INSTRUCTION = "changed"')
    except ValueError as exc:
        assert "AGENT_INSTRUCTION" in str(exc)
    else:
        raise AssertionError("Unexpected prompt shape must be rejected.")


def test_patch_writes_prompt_provenance_to_github_step_outputs(tmp_path) -> None:
    output_path = tmp_path / "github-output.txt"

    _write_github_outputs(str(output_path))

    assert output_path.read_text(encoding="utf-8").splitlines() == [
        "prompt_mode=patched",
        f"prompt_marker={PROMPT_MARKER}",
    ]


def test_prompt_output_helper_is_optional_outside_github_actions(tmp_path) -> None:
    _write_github_outputs(None)
    assert list(tmp_path.iterdir()) == []
