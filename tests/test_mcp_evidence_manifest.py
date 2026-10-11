from __future__ import annotations

import json

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from ai_workflow_assurance_mcp.server import inspect_tau2_evidence_manifest


def _manifest() -> dict:
    names = (
        "source_code_commit_matches_trace",
        "pre_state_matches_recorded_order_read",
        "write_execution_succeeded",
        "no_other_database_entities_mutated",
        "independent_db_state_matches_recorded_exchange_response",
        "replay_db_payment_profile_and_original_transaction_match",
        "unrelated_order_fields_unchanged_in_database",
        "database_price_recalculation_matches_post_state",
        "database_transition_matches_write_request",
        "tamper_probe_is_detected",
    )
    checks = {name: True for name in names}
    return {
        "schema_version": "1.0.0",
        "manifest_type": "awa-tau2-source-evidence-v1",
        "assurance_scope": "pinned_simulator_replay_evidence_only",
        "production_ready": False,
        "release_eligible": False,
        "decision": "GO",
        "simulation_task_id": "0",
        "order_id": "#synthetic",
        "source_provenance": {
            "checked_out_commit": "c" * 40,
            "source_authenticity": "not_verified",
        },
        "database_evidence": {
            "before": {
                "order_id": "#synthetic",
                "status": "delivered",
                "address": {"street": "private"},
            },
            "after": {
                "order_id": "#synthetic",
                "status": "exchange requested",
                "payment_history": [{"payment_method_id": "private"}],
            },
            "full_database_before_sha256": "1" * 64,
            "full_database_after_sha256": "2" * 64,
            "other_database_entities_unchanged": True,
            "write_count_in_trace": 1,
            "tool_return_value_used_for_decision": False,
            "tamper_probe": {"mutated_field": "status", "detected": True},
        },
        "checks": checks,
        "summary": {"passed_checks": len(checks), "total_checks": len(checks)},
        "data_minimization": {"raw_order_snapshots_included": False},
    }


def test_mcp_tool_returns_strict_nonproduction_evidence_projection() -> None:
    result = inspect_tau2_evidence_manifest(json.dumps(_manifest()))

    assert result["source_name"] == "tau2-pinned-simulator-manifest"
    assert result["source_version"] == "c" * 40
    assert result["source_authenticity"] == "not_verified"
    assert result["release_eligible"] is False
    assert result["evidence"]["decision"] == "GO"
    assert "address" not in result["evidence"]["database_evidence"]["before"]
    assert "payment_history" not in result["evidence"]["database_evidence"]["after"]


def test_mcp_tool_rejects_invalid_manifest() -> None:
    manifest = _manifest()
    manifest["checks"]["unreviewed_extra_check"] = True

    with pytest.raises(ToolError, match="exactly the supported tau2 check names"):
        inspect_tau2_evidence_manifest(json.dumps(manifest))


def test_mcp_tool_rejects_oversized_json() -> None:
    with pytest.raises(ToolError, match="size limit"):
        inspect_tau2_evidence_manifest(" " * 1_048_577)
