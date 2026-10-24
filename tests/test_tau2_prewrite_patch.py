from __future__ import annotations

import pytest

from scripts.install_tau2_prewrite_guard import (
    ORIGINAL,
    PATCH_MARKER,
    REPLACEMENT,
    patch_orchestrator_source,
)


def test_patcher_replaces_exactly_one_expected_dispatch_loop() -> None:
    source = "class BaseOrchestrator:\n    def _execute_tool_calls(self):\n" + ORIGINAL + "\n"
    patched = patch_orchestrator_source(source)

    assert PATCH_MARKER in patched
    # Validators are dispatched through one shared table and one approved write call site.
    # Pending-item changes are limited to one pair and audited after execution; create_order remains denied.
    assert patched.count("self.environment.get_response(tool_call)") == 2
    assert 'policy = awa_write_policies.get(tool_call.name)' in patched
    assert 'preflight = policy["validator"](' in patched
    assert "evaluate_tau2_prewrite," in patched
    assert "evaluate_tau2_cancel_prewrite," in patched
    assert "evaluate_tau2_address_prewrite," in patched
    assert "evaluate_tau2_payment_prewrite," in patched
    assert "evaluate_tau2_pending_items_prewrite" in patched
    assert "audit_tau2_single_pending_item_write_response" in patched
    assert "AWA_POSTWRITE_AUDIT_NOT_PASS" in patched
    assert "exactly one distinct old/new item pair" in patched
    assert "pending-order item modification is disabled" not in patched
    assert '"modify_pending_order_items"' in patched
    assert '"create_order"' in patched
    assert "evaluate_tau2_user_address_prewrite," in patched
    assert "evaluate_tau2_return_prewrite," in patched
    assert "no reviewed " in patched
    assert "AWA policy adapter" in patched
    assert "awa_passthrough_tools" in patched
    assert "unrecognized or unreviewed tool name" in patched
    assert "awa_write_orders_seen = set()" in patched
    assert "second write for the same order" in patched
    assert "Do not make any further write attempt" in patched
    assert "The operation remains blocked" in patched
    assert 'getattr(self, "_awa_prewrite_no_go_latched", False)' in patched
    assert "self._awa_prewrite_no_go_latched = True" in patched
    assert "prior write was blocked earlier in this benchmark run" in patched
    assert "cancel_pending_order" in patched
    assert patched != source



def test_patcher_adds_opt_in_no_go_injection_before_any_real_write_callback() -> None:
    patched = patch_orchestrator_source("class BaseOrchestrator:\n    def _execute_tool_calls(self):\n" + ORIGINAL)

    assert "AWA_TEST_FORCE_NO_GO_FIRST_WRITE_V1" in patched
    assert 'environ.get("AWA_TEST_FORCE_NO_GO_FIRST_WRITE") == "1"' in patched
    assert "self._awa_test_forced_no_go_once = True" in patched
    assert "controlled test denial" in patched
    assert "no mutation was executed" in patched
    assert patched.index("AWA_TEST_FORCE_NO_GO_FIRST_WRITE_V1") < patched.index(
        'preflight = policy["validator"]('
    )


def test_patcher_is_idempotent() -> None:
    source = "class BaseOrchestrator:\n" + ORIGINAL
    patched = patch_orchestrator_source(source)

    assert patch_orchestrator_source(patched) == patched


def test_patcher_fails_closed_on_unrecognized_upstream_source() -> None:
    with pytest.raises(ValueError, match="Refusing to patch"):
        patch_orchestrator_source("def _execute_tool_calls(self):\n    return []")


def test_patcher_refuses_legacy_v2_patch_without_silently_accepting_it() -> None:
    stale_patch = REPLACEMENT.replace(PATCH_MARKER, "AWA_PREWRITE_GUARD_PATCH_V2")
    with pytest.raises(ValueError, match="Refusing to patch"):
        patch_orchestrator_source(stale_patch)


def test_patcher_does_not_patch_ambiguous_duplicate_dispatch_loops() -> None:
    source = ORIGINAL + "\n" + ORIGINAL
    with pytest.raises(ValueError, match="exactly one"):
        patch_orchestrator_source(source)
