from __future__ import annotations

import pytest

from scripts.adapt_tau2_results import _user_simulator_prompt_provenance
from scripts.patch_tau2_retail_user_simulator import (
    BASELINE_ANCHOR,
    COMPLETION_GATE,
    PROMPT_MARKER,
    _write_github_outputs,
    patch_guidelines_source,
)

BASELINE = """# User Simulation Guidelines
You are playing the role of a customer contacting a customer service representative.

## Core Principles
- Generate one message at a time.

## Task Completion
- The goal is to continue the conversation until the task is complete.
- If the instruction goal is satisified, generate the '###STOP###' token to end the conversation.
- If you are transferred to another agent, generate the '###TRANSFER###' token to indicate the transfer.
- If you find yourself in a situation in which the scenario does not provide enough information to continue the conversation, generate the '###OUT-OF-SCOPE###' token to end the conversation.
Remember: maintain character consistency.
"""


def test_patch_adds_completion_gate_and_preserves_general_guidance() -> None:
    patched = patch_guidelines_source(BASELINE)

    assert PROMPT_MARKER in patched
    assert BASELINE_ANCHOR in patched
    assert "###STOP###" in patched
    assert "confirmation gives the agent permission" in patched
    assert "It does not prove that the operation happened" in patched
    assert "Do not output the `###STOP###` token in the same message" in patched
    assert "An offer, plan, item" in patched
    assert "unambiguous affirmative confirmation in your next message" in patched
    assert "Yes, I confirm both exchanges as described." in patched
    assert "Do not replace confirmation with" in patched
    assert "Before confirming a multi-item exchange, inspect the agent's immediately" in patched
    assert "A generic summary such as \"both exchanges as described\" is NOT a complete disclosure." in patched
    assert "If any required detail is missing, unclear, inconsistent with the scenario" in patched
    assert "Only after all required details are disclosed accurately" in patched
    assert "Never encourage the agent to bypass a guard" in patched
    assert patched.endswith(COMPLETION_GATE.strip() + "\n")
    assert patched.startswith(BASELINE.rstrip())


def test_adapter_records_verified_customer_prompt_provenance(monkeypatch) -> None:
    monkeypatch.setenv("AWA_TAU2_USER_PROMPT_MODE", "patched")
    monkeypatch.setenv("AWA_TAU2_USER_PROMPT_MARKER", PROMPT_MARKER)

    provenance = _user_simulator_prompt_provenance()

    assert provenance == {
        "mode": "patched",
        "marker": PROMPT_MARKER,
        "expected_marker": PROMPT_MARKER,
        "status": "verified_patched",
    }


def test_patch_is_idempotent() -> None:
    once = patch_guidelines_source(BASELINE)
    twice = patch_guidelines_source(once)

    assert twice == once
    assert twice.count(PROMPT_MARKER) == 1


def test_patch_rejects_unknown_guidelines_shape() -> None:
    with pytest.raises(ValueError, match="reviewed Tau2 user-simulation"):
        patch_guidelines_source("# unrelated guidelines")


def test_patch_rejects_partial_or_modified_marker() -> None:
    partial = BASELINE + "\n<!-- " + PROMPT_MARKER + " -->\n"
    with pytest.raises(ValueError, match="complete reviewed rule"):
        patch_guidelines_source(partial)


def test_prompt_output_helper_records_provenance(tmp_path) -> None:
    output_path = tmp_path / "github-output.txt"
    _write_github_outputs(str(output_path))

    assert output_path.read_text(encoding="utf-8").splitlines() == [
        "prompt_mode=patched",
        f"prompt_marker={PROMPT_MARKER}",
    ]


def test_prompt_output_helper_is_optional(tmp_path) -> None:
    _write_github_outputs(None)
    assert list(tmp_path.iterdir()) == []
