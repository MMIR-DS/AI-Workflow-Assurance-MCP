"""Package a pinned tau2 independent-DB replay report as an evidence manifest.

This is a read-only post-processor: it does not execute model calls, query a database,
or replay workflow writes. It preserves the limits of the upstream replay evidence.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_CHECKS = {
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
}


def _safe_order_projection(order: dict[str, Any]) -> dict[str, Any]:
    """Expose only order fields useful for audit; omit customer/payment details."""
    allowed = ("order_id", "status", "exchange_items", "exchange_new_items", "exchange_price_difference")
    projection = {key: order[key] for key in allowed if key in order}
    items = order.get("items", [])
    if isinstance(items, list):
        projection["items"] = [
            {key: item[key] for key in ("item_id", "product_id", "price", "options") if key in item}
            for item in items if isinstance(item, dict)
        ]
    return projection


def build_evidence_manifest(report: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize a verifier report without changing its evidence."""
    if not isinstance(report, dict):
        raise ValueError("report must be a JSON object.")
    if report.get("schema_version") != "1.0.0":
        raise ValueError("report schema_version must be '1.0.0'.")
    if report.get("verification_type") != "pinned_tau2_retail_database_replay":
        raise ValueError("unsupported verification_type.")

    source = report.get("source")
    evidence = report.get("database_evidence")
    checks = report.get("checks")
    summary = report.get("summary")
    if not isinstance(source, dict) or not isinstance(evidence, dict):
        raise ValueError("report must include source and database_evidence objects.")
    if not isinstance(checks, dict) or not isinstance(summary, dict):
        raise ValueError("report must include checks and summary objects.")

    missing_checks = REQUIRED_CHECKS - set(checks)
    if missing_checks:
        raise ValueError(f"report is missing required checks: {', '.join(sorted(missing_checks))}.")
    if any(not isinstance(value, bool) for value in checks.values()):
        raise ValueError("every report check must be a boolean.")
    if not isinstance(summary.get("passed_checks"), int) or not isinstance(summary.get("total_checks"), int):
        raise ValueError("summary passed_checks and total_checks must be integers.")
    if summary["total_checks"] != len(checks) or summary["passed_checks"] != sum(checks.values()):
        raise ValueError("summary counts do not reconcile with the report checks.")

    decision = report.get("decision")
    if decision not in {"GO", "HOLD", "NO_GO"}:
        raise ValueError("decision must be GO, HOLD, or NO_GO.")
    checks_all_pass = all(checks.values())
    if (decision == "GO") != checks_all_pass:
        raise ValueError("decision does not reconcile with the individual checks.")

    trace_commit = source.get("trace_commit")
    checked_out_commit = source.get("checked_out_commit")
    if not isinstance(trace_commit, str) or not trace_commit.strip():
        raise ValueError("source.trace_commit must be a non-empty string.")
    if not isinstance(checked_out_commit, str) or not checked_out_commit.strip():
        raise ValueError("source.checked_out_commit must be a non-empty string.")
    database_reader = source.get("database_reader")
    if not isinstance(database_reader, str) or not database_reader.strip():
        raise ValueError("source.database_reader must be a non-empty string.")
    commit_match = checks["source_code_commit_matches_trace"]
    if commit_match != (trace_commit == checked_out_commit):
        raise ValueError("source commit metadata does not reconcile with source_code_commit_matches_trace.")

    before = evidence.get("before")
    after = evidence.get("after")
    if not isinstance(before, dict) or not isinstance(after, dict):
        raise ValueError("database_evidence.before and after must be JSON objects.")
    if str(before.get("order_id", "")) != str(report.get("order_id", "")):
        raise ValueError("database_evidence.before does not match report.order_id.")
    if str(after.get("order_id", "")) != str(report.get("order_id", "")):
        raise ValueError("database_evidence.after does not match report.order_id.")

    collateral_check = evidence.get("other_database_entities_unchanged")
    if not isinstance(collateral_check, bool):
        raise ValueError("database_evidence.other_database_entities_unchanged must be a boolean.")
    if collateral_check is not checks["no_other_database_entities_mutated"]:
        raise ValueError("collateral-mutation metadata does not reconcile with its check.")
    write_count = evidence.get("write_count_in_trace")
    if isinstance(write_count, bool) or not isinstance(write_count, int) or write_count < 0:
        raise ValueError("database_evidence.write_count_in_trace must be a non-negative integer.")
    if decision == "GO" and write_count != 1:
        raise ValueError("a GO report must contain exactly one write in the trace.")

    hashes = {
        "before": evidence.get("full_database_before_sha256"),
        "after": evidence.get("full_database_after_sha256"),
    }
    if any(not isinstance(value, str) or not HASH_PATTERN.fullmatch(value) for value in hashes.values()):
        raise ValueError("full-database fingerprints must be 64-character lowercase SHA-256 hex strings.")
    if evidence.get("tool_return_value_used_for_decision") is not False:
        raise ValueError("report must explicitly confirm the tool return value was not used for the decision.")
    tamper_probe = evidence.get("tamper_probe")
    if not isinstance(tamper_probe, dict) or tamper_probe.get("detected") is not checks["tamper_probe_is_detected"]:
        raise ValueError("tamper probe metadata does not reconcile with its check.")

    return {
        "schema_version": "1.0.0",
        "manifest_type": "awa-tau2-source-evidence-v1",
        "verification_type": report["verification_type"],
        "simulation_task_id": report.get("simulation_task_id"),
        "order_id": report.get("order_id"),
        "decision": decision,
        "assurance_scope": "pinned_simulator_replay_evidence_only",
        "production_ready": False,
        "release_eligible": False,
        "release_eligibility_reason": "simulator replay evidence is not authenticated production-source evidence",
        "source_provenance": {
            "trace_commit": trace_commit,
            "checked_out_commit": checked_out_commit,
            "source_commit_match": commit_match,
            "database_reader": database_reader,
            "database_path": "[redacted local path]",
            "source_authenticity": "not_verified",
            "cryptographic_signature_validation": "not_implemented",
        },
        "database_evidence": {
            "before": _safe_order_projection(before),
            "after": _safe_order_projection(after),
            "full_database_before_sha256": hashes["before"],
            "full_database_after_sha256": hashes["after"],
            "other_database_entities_unchanged": evidence.get("other_database_entities_unchanged") is True,
            "write_count_in_trace": evidence.get("write_count_in_trace"),
            "tool_return_value_used_for_decision": False,
            "tamper_probe": tamper_probe,
        },
        "checks": checks,
        "summary": summary,
        "data_minimization": {
            "raw_order_snapshots_included": False,
            "redacted_fields": ["address", "user_id", "fulfillments", "payment_history", "exchange_payment_method_id", "return_payment_method_id", "cancel_reason"],
        },
        "limitations": [
            "This manifest packages a deterministic replay against a pinned simulator; it is not a snapshot of the original model run's live in-memory database.",
            "The replay report and its source data are not cryptographically authenticated by this adapter.",
            "SHA-256 fingerprints support change detection; they are not digital signatures or proof of provenance.",
            "A successful simulated replay is not evidence of production readiness or general workflow reliability.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True, type=Path, help="Independent tau2 DB replay report JSON.")
    parser.add_argument("--output", required=True, type=Path, help="Output evidence manifest JSON.")
    args = parser.parse_args()
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        manifest = build_evidence_manifest(report)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "manifest_type": manifest["manifest_type"],
        "decision": manifest["decision"],
        "passed_checks": manifest["summary"]["passed_checks"],
        "total_checks": manifest["summary"]["total_checks"],
        "production_ready": manifest["production_ready"],
        "output": str(args.output),
    }, indent=2))
    return 0 if manifest["decision"] == "GO" else 2


if __name__ == "__main__":
    raise SystemExit(main())
