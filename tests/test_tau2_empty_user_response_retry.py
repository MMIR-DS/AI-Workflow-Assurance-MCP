from __future__ import annotations

from scripts.install_tau2_prewrite_guard import (
    USER_EMPTY_RESPONSE_PATCH_MARKER,
    patch_user_empty_response_source,
)

import pytest


UPSTREAM_BLOCK = """        assistant_message = generate(
            model=self.llm,
            messages=messages,
            tools=self.tools,
            call_name="user_simulator_response",
            **self.llm_args,
        )"""


def test_empty_user_response_patch_is_bounded_and_idempotent() -> None:
    patched = patch_user_empty_response_source(UPSTREAM_BLOCK)

    assert USER_EMPTY_RESPONSE_PATCH_MARKER in patched
    assert "for attempt in range(2)" in patched
    assert "retrying once" in patched
    assert "after one retry" in patched
    assert "refusing to synthesize a user message" in patched.lower()
    assert patch_user_empty_response_source(patched) == patched


def test_empty_user_response_patch_refuses_unreviewed_upstream_source() -> None:
    with pytest.raises(ValueError, match="Expected exactly one unmodified"):
        patch_user_empty_response_source(
            UPSTREAM_BLOCK.replace(
                'call_name="user_simulator_response"',
                'call_name="renamed_upstream_call"',
            )
        )
