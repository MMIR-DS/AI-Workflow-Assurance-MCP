"""Regression tests for the Tau2 source patcher's fail-closed behavior."""
from __future__ import annotations

import pytest

from scripts.install_tau2_prewrite_guard import (
    ORIGINAL,
    PATCH_MARKER,
    REPLACEMENT,
    REPLAY_ORIGINAL,
    REPLAY_PATCH_MARKER,
    REPLAY_REPLACEMENT,
    patch_environment_replay_source,
    patch_orchestrator_source,
)


def test_patch_is_idempotent_only_for_the_complete_reviewed_replacement() -> None:
    patched = patch_orchestrator_source(ORIGINAL)

    assert PATCH_MARKER in patched
    assert patched.count(PATCH_MARKER) == 1
    assert patched.count(REPLACEMENT) == 1
    assert "TAU2_PASSTHROUGH_TOOLS as awa_shared_passthrough_tools" in REPLACEMENT
    assert "set(awa_shared_passthrough_tools)" in REPLACEMENT
    assert patch_orchestrator_source(patched) == patched


def test_patch_rejects_marker_without_complete_replacement() -> None:
    partial_source = f"# {PATCH_MARKER}\n{ORIGINAL}"

    with pytest.raises(ValueError, match="complete reviewed dispatcher replacement"):
        patch_orchestrator_source(partial_source)


def test_patch_rejects_modified_guard_even_when_marker_remains() -> None:
    patched = patch_orchestrator_source(ORIGINAL)
    corrupted = patched.replace(
        "evaluate_tau2_prewrite,",
        "evaluate_tau2_prewrite_broken,",
        1,
    )

    assert PATCH_MARKER in corrupted
    with pytest.raises(ValueError, match="complete reviewed dispatcher replacement"):
        patch_orchestrator_source(corrupted)


def test_environment_replay_patch_skips_recorded_awa_blocked_writes() -> None:
    patched = patch_environment_replay_source(REPLAY_ORIGINAL)

    assert REPLAY_PATCH_MARKER in patched
    assert patched.count(REPLAY_PATCH_MARKER) == 1
    assert patched.count(REPLAY_REPLACEMENT) == 1
    assert "expected_response.error" in REPLAY_REPLACEMENT
    assert "recorded_content.startswith(\"AWA_PREWRITE_NO_GO:\")" in REPLAY_REPLACEMENT
    assert "continue" in REPLAY_REPLACEMENT
    assert patch_environment_replay_source(patched) == patched


def test_environment_replay_patch_rejects_drift_and_partial_markers() -> None:
    with pytest.raises(ValueError, match="Expected exactly one unmodified mutating-tool replay block"):
        patch_environment_replay_source("def set_state(self):\n    pass\n")

    partial = f"# {REPLAY_PATCH_MARKER}\n{REPLAY_ORIGINAL}"
    with pytest.raises(ValueError, match="complete reviewed replay replacement"):
        patch_environment_replay_source(partial)
