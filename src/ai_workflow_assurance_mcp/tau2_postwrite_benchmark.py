"""Benchmark-artifact post-write audit for Tau2 retail simulations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ai_workflow_assurance_mcp.tau2_postwrite_catalog import _field
from ai_workflow_assurance_mcp.tau2_postwrite_trace import (
    _trace_messages,
    _trace_messages_are_well_formed,
    _trace_not_evaluable,
    _trace_tool_calls,
    audit_tau2_trace_postwrite,
)


def audit_tau2_benchmark_result_postwrite(
    benchmark_result: Any,
    *,
    write_tool_name: str = "modify_pending_order_items",
    simulation_index: int | None = None,
) -> dict[str, Any]:
    """Audit write results across a complete Tau2 benchmark JSON artifact.

    Expected artifact shape: a mapping with a simulations list where every
    simulation contains a messages trace. Each matching target write/order is
    audited independently. Tau2 reward metadata is deliberately ignored.
    """
    simulations = _field(benchmark_result, "simulations")
    if not isinstance(simulations, (list, tuple)):
        return {
            "decision": "NOT_EVALUABLE",
            "checked": {"benchmark_simulations_are_well_formed": "NOT_EVALUABLE"},
            "blocking_checks": ["benchmark_simulations_are_well_formed"],
            "simulation_results": [],
            "order_audits": [],
            "evidence_summary": {
                "simulation_count": 0,
                "selected_simulation_indices": [],
                "order_audit_count": 0,
                "simulations_without_matching_write": 0,
                "fail_count": 0,
                "not_evaluable_count": 1,
            },
            "scope": "tau2_benchmark_artifact_postwrite_audit_not_production_data_integrity_proof",
            "not_evaluable": [
                {
                    "check": "benchmark_simulations_are_well_formed",
                    "detail": "Expected a Tau2 benchmark artifact with a simulations list.",
                }
            ],
        }
    if not isinstance(write_tool_name, str) or not write_tool_name:
        return {
            "decision": "NOT_EVALUABLE",
            "checked": {"write_tool_name_is_valid": "NOT_EVALUABLE"},
            "blocking_checks": ["write_tool_name_is_valid"],
            "simulation_results": [],
            "order_audits": [],
            "evidence_summary": {
                "simulation_count": len(simulations),
                "selected_simulation_indices": [],
                "order_audit_count": 0,
                "simulations_without_matching_write": 0,
                "fail_count": 0,
                "not_evaluable_count": 1,
            },
            "scope": "tau2_benchmark_artifact_postwrite_audit_not_production_data_integrity_proof",
            "not_evaluable": [
                {
                    "check": "write_tool_name_is_valid",
                    "detail": "A non-empty write_tool_name is required.",
                }
            ],
        }

    if simulation_index is None:
        selected = list(enumerate(simulations))
    elif (
        isinstance(simulation_index, int)
        and not isinstance(simulation_index, bool)
        and 0 <= simulation_index < len(simulations)
    ):
        selected = [(simulation_index, simulations[simulation_index])]
    else:
        return {
            "decision": "NOT_EVALUABLE",
            "checked": {"simulation_index_is_valid": "NOT_EVALUABLE"},
            "blocking_checks": ["simulation_index_is_valid"],
            "simulation_results": [],
            "order_audits": [],
            "evidence_summary": {
                "simulation_count": len(simulations),
                "selected_simulation_indices": [],
                "order_audit_count": 0,
                "simulations_without_matching_write": 0,
                "fail_count": 0,
                "not_evaluable_count": 1,
            },
            "scope": "tau2_benchmark_artifact_postwrite_audit_not_production_data_integrity_proof",
            "not_evaluable": [
                {
                    "check": "simulation_index_is_valid",
                    "detail": (
                        "simulation_index must be a valid zero-based index into simulations."
                    ),
                }
            ],
        }

    if not selected:
        return {
            "decision": "NOT_EVALUABLE",
            "checked": {"at_least_one_simulation_selected": "NOT_EVALUABLE"},
            "blocking_checks": ["at_least_one_simulation_selected"],
            "simulation_results": [],
            "order_audits": [],
            "evidence_summary": {
                "simulation_count": 0,
                "selected_simulation_indices": [],
                "order_audit_count": 0,
                "simulations_without_matching_write": 0,
                "fail_count": 0,
                "not_evaluable_count": 1,
                "benchmark_reward_used_as_integrity_oracle": False,
            },
            "scope": "tau2_benchmark_artifact_postwrite_audit_not_production_data_integrity_proof",
            "not_evaluable": [
                {
                    "check": "at_least_one_simulation_selected",
                    "detail": "The benchmark artifact contains no simulations to audit.",
                }
            ],
        }

    simulation_results: list[dict[str, Any]] = []
    order_audits: list[dict[str, Any]] = []
    simulation_decisions: list[str] = []
    simulations_without_write = 0
    all_simulations_well_formed = True

    for index, simulation in selected:
        task_id = _field(simulation, "task_id")
        messages = _trace_messages(_field(simulation, "messages"))
        if not _trace_messages_are_well_formed(messages):
            all_simulations_well_formed = False
            audit = _trace_not_evaluable(
                None,
                "simulation_messages_are_well_formed",
                "This simulation's messages list or an individual message/tool-call "
                "record is missing or malformed.",
            )
            entry = {
                "simulation_index": index,
                "task_id": task_id,
                "decision": "NOT_EVALUABLE",
                "order_audits": [],
                "not_evaluable": audit["not_evaluable"],
            }
            simulation_results.append(entry)
            simulation_decisions.append("NOT_EVALUABLE")
            continue

        target_order_ids: list[str] = []
        for message in messages:
            for call in _trace_tool_calls(message):
                arguments = _field(call, "arguments", {})
                if (
                    _field(call, "name") == write_tool_name
                    and isinstance(arguments, Mapping)
                    and isinstance(arguments.get("order_id"), str)
                    and arguments["order_id"].strip()
                    and arguments["order_id"] not in target_order_ids
                ):
                    target_order_ids.append(arguments["order_id"])

        if not target_order_ids:
            simulation_results.append(
                {
                    "simulation_index": index,
                    "task_id": task_id,
                    "decision": "NOT_APPLICABLE",
                    "order_audits": [],
                    "not_applicable": [
                        {
                            "check": "matching_write_attempt_available",
                            "detail": (
                                f"No {write_tool_name!r} call with a valid order_id "
                                "was found in this simulation; no write-specific audit applies."
                            ),
                        }
                    ],
                }
            )
            simulation_decisions.append("NOT_APPLICABLE")
            simulations_without_write += 1
            continue

        this_simulation_audits: list[dict[str, Any]] = []
        for target_order_id in target_order_ids:
            audit = audit_tau2_trace_postwrite(
                messages,
                target_order_id,
                write_tool_name=write_tool_name,
            )
            audit_entry = {
                "simulation_index": index,
                "task_id": task_id,
                "order_id": target_order_id,
                **audit,
            }
            this_simulation_audits.append(audit_entry)
            order_audits.append(audit_entry)

        this_decisions = [audit["decision"] for audit in this_simulation_audits]
        if any(decision == "FAIL" for decision in this_decisions):
            simulation_decision = "FAIL"
        elif any(decision != "PASS" for decision in this_decisions):
            simulation_decision = "NOT_EVALUABLE"
        else:
            simulation_decision = "PASS"
        simulation_results.append(
            {
                "simulation_index": index,
                "task_id": task_id,
                "decision": simulation_decision,
                "order_audits": this_simulation_audits,
            }
        )
        simulation_decisions.append(simulation_decision)

    applicable_decisions = [
        item for item in simulation_decisions if item != "NOT_APPLICABLE"
    ]
    if any(item == "FAIL" for item in applicable_decisions):
        decision = "FAIL"
    elif not applicable_decisions or any(item != "PASS" for item in applicable_decisions):
        # An all-read-only selection has no applicable write audit and cannot PASS.
        decision = "NOT_EVALUABLE"
    else:
        decision = "PASS"

    fail_count = sum(audit["decision"] == "FAIL" for audit in order_audits)
    not_evaluable_order_count = sum(
        audit["decision"] == "NOT_EVALUABLE" for audit in order_audits
    )
    simulations_without_usable_trace = sum(
        item["decision"] == "NOT_EVALUABLE" and not item["order_audits"]
        for item in simulation_results
    )
    not_evaluable_count = (
        not_evaluable_order_count + simulations_without_usable_trace
    )
    not_evaluable_simulation_count = sum(
        item["decision"] == "NOT_EVALUABLE" for item in simulation_results
    )
    blocking_checks: list[str] = []
    if fail_count:
        blocking_checks.append("one_or_more_order_audits_failed")
    if not_evaluable_count:
        blocking_checks.append("one_or_more_simulations_not_evaluable")
    if simulations_without_usable_trace:
        blocking_checks.append("one_or_more_simulations_have_no_usable_write_trace")
    if not applicable_decisions:
        blocking_checks.append("no_applicable_write_simulations")

    return {
        "decision": decision,
        "checked": {
            "benchmark_simulations_are_well_formed": (
                "PASS" if all_simulations_well_formed else "NOT_EVALUABLE"
            ),
            "all_target_order_audits_passed": (
                "PASS" if decision == "PASS" else decision
            ),
            "at_least_one_applicable_write_simulation": (
                "PASS" if applicable_decisions else "NOT_EVALUABLE"
            ),
        },
        "blocking_checks": blocking_checks,
        "simulation_results": simulation_results,
        "order_audits": order_audits,
        "evidence_summary": {
            "simulation_count": len(simulation_results),
            "selected_simulation_indices": [index for index, _ in selected],
            "order_audit_count": len(order_audits),
            "simulations_without_matching_write": simulations_without_write,
            "not_evaluable_simulation_count": not_evaluable_simulation_count,
            "not_applicable_simulation_count": sum(
                item["decision"] == "NOT_APPLICABLE" for item in simulation_results
            ),
            "applicable_simulation_count": len(applicable_decisions),
            "simulations_without_usable_trace": simulations_without_usable_trace,
            "fail_count": fail_count,
            "not_evaluable_count": not_evaluable_count,
            "benchmark_reward_used_as_integrity_oracle": False,
        },
        "scope": "tau2_benchmark_artifact_postwrite_audit_not_production_data_integrity_proof",
    }
