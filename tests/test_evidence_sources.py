from __future__ import annotations

import json
from datetime import datetime

import pytest

from ai_workflow_assurance_mcp.evidence_sources import (
    EvidenceEnvelope,
    ReadOnlyEvidenceSource,
    Tau2ManifestFileSource,
)


def _manifest() -> dict:
    return {
        "manifest_type": "awa-tau2-source-evidence-v1",
        "assurance_scope": "pinned_simulator_replay_evidence_only",
        "production_ready": False,
        "release_eligible": False,
        "decision": "GO",
        "simulation_task_id": "0",
        "order_id": "#synthetic",
        "source_provenance": {
            "checked_out_commit": "a" * 40,
            "source_authenticity": "not_verified",
        },
        "database_evidence": {"write_count_in_trace": 1},
        "checks": {"check_a": True},
        "summary": {"passed_checks": 1, "total_checks": 1},
        "limitations": ["simulator only"],
        "data_minimization": {"raw_order_snapshots_included": False},
    }


def test_tau2_manifest_adapter_implements_read_only_protocol(tmp_path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(_manifest()), encoding="utf-8")

    source = Tau2ManifestFileSource(path)
    assert isinstance(source, ReadOnlyEvidenceSource)
    envelope = source.read_evidence()

    assert envelope.source_name == "tau2-pinned-simulator-manifest"
    assert envelope.source_version == "a" * 40
    assert envelope.assurance_scope == "pinned_simulator_replay_evidence_only"
    assert envelope.source_authenticity == "not_verified"
    assert envelope.release_eligible is False
    assert envelope.collected_at is None
    assert envelope.evidence["decision"] == "GO"
    assert "source_provenance" not in envelope.evidence
    assert path.exists()


def test_tau2_adapter_fails_closed_on_release_eligible_manifest(tmp_path) -> None:
    manifest = _manifest()
    manifest["release_eligible"] = True
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="release_eligible to false"):
        Tau2ManifestFileSource(path).read_evidence()


def test_tau2_adapter_fails_closed_on_wrong_scope(tmp_path) -> None:
    manifest = _manifest()
    manifest["assurance_scope"] = "production"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="unexpected assurance_scope"):
        Tau2ManifestFileSource(path).read_evidence()


def test_tau2_adapter_rejects_malformed_json(tmp_path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text("{broken", encoding="utf-8")

    with pytest.raises(ValueError, match="valid JSON manifest"):
        Tau2ManifestFileSource(path).read_evidence()


def test_envelope_rejects_unverified_release_evidence() -> None:
    with pytest.raises(ValueError, match="unverified source evidence"):
        EvidenceEnvelope(
            source_name="test",
            source_version="commit",
            assurance_scope="test-only",
            source_authenticity="not_verified",
            release_eligible=True,
            evidence={},
        )


def test_envelope_rejects_naive_collection_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        EvidenceEnvelope(
            source_name="test",
            source_version="commit",
            assurance_scope="test-only",
            source_authenticity="not_verified",
            release_eligible=False,
            evidence={},
            collected_at=datetime(2026, 10, 11, 0, 0),
        )
