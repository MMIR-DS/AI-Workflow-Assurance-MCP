"""Smoke-test the MCP stdio boundary from the installed wheel.

This deliberately runs without PYTHONPATH so the server executable must import the
installed package, not this checkout's source tree. All observations are synthetic;
no model API or external service is called.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import os
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


SPEC: dict[str, Any] = {
    "id": "wheel-mcp-smoke",
    "name": "Installed wheel MCP smoke",
    "version": "1.0.0",
    "criteria": [
        {
            "id": "decision_matches",
            "operator": "equals",
            "actual_path": "decision",
            "expected_path": "decision",
            "severity": "critical",
        }
    ],
    "thresholds": {"min_pass_rate": 1.0, "max_critical_failures": 0},
}
CASES = [
    {
        "case_id": "wheel-smoke-control",
        "expected": {"decision": "approve"},
        "actual": {"decision": "approve"},
        "human_review_observed": False,
        "cost_usd": 0.01,
        "latency_ms": 100,
    }
]
EXPECTED_TOOLS = {
    "validate_workflow_spec",
    "run_eval_suite",
    "compare_eval_runs",
    "explain_failures",
    "generate_release_report",
    "inspect_tau2_evidence_manifest",
    "inspect_github_actions_run",
    "preflight_sensitive_write",
}


def _is_error(result: object) -> bool:
    return bool(getattr(result, "is_error", getattr(result, "isError", False)))


def _content_text(result: object) -> str:
    parts = getattr(result, "content", []) or []
    return "\n".join(str(getattr(part, "text", "")) for part in parts)


def _payload(result: object) -> dict[str, Any]:
    return json.loads(_content_text(result))


async def _run(server_executable: str) -> dict[str, Any]:
    expected_version = importlib.metadata.version("ai-workflow-assurance-mcp")
    env = os.environ.copy()
    # Force the child server to use the installed wheel instead of a source override.
    env.pop("PYTHONPATH", None)
    params = StdioServerParameters(command=server_executable, args=[], env=env)

    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            initialized = await session.initialize()
            server_info = getattr(initialized, "serverInfo", None) or getattr(
                initialized, "server_info", None
            )
            if server_info is None or server_info.version != expected_version:
                raise AssertionError(
                    f"MCP initialize version mismatch: expected {expected_version!r}, "
                    f"got {getattr(server_info, 'version', None)!r}"
                )

            listed = await session.list_tools()
            tool_names = {tool.name for tool in listed.tools}
            if tool_names != EXPECTED_TOOLS:
                raise AssertionError(
                    f"Unexpected MCP tool set: missing={sorted(EXPECTED_TOOLS - tool_names)}, "
                    f"extra={sorted(tool_names - EXPECTED_TOOLS)}"
                )

            spec_json = json.dumps(SPEC)
            cases_json = json.dumps(CASES)
            checks: dict[str, Any] = {}

            validated = await session.call_tool(
                "validate_workflow_spec", {"workflow_spec_json": spec_json}
            )
            if _is_error(validated):
                raise AssertionError(_content_text(validated))
            checks["validate_workflow_spec"] = _payload(validated).get("valid") is True
            if not checks["validate_workflow_spec"]:
                raise AssertionError("Installed MCP wheel rejected the valid smoke spec.")

            evaluated = await session.call_tool(
                "run_eval_suite",
                {"workflow_spec_json": spec_json, "cases_json": cases_json},
            )
            if _is_error(evaluated):
                raise AssertionError(_content_text(evaluated))
            evaluation = _payload(evaluated)
            checks["run_eval_suite"] = evaluation.get("case_results_omitted") is True
            if not checks["run_eval_suite"]:
                raise AssertionError("Installed MCP wheel returned an unexpected eval payload.")

            compared = await session.call_tool(
                "compare_eval_runs",
                {
                    "workflow_spec_json": spec_json,
                    "baseline_cases_json": cases_json,
                    "candidate_cases_json": cases_json,
                },
            )
            if _is_error(compared):
                raise AssertionError(_content_text(compared))
            comparison = _payload(compared).get("comparison", {})
            checks["compare_eval_runs"] = comparison.get("case_details_omitted") is True
            if not checks["compare_eval_runs"]:
                raise AssertionError("Installed MCP wheel returned unexpected comparison details.")

            explained = await session.call_tool(
                "explain_failures",
                {
                    "workflow_spec_json": spec_json,
                    "cases_json": cases_json,
                    "max_items": 5,
                },
            )
            if _is_error(explained):
                raise AssertionError(_content_text(explained))
            explanation = _payload(explained)
            checks["explain_failures"] = explanation.get("failures_returned", 0) <= 5
            if not checks["explain_failures"]:
                raise AssertionError("Installed MCP wheel exceeded the explanation limit.")

            released = await session.call_tool(
                "generate_release_report",
                {"workflow_spec_json": spec_json, "cases_json": cases_json},
            )
            if _is_error(released):
                raise AssertionError(_content_text(released))
            release = _payload(released)
            checks["generate_release_report"] = release.get("decision") == "GO"
            if not checks["generate_release_report"]:
                raise AssertionError(f"Smoke release decision was not GO: {release.get('decision')}")

            evidence_names = (
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
            evidence_manifest = {
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
                    "before": {"order_id": "#synthetic", "status": "delivered"},
                    "after": {"order_id": "#synthetic", "status": "exchange requested"},
                    "full_database_before_sha256": "1" * 64,
                    "full_database_after_sha256": "2" * 64,
                    "other_database_entities_unchanged": True,
                    "write_count_in_trace": 1,
                    "tool_return_value_used_for_decision": False,
                    "tamper_probe": {"mutated_field": "status", "detected": True},
                },
                "checks": {name: True for name in evidence_names},
                "summary": {
                    "passed_checks": len(evidence_names),
                    "total_checks": len(evidence_names),
                },
                "data_minimization": {"raw_order_snapshots_included": False},
            }
            inspected = await session.call_tool(
                "inspect_tau2_evidence_manifest",
                {"manifest_json": json.dumps(evidence_manifest)},
            )
            if _is_error(inspected):
                raise AssertionError(_content_text(inspected))
            inspected_payload = _payload(inspected)
            checks["inspect_tau2_evidence_manifest"] = (
                inspected_payload.get("release_eligible") is False
                and inspected_payload.get("source_authenticity") == "not_verified"
            )
            if not checks["inspect_tau2_evidence_manifest"]:
                raise AssertionError("Evidence tool did not preserve the untrusted-source boundary.")

            # Invalid input should be rejected at validation, without making a network call.
            invalid_github = await session.call_tool(
                "inspect_github_actions_run",
                {
                    "repository": "owner/repo",
                    "run_id": True,
                    "expected_head_sha": "a" * 40,
                },
            )
            checks["inspect_github_actions_run_rejects_invalid_input"] = _is_error(
                invalid_github
            )
            if not checks["inspect_github_actions_run_rejects_invalid_input"]:
                raise AssertionError("GitHub evidence tool accepted an invalid run ID.")

            preflight_action = {
                "order_id": "ORD-1001",
                "old_item_ids": ["ITEM-11"],
                "new_item_ids": ["ITEM-12"],
                "payment_method_id": "PAY-1",
            }
            preflight_evidence = {
                "identity_verified": True,
                "verified_user_id": "USER-7",
                "order_owner_id": "USER-7",
                "order_id": "ORD-1001",
                "order_status": "delivered",
                "confirmation": {
                    "confirmed": True,
                    "order_id": "ORD-1001",
                    "old_item_ids": ["ITEM-11"],
                    "new_item_ids": ["ITEM-12"],
                    "payment_method_id": "PAY-1",
                    "confirmation_id": "CONF-1",
                },
                "customer_facing_confirmation": {
                    "order_id": "ORD-1001",
                    "old_item_ids": ["ITEM-11"],
                    "new_item_ids": ["ITEM-12"],
                    "payment_method_id": "PAY-1",
                    "payment_method_disclosed": True,
                },
                "confirmation_event_sequence": 3,
                "proposed_write_sequence": 4,
            }
            preflight = await session.call_tool(
                "preflight_sensitive_write",
                {
                    "action_json": json.dumps(preflight_action),
                    "evidence_json": json.dumps(preflight_evidence),
                },
            )
            if _is_error(preflight):
                raise AssertionError(_content_text(preflight))
            checks["preflight_sensitive_write"] = (
                _payload(preflight).get("decision") == "GO"
            )
            if not checks["preflight_sensitive_write"]:
                raise AssertionError("Valid synthetic preflight did not return GO.")

            return {
                "passed": all(checks.values()),
                "package_version": expected_version,
                "server_version": server_info.version,
                "listed_tool_count": len(tool_names),
                "checks": checks,
                "scope": "installed_wheel_local_synthetic_mcp_stdio_smoke_not_production_proof",
                "model_calls": 0,
                "external_api_calls": 0,
            }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--server",
        type=Path,
        required=True,
        help="Absolute path to the installed ai-workflow-assurance-mcp executable.",
    )
    args = parser.parse_args()
    server = args.server.resolve()
    if not server.is_file():
        parser.error(f"MCP server executable does not exist: {server}")
    report = asyncio.run(_run(str(server)))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
