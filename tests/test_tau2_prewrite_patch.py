from __future__ import annotations

import pytest

from scripts.install_tau2_prewrite_guard import (
    PATCH_MARKER,
    ORIGINAL,
    patch_orchestrator_source,
)


def test_patcher_replaces_exactly_one_expected_dispatch_loop() -> None:
    source = "class BaseOrchestrator:\n    def _execute_tool_calls(self):\n" + ORIGINAL + "\n"
    patched = patch_orchestrator_source(source)

    assert PATCH_MARKER in patched
    assert patched.count("self.environment.get_response(tool_call)") == 2
    assert "evaluate_tau2_prewrite(self.trajectory, tool_call)" in patched
    assert patched != source


def test_patcher_is_idempotent() -> None:
    source = "class BaseOrchestrator:\n" + ORIGINAL
    patched = patch_orchestrator_source(source)

    assert patch_orchestrator_source(patched) == patched


def test_patcher_fails_closed_on_unrecognized_upstream_source() -> None:
    with pytest.raises(ValueError, match="Refusing to patch"):
        patch_orchestrator_source("def _execute_tool_calls(self):\n    return []")


def test_patcher_does_not_patch_ambiguous_duplicate_dispatch_loops() -> None:
    source = ORIGINAL + "\n" + ORIGINAL
    with pytest.raises(ValueError, match="exactly one"):
        patch_orchestrator_source(source)
