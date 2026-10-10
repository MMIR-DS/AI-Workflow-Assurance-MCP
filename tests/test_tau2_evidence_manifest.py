from __future__ import annotations

import copy

import pytest

from scripts.adapt_tau2_db_evidence import REQUIRED_CHECKS, build_evidence_manifest


def _valid_report() -> dict:
    checks = {key: True for key in REQUIRED_CHECKS}
    return {
        "schema_version": "1.0.0",
        "verification_type": "pinned_tau2_retail_database_replay",
        "simulation_task_id": "0",
        "order_id": "#W2378156",
        "decision": "GO",
        "source": {
            "trace_commit": "a" * 40,
            "checked_out_commit": "a" * 40,
            "database_path": "RetailDB",
            "database_reader": "RetailDB.orders[order_id].model_dump(mode='json')",
        },
        "database_evidence": {
            "before": {"order_id": "#W2378156", "status": "delivered"},
            "after": {"order_id": "#W2378156", "status": "exchange requested"},
            "full_database_before_sha256": "1" * 64,
            "full_database_after_sha256": "2" * 64,
            "other_database_entities_unchanged": True,
            "write_count_in_trace": 1,
            "tool_return_value_used_for_decision": False,
            "tamper_probe": {"mutated_field": "status", "detected": True},
        },
        "checks": checks,
        "summary": {
            "passed_checks": len(checks),
            "total_checks": len(checks),
            "computed_price_difference": "-16.63",
        },
    }


def test_valid_independent_db_report_becomes_scoped_manifest() -> None:
    manifest = build_evidence_manifest(_valid_report())

    assert manifest["decision"] == "GO"
    assert manifest["production_ready"] is False
    assert manifest["assurance_scope"] == "pinned_simulator_replay_evidence_only"
    assert manifest["source_provenance"]["source_authenticity"] == "not_verified"
    assert manifest["database_evidence"]["tool_return_value_used_for_decision"] is False
    assert manifest["summary"]["passed_checks"] == manifest["summary"]["total_checks"]


def test_manifest_rejects_go_with_failed_check() -> None:
    report = _valid_report()
    report["checks"]["write_execution_succeeded"] = False

    with pytest.raises(ValueError, match="summary counts do not reconcile"):
        build_evidence_manifest(report)


def test_manifest_rejects_inconsistent_decision_even_if_counts_match() -> None:
    report = _valid_report()
    report["decision"] = "NO_GO"

    with pytest.raises(ValueError, match="decision does not reconcile"):
        build_evidence_manifest(report)


def test_manifest_rejects_source_commit_drift() -> None:
    report = _valid_report()
    report["source"]["checked_out_commit"] = "b" * 40
    report["checks"]["source_code_commit_matches_trace"] = False
    report["decision"] = "NO_GO"
    report["summary"]["passed_checks"] = len(report["checks"]) - 1

    manifest = build_evidence_manifest(report)
    assert manifest["decision"] == "NO_GO"
    assert manifest["source_provenance"]["source_commit_match"] is False


def test_manifest_rejects_source_commit_metadata_mismatch() -> None:
    report = _valid_report()
    report["source"]["checked_out_commit"] = "b" * 40

    with pytest.raises(ValueError, match="source commit metadata does not reconcile"):
        build_evidence_manifest(report)


def test_manifest_rejects_malformed_database_fingerprint() -> None:
    report = _valid_report()
    report["database_evidence"]["full_database_after_sha256"] = "not-a-hash"

    with pytest.raises(ValueError, match="64-character lowercase SHA-256"):
        build_evidence_manifest(report)


def test_manifest_rejects_missing_required_check() -> None:
    report = _valid_report()
    report["checks"].pop("tamper_probe_is_detected")
    report["summary"]["total_checks"] -= 1
    report["summary"]["passed_checks"] -= 1

    with pytest.raises(ValueError, match="missing required checks"):
        build_evidence_manifest(report)


def test_manifest_rejects_use_of_write_tool_return_value() -> None:
    report = _valid_report()
    report["database_evidence"]["tool_return_value_used_for_decision"] = True

    with pytest.raises(ValueError, match="tool return value was not used"):
        build_evidence_manifest(report)


def test_manifest_rejects_tamper_probe_mismatch() -> None:
    report = _valid_report()
    report["database_evidence"]["tamper_probe"]["detected"] = False

    with pytest.raises(ValueError, match="tamper probe metadata"):
        build_evidence_manifest(report)
