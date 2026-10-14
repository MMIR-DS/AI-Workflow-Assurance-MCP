"""Deterministic evaluation of cases and criteria against a workflow specification."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from ai_workflow_assurance_mcp.core_support import (
    MAX_EVALUATION_CHECKS,
    SCHEMA_VERSION,
    AssuranceInputError,
    _bounded_report_value,
    _is_number,
    _lookup_path,
    _precise_average,
    _precise_sum,
    _typed_equal,
    stable_json_digest,
)
from ai_workflow_assurance_mcp.core_validation import (
    validate_cases,
    validate_spec,
)


def _expected_value(criterion: dict[str, Any], expected_root: Any) -> tuple[bool, Any]:
    if "expected_path" in criterion:
        return _lookup_path(expected_root, criterion["expected_path"])
    if "expected_value" in criterion:
        return True, criterion["expected_value"]
    return False, None


def _evaluation_status(check: dict[str, Any]) -> str:
    status = check.get("status")
    if status in {"PASS", "FAIL", "NOT_EVALUABLE"}:
        return status
    # Backward compatibility for reports created before explicit status existed.
    return "PASS" if check.get("passed") is True else "FAIL"


def _evaluate_criterion(
    criterion: dict[str, Any], expected_root: Any, actual_root: Any, not_evaluable: bool = False
) -> dict[str, Any]:
    operator = criterion["operator"]
    actual_exists, actual_value = _lookup_path(actual_root, criterion["actual_path"])
    expected_exists, expected_value = _expected_value(criterion, expected_root)
    passed = False
    message = ""

    if operator == "exists":
        # Existence means that path lookup found a value; null/empty values are still present.
        passed = actual_exists
        message = "Path exists." if passed else f"Required path '{criterion['actual_path']}' is missing."
    elif operator == "non_empty":
        if isinstance(actual_value, str):
            has_content = bool(actual_value.strip())
        elif isinstance(actual_value, (list, dict)):
            has_content = bool(actual_value)
        else:
            has_content = actual_value is not None
        passed = actual_exists and has_content
        message = (
            "Value is present and non-empty."
            if passed
            else f"Required path '{criterion['actual_path']}' is missing, null, or empty."
        )
    elif operator == "is_true":
        passed = actual_exists and actual_value is True
        message = "Value is true." if passed else f"Expected '{criterion['actual_path']}' to be true."
    elif operator == "is_false":
        passed = actual_exists and actual_value is False
        message = "Value is false." if passed else f"Expected '{criterion['actual_path']}' to be false."
    elif not actual_exists:
        message = f"Actual path '{criterion['actual_path']}' is missing."
    elif not expected_exists:
        message = f"Expected value path '{criterion.get('expected_path')}' is missing."
    elif operator == "equals":
        passed = _typed_equal(actual_value, expected_value)
        message = "Values match." if passed else "Values do not match."
    elif operator == "approx":
        passed = _is_number(actual_value) and _is_number(expected_value) and abs(float(actual_value) - float(expected_value)) <= float(criterion["tolerance"])
        message = "Values are within tolerance." if passed else f"Values differ by more than tolerance ({criterion['tolerance']})."
    elif operator == "contains":
        if isinstance(actual_value, str):
            passed = isinstance(expected_value, str) and expected_value in actual_value
        elif isinstance(actual_value, list):
            passed = any(_typed_equal(expected_value, item) for item in actual_value)
        elif isinstance(actual_value, dict):
            passed = isinstance(expected_value, str) and expected_value in actual_value
        message = "Expected value is contained." if passed else "Expected value is not contained."
    elif operator == "in_set":
        passed = isinstance(expected_value, list) and any(_typed_equal(actual_value, choice) for choice in expected_value)
        message = "Value is in the allowed set." if passed else "Value is outside the allowed set."

    if not_evaluable:
        passed = False
        message = "Criterion is not evaluable from the available evidence."

    item: dict[str, Any] = {
        "criterion_id": criterion["id"],
        "operator": operator,
        "severity": criterion.get("severity", "high"),
        "passed": bool(passed),
        "status": "NOT_EVALUABLE" if not_evaluable else ("PASS" if passed else "FAIL"),
        "message": message,
        "actual_path": criterion["actual_path"],
        "actual_value": _bounded_report_value(actual_value) if actual_exists else None,
    }
    if expected_exists and operator not in {"exists", "is_true", "is_false"}:
        item["expected_value"] = _bounded_report_value(expected_value)
    if operator == "approx":
        item["tolerance"] = criterion["tolerance"]
    return item


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def evaluate_suite(spec: dict[str, Any], cases: list[dict[str, Any]]) -> dict[str, Any]:
    spec_errors = validate_spec(spec)
    if spec_errors:
        raise AssuranceInputError("Invalid workflow specification: " + " ".join(spec_errors))
    case_errors = validate_cases(cases)
    if case_errors:
        raise AssuranceInputError("Invalid cases: " + " ".join(case_errors))
    if len(spec["criteria"]) * len(cases) > MAX_EVALUATION_CHECKS:
        raise AssuranceInputError(f"This run would exceed {MAX_EVALUATION_CHECKS:,} individual checks; reduce cases or criteria.")
    allowed_criterion_ids = {rule["id"] for rule in spec["criteria"]}
    for index, case in enumerate(cases):
        unknown_ids = set(case.get("unobserved_checks", [])) - allowed_criterion_ids
        if unknown_ids:
            raise AssuranceInputError(
                f"cases[{index}].unobserved_checks contains unknown criterion id(s): "
                + ", ".join(sorted(unknown_ids))
            )

    case_results: list[dict[str, Any]] = []
    all_checks: list[dict[str, Any]] = []
    review_observations: list[bool] = []
    costs: list[float] = []
    latencies: list[float] = []

    for case in cases:
        unobserved = set(case.get("unobserved_checks", []))
        checks = [
            _evaluate_criterion(rule, case["expected"], case["actual"], rule["id"] in unobserved)
            for rule in spec["criteria"]
        ]
        statuses = [_evaluation_status(check) for check in checks]
        case_status = (
            "PASS" if all(status == "PASS" for status in statuses)
            else "FAIL" if any(status == "FAIL" for status in statuses)
            else "NOT_EVALUABLE"
        )
        passed = case_status == "PASS"
        # Review-rate metrics must come from an explicit observation, not an
        # inference from the workflow's predicted output. The legacy name is kept
        # as an alias for backwards compatibility.
        review = case.get("human_review_observed", case.get("human_review_required"))
        if isinstance(review, bool):
            review_observations.append(review)
        if "cost_usd" in case:
            costs.append(float(case["cost_usd"]))
        if "latency_ms" in case:
            latencies.append(float(case["latency_ms"]))
        result = {
            "case_id": case["case_id"],
            "expected_sha256": stable_json_digest(case["expected"]),
            "passed": passed,
            "status": case_status,
            "checks_passed": sum(1 for status in statuses if status == "PASS"),
            "checks_failed": sum(1 for status in statuses if status == "FAIL"),
            "checks_not_evaluable": sum(1 for status in statuses if status == "NOT_EVALUABLE"),
            "checks_total": len(checks),
            "checks": checks,
            "human_review_observed": review,
            "cost_usd": case.get("cost_usd"),
            "latency_ms": case.get("latency_ms"),
        }
        case_results.append(result)
        all_checks.extend({**check, "case_id": case["case_id"]} for check in checks)

    total_cases = len(case_results)
    total_checks = len(all_checks)
    failed_critical = sum(1 for item in all_checks if _evaluation_status(item) == "FAIL" and item["severity"] == "critical")
    failed_high = sum(1 for item in all_checks if _evaluation_status(item) == "FAIL" and item["severity"] == "high")
    review_count = sum(review_observations)
    summary = {
        "total_cases": total_cases,
        "passed_cases": sum(1 for result in case_results if result["status"] == "PASS"),
        "failed_cases": sum(1 for result in case_results if result["status"] == "FAIL"),
        "not_evaluable_cases": sum(1 for result in case_results if result["status"] == "NOT_EVALUABLE"),
        "pass_rate": sum(1 for result in case_results if result["status"] == "PASS") / total_cases,
        "total_checks": total_checks,
        "passed_checks": sum(1 for item in all_checks if _evaluation_status(item) == "PASS"),
        "failed_checks": sum(1 for item in all_checks if _evaluation_status(item) == "FAIL"),
        "not_evaluable_checks": sum(1 for item in all_checks if _evaluation_status(item) == "NOT_EVALUABLE"),
        "critical_failures": failed_critical,
        "high_failures": failed_high,
        "reviewed_cases": review_count,
        "review_observation_coverage": len(review_observations) / total_cases,
        "review_rate": review_count / len(review_observations) if review_observations else None,
        "cost_observation_coverage": len(costs) / total_cases,
        "total_cost_usd_observed": _precise_sum(costs) if costs else None,
        "avg_cost_usd_per_observed_case": _precise_average(costs),
        "max_cost_usd_observed": max(costs) if costs else None,
        "latency_observation_coverage": len(latencies) / total_cases,
        "avg_latency_ms_observed": sum(latencies) / len(latencies) if latencies else None,
        "max_latency_ms_observed": max(latencies) if latencies else None,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": str(uuid.uuid4()),
        "executed_at": _utc_now(),
        "workflow": {"id": spec["id"], "name": spec["name"], "version": spec["version"]},
        "audit": {
            "spec_sha256": stable_json_digest(spec),
            "criteria_sha256": stable_json_digest(spec["criteria"]),
            "thresholds_sha256": stable_json_digest(spec["thresholds"]),
            "cases_sha256": stable_json_digest(cases),
            "digest_note": "SHA-256 fingerprints for change detection; not a digital signature or proof of source authenticity.",
        },
        "summary": summary,
        "case_results": case_results,
        "assurance_scope": "Evaluates supplied expected and actual outputs only. It does not execute, inspect, or independently verify the external AI workflow.",
    }
