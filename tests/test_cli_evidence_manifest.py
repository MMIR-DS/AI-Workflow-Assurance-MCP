from __future__ import annotations

import json
import sys

import pytest

from ai_workflow_assurance_mcp.cli import main


def _manifest() -> dict:
    check_names = (
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
    checks = {name: True for name in check_names}
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
            "checked_out_commit": "b" * 40,
            "source_authenticity": "not_verified",
        },
        "database_evidence": {
            "before": {"order_id": "#synthetic", "status": "delivered"},
            "after": {"order_id": "#synthetic", "status": "exchange requested"},
            "full_database_before_sha256": "1" * 64,
            "full_database_after_sha256": "2" * 64,
            "other_database_entities_unchanged": True,
            "write_count_in_trace": 1,
            "tool_return_value_used_for_decision": False,
            "tamper_probe": {"mutated_field": "status", "detected": True},
        },
        "checks": checks,
        "summary": {"passed_checks": len(checks), "total_checks": len(checks)},
        "limitations": ["simulator only"],
        "data_minimization": {"raw_order_snapshots_included": False},
    }

def test_inspect_evidence_cli_emits_normalized_nonproduction_envelope(
    tmp_path, monkeypatch, capsys
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["ai-workflow-assurance", "inspect-evidence", "--manifest", str(manifest_path)],
    )

    main()
    result = json.loads(capsys.readouterr().out)

    assert result["source_name"] == "tau2-pinned-simulator-manifest"
    assert result["source_version"] == "b" * 40
    assert result["source_authenticity"] == "not_verified"
    assert result["assurance_scope"] == "pinned_simulator_replay_evidence_only"
    assert result["release_eligible"] is False
    assert result["collected_at"] is None
    assert result["evidence"]["decision"] == "GO"
    assert "customer_address" not in result["evidence"]


def test_inspect_evidence_cli_writes_requested_output_file(tmp_path, monkeypatch) -> None:
    manifest_path = tmp_path / "manifest.json"
    output_path = tmp_path / "normalized.json"
    manifest_path.write_text(json.dumps(_manifest()), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ai-workflow-assurance",
            "inspect-evidence",
            "--manifest",
            str(manifest_path),
            "--output",
            str(output_path),
        ],
    )

    main()
    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert result["release_eligible"] is False
    assert "customer_address" not in result["evidence"]


def test_inspect_evidence_cli_fails_closed_on_oversized_manifest(
    tmp_path, monkeypatch, capsys
) -> None:
    manifest_path = tmp_path / "large.json"
    manifest_path.write_text(" " * 1_048_577, encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["ai-workflow-assurance", "inspect-evidence", "--manifest", str(manifest_path)],
    )

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 2
    assert "size limit" in capsys.readouterr().err
