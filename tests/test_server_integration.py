# ruff: noqa: I001
# Delayed MCP imports are required after pytest.importorskip.
"""End-to-end MCP stdio tests; skipped when the optional SDK is unavailable."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp", reason="MCP SDK is installed by the project's dev extra and CI")

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

from ai_workflow_assurance_mcp import __version__  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
SPEC = {
    "id": "protocol-test",
    "name": "Protocol integration test",
    "version": "1",
    "criteria": [
        {"id": "decision_matches", "operator": "equals", "actual_path": "decision", "expected_path": "decision", "severity": "critical"}
    ],
    "thresholds": {"min_pass_rate": 1.0, "max_critical_failures": 0},
}
CASES = [
    {
        "case_id": "case-1",
        "expected": {"decision": "approve"},
        "actual": {"decision": "approve"},
        "human_review_observed": False,
        "cost_usd": 0.01,
        "latency_ms": 100,
    }
]


def _is_error(result: object) -> bool:
    return bool(getattr(result, "is_error", getattr(result, "isError", False)))


def _content_text(result: object) -> str:
    parts = getattr(result, "content", []) or []
    return "\n".join(str(getattr(part, "text", "")) for part in parts)


def test_stdio_handshake_lists_tools_and_invokes_all_tools() -> None:
    async def run() -> None:
        env = os.environ.copy()
        source_path = str(ROOT / "src")
        env["PYTHONPATH"] = source_path + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "ai_workflow_assurance_mcp.server"],
            env=env,
        )
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                initialized = await session.initialize()
                server_info = getattr(initialized, "serverInfo", None) or getattr(initialized, "server_info", None)
                assert server_info is not None
                assert server_info.version == __version__
                listed = await session.list_tools()
                names = {tool.name for tool in listed.tools}
                assert names == {
                    "validate_workflow_spec",
                    "run_eval_suite",
                    "compare_eval_runs",
                    "explain_failures",
                    "generate_release_report",
                    "inspect_tau2_evidence_manifest",
                    "inspect_github_actions_run",
                    "preflight_delivered_item_exchange",
                }

                preflight_tool = next(
                    tool for tool in listed.tools if tool.name == "preflight_delivered_item_exchange"
                )
                preflight_description = (preflight_tool.description or "").lower()
                assert "exchange-specific" in preflight_description
                assert "not a generic policy" in preflight_description

                spec_json = json.dumps(SPEC)
                cases_json = json.dumps(CASES)
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
                evidence_checks = {name: True for name in evidence_names}
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
                    "checks": evidence_checks,
                    "summary": {"passed_checks": len(evidence_checks), "total_checks": len(evidence_checks)},
                    "data_minimization": {"raw_order_snapshots_included": False},
                }
                evidence_json = json.dumps(evidence_manifest)
                results = [
                    await session.call_tool("validate_workflow_spec", {"workflow_spec_json": spec_json}),
                    await session.call_tool("run_eval_suite", {"workflow_spec_json": spec_json, "cases_json": cases_json}),
                    await session.call_tool(
                        "compare_eval_runs",
                        {"workflow_spec_json": spec_json, "baseline_cases_json": cases_json, "candidate_cases_json": cases_json},
                    ),
                    await session.call_tool(
                        "explain_failures",
                        {"workflow_spec_json": spec_json, "cases_json": cases_json, "max_items": 10},
                    ),
                    await session.call_tool("generate_release_report", {"workflow_spec_json": spec_json, "cases_json": cases_json}),
                    await session.call_tool("inspect_tau2_evidence_manifest", {"manifest_json": evidence_json}),
                ]
                assert all(not _is_error(result) for result in results), [_content_text(result) for result in results]

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
                    "preflight_delivered_item_exchange",
                    {
                        "action_json": json.dumps(preflight_action),
                        "evidence_json": json.dumps(preflight_evidence),
                    },
                )
                assert not _is_error(preflight), _content_text(preflight)
                preflight_payload = json.loads(_content_text(preflight))
                assert preflight_payload["decision"] == "GO"
                assert preflight_payload["evidence_trust_boundary"] == "caller_supplied_not_authenticated"
                invalid_github_evidence = await session.call_tool(
                    "inspect_github_actions_run",
                    {"repository": "owner/repo", "run_id": True, "expected_head_sha": "a" * 40},
                )
                assert _is_error(invalid_github_evidence)
                evidence_payload = json.loads(_content_text(results[5]))
                assert evidence_payload["release_eligible"] is False
                assert evidence_payload["source_authenticity"] == "not_verified"
                release_payload = json.loads(_content_text(results[4]))
                assert "failed_case_count" in release_payload
                assert len(release_payload["failed_case_ids_preview"]) <= 20
                default_comparison = json.loads(_content_text(results[2]))["comparison"]
                assert default_comparison["case_details_omitted"] is True
                assert "case_changes" not in default_comparison
                # Large case-level responses are opt-in so normal LLM context stays bounded.
                default_eval = json.loads(_content_text(results[1]))
                assert default_eval["case_results_omitted"] is True
                detailed_eval = await session.call_tool(
                    "run_eval_suite",
                    {"workflow_spec_json": spec_json, "cases_json": cases_json, "summary_only": False},
                )
                assert not _is_error(detailed_eval)
                assert "case_results" in json.loads(_content_text(detailed_eval))
                detailed_compare = await session.call_tool(
                    "compare_eval_runs",
                    {"workflow_spec_json": spec_json, "baseline_cases_json": cases_json, "candidate_cases_json": cases_json, "include_case_details": True},
                )
                assert not _is_error(detailed_compare)
                assert "case_changes" in json.loads(_content_text(detailed_compare))["comparison"]

                invalid = await session.call_tool(
                    "run_eval_suite",
                    {"workflow_spec_json": spec_json, "cases_json": "not valid JSON"},
                )
                assert _is_error(invalid)
                assert "cases_json" in _content_text(invalid)

                invalid_spec = await session.call_tool(
                    "validate_workflow_spec", {"workflow_spec_json": "not valid JSON"}
                )
                assert not _is_error(invalid_spec)
                assert "valid" in _content_text(invalid_spec).lower()

    asyncio.run(run())
