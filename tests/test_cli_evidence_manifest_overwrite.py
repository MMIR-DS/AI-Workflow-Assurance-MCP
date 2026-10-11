from __future__ import annotations

import json
import sys

import pytest

from ai_workflow_assurance_mcp.cli import main


def _manifest() -> dict:
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
        "database_evidence": {"write_count_in_trace": 1},
        "checks": {"check_a": True},
        "summary": {"passed_checks": 1, "total_checks": 1},
        "limitations": ["simulator only"],
        "data_minimization": {"raw_order_snapshots_included": False},
    }


def test_inspect_evidence_cli_refuses_to_overwrite_source_manifest(
    tmp_path, monkeypatch, capsys
) -> None:
    manifest_path = tmp_path / "manifest.json"
    original = json.dumps(_manifest())
    manifest_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ai-workflow-assurance",
            "inspect-evidence",
            "--manifest",
            str(manifest_path),
            "--output",
            str(manifest_path),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 2
    assert "must differ from the source manifest" in capsys.readouterr().err
    assert manifest_path.read_text(encoding="utf-8") == original
