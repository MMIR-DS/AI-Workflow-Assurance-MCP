"""Run a small, deterministic mutation harness against AWA's release gate.

This measures seeded input-fault detection for a narrow synthetic workflow. It is
not a source-code mutation score, a production reliability estimate, or a safety
certification. No model APIs or external services are called.
"""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from ai_workflow_assurance_mcp.core import create_release_report, evaluate_suite

SPEC: dict[str, Any] = {
    "id": "mutation-harness-demo",
    "name": "Synthetic payment decision workflow",
    "version": "1.0.0",
    "criteria": [
        {"id": "decision_matches", "operator": "equals", "actual_path": "decision",
         "expected_path": "decision", "severity": "critical"},
        {"id": "review_flag_matches", "operator": "equals",
         "actual_path": "requires_human_review", "expected_path": "requires_human_review",
         "severity": "critical"},
        {"id": "amount_matches", "operator": "approx", "actual_path": "amount",
         "expected_path": "amount", "tolerance": 0.01, "severity": "critical"},
    ],
    "thresholds": {"min_pass_rate": 1.0, "max_critical_failures": 0},
}

CONTROL_CASE = {
    "case_id": "valid-control",
    "expected": {"decision": "review", "requires_human_review": True, "amount": 125.0},
    "actual": {"decision": "review", "requires_human_review": True, "amount": 125.0},
}
MUTATIONS = {
    "wrong_decision": lambda actual: actual.update(decision="reject"),
    "missing_review_escalation": lambda actual: actual.update(requires_human_review=False),
    "amount_mismatch": lambda actual: actual.update(amount=999.0),
    "missing_required_amount": lambda actual: actual.pop("amount"),
    "boolean_integer_confusion": lambda actual: actual.update(amount=True),
}


def run_harness() -> dict[str, Any]:
    # CONTROL_CASE is the explicit reviewed baseline; do not silently override it.
    control = deepcopy(CONTROL_CASE)
    cases = [control]
    for name, mutate in MUTATIONS.items():
        case = deepcopy(control)
        case["case_id"] = name
        mutate(case["actual"])
        cases.append(case)

    detected: list[str] = []
    missed: list[str] = []
    for case in cases[1:]:
        report = evaluate_suite(SPEC, [case])
        release = create_release_report(SPEC, report)
        (detected if release["decision"] == "NO_GO" else missed).append(case["case_id"])

    control_release = create_release_report(SPEC, evaluate_suite(SPEC, [control]))
    repeated_release = create_release_report(SPEC, evaluate_suite(SPEC, [control]))
    reproducible = (
        control_release["decision"] == repeated_release["decision"]
        and control_release["checks"] == repeated_release["checks"]
        and control_release["blocking_checks"] == repeated_release["blocking_checks"]
    )
    total = len(MUTATIONS)
    return {
        "schema_version": "1.0",
        "scope": "synthetic input-fault detection; not source-code mutation testing",
        "model_calls": 0,
        "control": {
            "decision": control_release["decision"],
            "expected_decision": "GO",
            "passed": control_release["decision"] == "GO",
        },
        "seeded_faults": {
            "total": total,
            "detected": len(detected),
            "missed": len(missed),
            "detection_rate": len(detected) / total if total else 1.0,
            "detected_ids": detected,
            "missed_ids": missed,
        },
        "false_rejection_count": int(control_release["decision"] != "GO"),
        "reproducibility": {
            "stable_decision_and_checks": reproducible,
            "passed": reproducible,
        },
        "overall_passed": (
            control_release["decision"] == "GO"
            and len(detected) == total
            and not missed
            and reproducible
        ),
        "limitations": [
            "Only five deliberately seeded faults in a synthetic workflow are tested.",
            "This result is not a statistical reliability estimate or a production safety claim.",
            "The harness tests evaluated inputs, not arbitrary agent execution or source-code mutations.",
        ],
    }


if __name__ == "__main__":
    print(json.dumps(run_harness(), indent=2, sort_keys=True))
