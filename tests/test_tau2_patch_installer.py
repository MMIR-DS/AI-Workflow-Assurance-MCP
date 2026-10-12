"""Regression tests for the Tau2 source patcher's fail-closed behavior."""
from __future__ import annotations

import pytest

from scripts.install_tau2_prewrite_guard import (
    ORIGINAL,
    PATCH_MARKER,
    REPLACEMENT,
    patch_orchestrator_source,
)


def test_patch_is_idempotent_only_for_the_complete_reviewed_replacement() -> None:
    patched = patch_orchestrator_source(ORIGINAL)

    assert PATCH_MARKER in patched
    assert patched.count(PATCH_MARKER) == 1
    assert patched.count(REPLACEMENT) == 1
    assert patch_orchestrator_source(patched) == patched


def test_patch_rejects_marker_without_complete_replacement() -> None:
    partial_source = f"# {PATCH_MARKER}\n{ORIGINAL}"

    with pytest.raises(ValueError, match="complete reviewed dispatcher replacement"):
        patch_orchestrator_source(partial_source)


def test_patch_rejects_modified_guard_even_when_marker_remains() -> None:
    patched = patch_orchestrator_source(ORIGINAL)
    corrupted = patched.replace(
        "evaluate_tau2_prewrite(self.trajectory, tool_call)",
        "evaluate_tau2_prewrite(self.trajectory, None)",
        1,
    )

    assert PATCH_MARKER in corrupted
    with pytest.raises(ValueError, match="complete reviewed dispatcher replacement"):
        patch_orchestrator_source(corrupted)
