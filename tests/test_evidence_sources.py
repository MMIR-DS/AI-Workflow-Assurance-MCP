from __future__ import annotations

import json
from datetime import datetime

import pytest

from ai_workflow_assurance_mcp.evidence_sources import (
    EvidenceEnvelope,
    ReadOnlyEvidenceSource,
    Tau2ManifestFileSource,
)

REQUIRED_CHECKS = (
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


def _manifest() -> dict:
    checks = {key: True for key in REQUIRED_CHECKS}
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
            "checked_out_commit": "a" * 40,
            "source_authenticity": "not_verified",
        },
        "database_evidence": {
            "before": {
                "order_id": "#synthetic",
                "status": "delivered",
                "address": {"street": "private address"},
                "items": [
                    {
                        "item_id": "item-1",
                        "product_id": "product-1",
                        "price": 10,
                        "internal_note": "private note",
                    }
                ],
            },
            "after": {
                "order_id": "#synthetic",
                "status": "exchange requested",
                "user_id": "private-user-id",
                "payment_history": [{"payment_method_id": "private-payment-id"}],
            },
            "full_database_before_sha256": "1" * 64,
            "full_database_after_sha256": "2" * 64,
            "other_database_entities_unchanged": True,
            "write_count_in_trace": 1,
            "tool_return_value_used_for_decision": False,
            "tamper_probe": {"mutated_field": "status", "detected": True, "private": "drop me"},
            "unexpected_private_field": "drop me",
        },
        "checks": checks,
        "summary": {
            "passed_checks": len(checks),
            "total_checks": len(checks),
            "private_note": "must not propagate",
        },
        "limitations": ["attacker-controlled text must not propagate"],
        "data_minimization": {
            "raw_order_snapshots_included": False,
            "redacted_fields": ["attacker-controlled field"],
        },
        "customer_address": "must not appear in normalized output",
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
    assert "customer_address" not in envelope.evidence
    assert "address" not in envelope.evidence["database_evidence"]["before"]
    assert "user_id" not in envelope.evidence["database_evidence"]["after"]
    assert envelope.evidence["database_evidence"]["before"]["items"] == [
        {"item_id": "item-1", "product_id": "product-1", "price": 10}
    ]
    assert "unexpected_private_field" not in envelope.evidence["database_evidence"]
    assert "private" not in envelope.evidence["database_evidence"]["tamper_probe"]
    assert "private_note" not in envelope.evidence["summary"]
    assert envelope.evidence["limitations"][0].startswith("This manifest packages")
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


def test_tau2_adapter_rejects_malformed_source_commit(tmp_path) -> None:
    manifest = _manifest()
    manifest["source_provenance"]["checked_out_commit"] = "not-a-commit"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="40 lowercase hexadecimal"):
        Tau2ManifestFileSource(path).read_evidence()


def test_tau2_adapter_rejects_unknown_check_names(tmp_path) -> None:
    manifest = _manifest()
    manifest["checks"]["customer_address"] = True
    manifest["summary"]["total_checks"] += 1
    manifest["summary"]["passed_checks"] += 1
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="exactly the supported tau2 check names"):
        Tau2ManifestFileSource(path).read_evidence()


def test_tau2_adapter_rejects_inconsistent_summary(tmp_path) -> None:
    manifest = _manifest()
    manifest["summary"]["passed_checks"] -= 1
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="summary counts do not reconcile"):
        Tau2ManifestFileSource(path).read_evidence()


def test_tau2_adapter_rejects_malformed_database_fingerprint(tmp_path) -> None:
    manifest = _manifest()
    manifest["database_evidence"]["full_database_after_sha256"] = "not-a-hash"
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="64 lowercase SHA-256"):
        Tau2ManifestFileSource(path).read_evidence()


def test_tau2_adapter_rejects_naive_release_eligibility_types(tmp_path) -> None:
    manifest = _manifest()
    manifest["release_eligible"] = 0
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="release_eligible to false"):
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


def test_tau2_adapter_rejects_non_string_decision(tmp_path) -> None:
    manifest = _manifest()
    manifest["decision"] = ["GO"]
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="decision must be GO, HOLD, or NO_GO"):
        Tau2ManifestFileSource(path).read_evidence()


def test_tau2_adapter_rejects_nested_non_string_item_options(tmp_path) -> None:
    manifest = _manifest()
    manifest["database_evidence"]["before"]["items"][0]["options"] = {
        "private_customer_note": "must not pass through"
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="item options must be null or a list of short strings"):
        Tau2ManifestFileSource(path).read_evidence()


def test_tau2_adapter_rejects_unexpected_nested_exchange_items_type(tmp_path) -> None:
    manifest = _manifest()
    manifest["database_evidence"]["after"]["exchange_items"] = {
        "customer_address": "must not pass through"
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="exchange_items must be null or a list of short strings"):
        Tau2ManifestFileSource(path).read_evidence()
