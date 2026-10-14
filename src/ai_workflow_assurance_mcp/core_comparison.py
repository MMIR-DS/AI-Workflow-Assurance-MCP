"""Report integrity validation, baseline comparison, and failure explanations."""

from __future__ import annotations

import math
import re
from typing import Any

from ai_workflow_assurance_mcp.core_evaluation import (
    _evaluation_status,
)
from ai_workflow_assurance_mcp.core_support import (
    MAX_CASES,
    MAX_EXPLANATION_ITEMS,
    MAX_JSON_DEPTH,
    SEVERITY_ORDER,
    AssuranceInputError,
    _bounded_errors,
    _exceeds_json_depth,
    _is_number,
    _precise_average,
    _precise_sum,
)


def _validate_report(report: Any, label: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(report, dict):
        return [f"{label} must be a JSON object."]
    if _exceeds_json_depth(report):
        return [f"{label} exceeds the maximum JSON nesting depth of {MAX_JSON_DEPTH}."]
    for key in ("run_id", "workflow", "summary", "case_results"):
        if key not in report:
            errors.append(f"{label}.{key} is required.")
    if not isinstance(report.get("run_id"), str) or not report.get("run_id"):
        errors.append(f"{label}.run_id must be a non-empty string.")
    workflow = report.get("workflow")
    if not isinstance(workflow, dict) or not isinstance(workflow.get("id"), str) or not workflow.get("id"):
        errors.append(f"{label}.workflow.id is required.")
    summary = report.get("summary")
    if not isinstance(summary, dict):
        errors.append(f"{label}.summary must be an object.")
    else:
        for key in ("pass_rate", "review_rate", "review_observation_coverage", "cost_observation_coverage", "latency_observation_coverage"):
            value = summary.get(key)
            if value is not None and (not _is_number(value) or (key.endswith("coverage") or key == "pass_rate" or key == "review_rate") and not 0 <= float(value) <= 1):
                errors.append(f"{label}.summary.{key} must be null or a valid finite numeric rate between 0 and 1.")
        for key in ("critical_failures", "high_failures", "total_cases", "passed_cases", "failed_cases", "not_evaluable_cases", "not_evaluable_checks"):
            value = summary.get(key)
            if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
                errors.append(f"{label}.summary.{key} must be null or a non-negative integer.")
        for key in ("avg_cost_usd_per_observed_case", "avg_latency_ms_observed", "total_cost_usd_observed", "max_cost_usd_observed", "max_latency_ms_observed"):
            value = summary.get(key)
            if value is not None and (not _is_number(value) or float(value) < 0):
                errors.append(f"{label}.summary.{key} must be null or a finite non-negative number.")
    audit = report.get("audit")
    if not isinstance(audit, dict):
        errors.append(f"{label}.audit must be an object produced by evaluate_suite.")
    else:
        for key in ("spec_sha256", "criteria_sha256", "thresholds_sha256", "cases_sha256"):
            value = audit.get(key)
            if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
                errors.append(f"{label}.audit.{key} must be a SHA-256 hex digest.")

    case_results = report.get("case_results")
    if not isinstance(case_results, list):
        errors.append(f"{label}.case_results must be a list.")
    elif not case_results:
        errors.append(f"{label}.case_results must not be empty.")
    elif len(case_results) > MAX_CASES:
        errors.append(f"{label}.case_results may contain at most {MAX_CASES} items.")
    else:
        seen_case_ids: set[str] = set()
        for index, result in enumerate(case_results):
            prefix = f"{label}.case_results[{index}]"
            if not isinstance(result, dict):
                errors.append(f"{prefix} must be an object.")
                continue
            case_id = result.get("case_id")
            if not isinstance(case_id, str) or not case_id or case_id in seen_case_ids:
                errors.append(f"{prefix}.case_id must be a unique non-empty string.")
            else:
                seen_case_ids.add(case_id)
            digest = result.get("expected_sha256")
            if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
                errors.append(f"{prefix}.expected_sha256 must be a SHA-256 hex digest.")
            if not isinstance(result.get("passed"), bool):
                errors.append(f"{prefix}.passed must be boolean.")
            checks = result.get("checks")
            if not isinstance(checks, list):
                errors.append(f"{prefix}.checks must be a list.")
            else:
                if not checks:
                    errors.append(f"{prefix}.checks must not be empty.")
                for check_index, check in enumerate(checks):
                    if not isinstance(check, dict) or not isinstance(check.get("passed"), bool):
                        errors.append(f"{prefix}.checks[{check_index}] must contain a boolean passed field.")
                        continue
                    if "status" in check:
                        if check.get("status") not in {"PASS", "FAIL", "NOT_EVALUABLE"}:
                            errors.append(f"{prefix}.checks[{check_index}].status is invalid.")
                        elif check["passed"] is not (check["status"] == "PASS"):
                            errors.append(f"{prefix}.checks[{check_index}].passed conflicts with status.")
                    severity = check.get("severity", "high")
                    if not isinstance(severity, str):
                        errors.append(f"{prefix}.checks[{check_index}].severity must be a string.")
                    elif severity not in SEVERITY_ORDER:
                        errors.append(f"{prefix}.checks[{check_index}].severity is invalid.")
            if isinstance(checks, list) and all(isinstance(item, dict) and isinstance(item.get("passed"), bool) for item in checks):
                check_statuses = [_evaluation_status(item) for item in checks]
                actual_passed_checks = sum(1 for status in check_statuses if status == "PASS")
                actual_failed_checks = sum(1 for status in check_statuses if status == "FAIL")
                actual_not_evaluable_checks = sum(1 for status in check_statuses if status == "NOT_EVALUABLE")
                if result.get("checks_passed") != actual_passed_checks or result.get("checks_total") != len(checks):
                    errors.append(f"{prefix}.checks_passed/checks_total do not match checks.")
                if "checks_failed" in result and result["checks_failed"] != actual_failed_checks:
                    errors.append(f"{prefix}.checks_failed does not match checks.")
                if "checks_not_evaluable" in result and result["checks_not_evaluable"] != actual_not_evaluable_checks:
                    errors.append(f"{prefix}.checks_not_evaluable does not match checks.")
                expected_case_status = (
                    "PASS" if all(status == "PASS" for status in check_statuses)
                    else "FAIL" if any(status == "FAIL" for status in check_statuses)
                    else "NOT_EVALUABLE"
                )
                expected_case_passed = expected_case_status == "PASS"
                if result.get("passed") != expected_case_passed:
                    errors.append(f"{prefix}.passed does not match its individual checks.")
                if "status" in result and result["status"] != expected_case_status:
                    errors.append(f"{prefix}.status does not match its individual checks.")
            if result.get("human_review_observed") is not None and not isinstance(result.get("human_review_observed"), bool):
                errors.append(f"{prefix}.human_review_observed must be boolean or null.")
            for measure in ("cost_usd", "latency_ms"):
                value = result.get(measure)
                if value is not None and (not _is_number(value) or float(value) < 0):
                    errors.append(f"{prefix}.{measure} must be null or a finite non-negative number.")

        # Recompute every summary statistic derivable from case_results. This
        # prevents a mismatched/forged summary from producing a release decision.
        if isinstance(summary, dict) and all(isinstance(item, dict) and isinstance(item.get("checks"), list) for item in case_results):
            valid_results = [item for item in case_results if isinstance(item, dict)]
            total_cases = len(valid_results)
            total_checks = sum(len(item["checks"]) for item in valid_results)
            check_items = [check for item in valid_results for check in item["checks"] if isinstance(check, dict)]
            statuses_present = any("status" in check for check in check_items)
            passed_cases = sum(1 for item in valid_results if item.get("status", "PASS" if item.get("passed") is True else "FAIL") == "PASS")
            failed_cases = sum(1 for item in valid_results if item.get("status", "PASS" if item.get("passed") is True else "FAIL") == "FAIL")
            not_evaluable_cases = sum(1 for item in valid_results if item.get("status") == "NOT_EVALUABLE")
            passed_checks = sum(1 for check in check_items if _evaluation_status(check) == "PASS")
            failed_checks = sum(1 for check in check_items if _evaluation_status(check) == "FAIL")
            not_evaluable_checks = sum(1 for check in check_items if _evaluation_status(check) == "NOT_EVALUABLE")
            critical_failures = sum(1 for check in check_items if _evaluation_status(check) == "FAIL" and check.get("severity", "high") == "critical")
            high_failures = sum(1 for check in check_items if _evaluation_status(check) == "FAIL" and check.get("severity", "high") == "high")
            reviews = [item.get("human_review_observed") for item in valid_results if isinstance(item.get("human_review_observed"), bool)]
            costs = [item["cost_usd"] for item in valid_results if _is_number(item.get("cost_usd")) and float(item["cost_usd"]) >= 0]
            latencies = [item["latency_ms"] for item in valid_results if _is_number(item.get("latency_ms")) and float(item["latency_ms"]) >= 0]
            expected_summary = {
                "total_cases": total_cases,
                "passed_cases": passed_cases,
                "failed_cases": failed_cases,
                "pass_rate": passed_cases / total_cases if total_cases else None,
                "total_checks": total_checks,
                "passed_checks": passed_checks,
                "failed_checks": failed_checks,
                "critical_failures": critical_failures,
                "high_failures": high_failures,
                "reviewed_cases": sum(reviews),
                "review_observation_coverage": len(reviews) / total_cases if total_cases else 0,
                "review_rate": sum(reviews) / len(reviews) if reviews else None,
                "cost_observation_coverage": len(costs) / total_cases if total_cases else 0,
                "total_cost_usd_observed": _precise_sum(costs) if costs else None,
                "avg_cost_usd_per_observed_case": _precise_average(costs),
                "max_cost_usd_observed": max(costs) if costs else None,
                "latency_observation_coverage": len(latencies) / total_cases if total_cases else 0,
                "avg_latency_ms_observed": sum(latencies) / len(latencies) if latencies else None,
                "max_latency_ms_observed": max(latencies) if latencies else None,
            }
            if statuses_present:
                expected_summary["not_evaluable_cases"] = not_evaluable_cases
                expected_summary["not_evaluable_checks"] = not_evaluable_checks
            for key, expected_value in expected_summary.items():
                actual_value = summary.get(key)
                same = (
                    actual_value is None and expected_value is None
                    or isinstance(actual_value, (int, float)) and not isinstance(actual_value, bool)
                    and isinstance(expected_value, (int, float)) and math.isclose(float(actual_value), float(expected_value), rel_tol=1e-12, abs_tol=1e-12)
                    or isinstance(actual_value, bool) and isinstance(expected_value, bool) and actual_value is expected_value
                )
                if not same:
                    errors.append(f"{label}.summary.{key} does not match case_results.")
    return _bounded_errors(errors)


def compare_reports(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    errors = _validate_report(baseline, "baseline") + _validate_report(candidate, "candidate")
    if errors:
        raise AssuranceInputError("Invalid evaluation report: " + " ".join(errors))
    if baseline["workflow"]["id"] != candidate["workflow"]["id"]:
        raise AssuranceInputError("Cannot compare reports for different workflow ids.")
    if baseline["audit"]["criteria_sha256"] != candidate["audit"]["criteria_sha256"]:
        raise AssuranceInputError("Cannot compare reports whose acceptance criteria differ.")
    baseline_cases = {case["case_id"]: case for case in baseline["case_results"]}
    candidate_cases = {case["case_id"]: case for case in candidate["case_results"]}
    if set(baseline_cases) != set(candidate_cases):
        raise AssuranceInputError("Baseline and candidate reports must use the same set of case_id values.")
    changed_expected = sorted(
        case_id for case_id in baseline_cases
        if baseline_cases[case_id]["expected_sha256"] != candidate_cases[case_id]["expected_sha256"]
    )
    if changed_expected:
        preview = ", ".join(changed_expected[:10])
        raise AssuranceInputError(
            "Cannot compare runs because expected labels changed for case_id(s): " + preview
            + (" (and more)." if len(changed_expected) > 10 else ".")
        )

    # Compare outcomes by stable case ID as well as aggregate metrics. Aggregate
    # rates can hide one fixed case and one newly broken case.
    case_changes: list[dict[str, Any]] = []
    improved_case_ids: list[str] = []
    regressed_case_ids: list[str] = []
    critical_regression_ids: list[str] = []
    for case_id in sorted(baseline_cases):
        before_case, after_case = baseline_cases[case_id], candidate_cases[case_id]
        before_critical = sum(
            1 for check in before_case["checks"]
            if _evaluation_status(check) == "FAIL" and check.get("severity", "high") == "critical"
        )
        after_critical = sum(
            1 for check in after_case["checks"]
            if _evaluation_status(check) == "FAIL" and check.get("severity", "high") == "critical"
        )
        if after_critical > before_critical:
            critical_regression_ids.append(case_id)
        if before_case["passed"] and not after_case["passed"]:
            status = "regressed"
            regressed_case_ids.append(case_id)
        elif not before_case["passed"] and after_case["passed"]:
            status = "improved"
            improved_case_ids.append(case_id)
        else:
            status = "unchanged"
        case_changes.append({
            "case_id": case_id,
            "status": status,
            "baseline_passed": before_case["passed"],
            "candidate_passed": after_case["passed"],
            "baseline_critical_failures": before_critical,
            "candidate_critical_failures": after_critical,
        })
    b, c = baseline["summary"], candidate["summary"]
    comparisons = [
        ("pass_rate", "higher_is_better", "percentage_points"),
        ("critical_failures", "lower_is_better", "count"),
        ("high_failures", "lower_is_better", "count"),
        ("review_rate", "neutral", "percentage_points"),
        ("avg_cost_usd_per_observed_case", "lower_is_better", "USD_per_observed_case"),
        ("avg_latency_ms_observed", "lower_is_better", "milliseconds"),
    ]
    metrics: dict[str, Any] = {}
    improved = regressed = unchanged = neutral_changes = 0
    for key, direction, unit in comparisons:
        before, after = b.get(key), c.get(key)
        if before is None or after is None:
            metrics[key] = {"baseline": before, "candidate": after, "delta": None, "unit": unit, "comparison": "insufficient_data"}
            continue
        delta = float(after) - float(before)
        if abs(delta) < 1e-12:
            judgment = "unchanged"
            unchanged += 1
        else:
            if direction == "neutral":
                judgment = "increased" if delta > 0 else "decreased"
                neutral_changes += 1
            else:
                is_better = delta > 0 if direction == "higher_is_better" else delta < 0
                judgment = "improved" if is_better else "regressed"
                if is_better:
                    improved += 1
                else:
                    regressed += 1
        if unit == "percentage_points":
            delta *= 100
        metrics[key] = {"baseline": before, "candidate": after, "delta": round(delta, 6), "unit": unit, "comparison": judgment}

    if critical_regression_ids:
        trend = "REGRESSED_CRITICAL_FAILURES"
    elif regressed_case_ids and improved_case_ids:
        trend = "MIXED_CASE_CHANGES"
    elif regressed_case_ids:
        trend = "REGRESSED_CASES"
    elif improved_case_ids and improved and neutral_changes:
        trend = "IMPROVED_WITH_TRADEOFF"
    elif improved_case_ids:
        trend = "IMPROVED"
    elif improved and regressed:
        trend = "MIXED"
    elif regressed and not improved:
        trend = "REGRESSED"
    elif improved and neutral_changes:
        trend = "IMPROVED_WITH_TRADEOFF"
    elif improved:
        trend = "IMPROVED"
    elif neutral_changes:
        trend = "TRADEOFF_ONLY"
    elif unchanged:
        trend = "NO_MEASURED_CHANGE"
    else:
        trend = "INSUFFICIENT_DATA"
    return {
        "workflow_id": baseline["workflow"]["id"],
        "thresholds_changed": baseline["audit"]["thresholds_sha256"] != candidate["audit"]["thresholds_sha256"],
        "baseline_run_id": baseline["run_id"],
        "candidate_run_id": candidate["run_id"],
        "overall_trend": trend,
        "metrics": metrics,
        "case_changes": case_changes,
        "regressed_case_ids": regressed_case_ids,
        "improved_case_ids": improved_case_ids,
        "critical_regression_case_ids": critical_regression_ids,
        "counts": {"improved": improved, "regressed": regressed, "unchanged": unchanged, "neutral_changes": neutral_changes},
        "interpretation_note": "A directional comparison is not a statistical significance test. Expected-label fingerprints and criteria fingerprints must match. If thresholds_changed is true, review policy differences separately; inspect per-case and critical regressions individually.",
    }


def explain_report_failures(report: dict[str, Any], max_items: int = 25) -> dict[str, Any]:
    errors = _validate_report(report, "eval_report")
    if errors:
        raise AssuranceInputError("Invalid evaluation report: " + " ".join(errors))
    if not isinstance(max_items, int) or isinstance(max_items, bool) or not 1 <= max_items <= MAX_EXPLANATION_ITEMS:
        raise AssuranceInputError(f"max_items must be an integer between 1 and {MAX_EXPLANATION_ITEMS}.")
    failures: list[dict[str, Any]] = []
    not_evaluable: list[dict[str, Any]] = []
    for case in report["case_results"]:
        if not isinstance(case, dict):
            continue
        for check in case.get("checks", []):
            if not isinstance(check, dict):
                continue
            item = {"case_id": case.get("case_id"), **check}
            status = _evaluation_status(check)
            if status == "FAIL":
                failures.append(item)
            elif status == "NOT_EVALUABLE":
                not_evaluable.append(item)
    def sort_key(item: dict[str, Any]) -> tuple[int, str, str]:
        return (
            SEVERITY_ORDER.get(item.get("severity"), 9),
            str(item.get("case_id")),
            str(item.get("criterion_id")),
        )
    failures.sort(key=sort_key)
    not_evaluable.sort(key=sort_key)
    total = len(failures)
    selected = failures[:max_items]
    selected_not_evaluable = not_evaluable[:max_items]
    grouped: dict[str, dict[str, Any]] = {}
    seen_case_ids: dict[str, set[str]] = {}
    for item in failures:
        key = str(item.get("criterion_id", "unknown"))
        group = grouped.setdefault(key, {
            "criterion_id": key, "severity": item.get("severity", "low"),
            "failure_count": 0, "case_ids": [], "case_ids_omitted_count": 0,
        })
        group["failure_count"] += 1
        case_id = item.get("case_id")
        seen = seen_case_ids.setdefault(key, set())
        if case_id not in seen:
            seen.add(case_id)
            # Keep only a small preview; total failure_count remains exact.
            if len(group["case_ids"]) < 20:
                group["case_ids"].append(case_id)
            else:
                group["case_ids_omitted_count"] += 1
    not_evaluable_grouped: dict[str, dict[str, Any]] = {}
    not_evaluable_seen_case_ids: dict[str, set[str]] = {}
    for item in not_evaluable:
        key = str(item.get("criterion_id", "unknown"))
        group = not_evaluable_grouped.setdefault(key, {
            "criterion_id": key,
            "severity": item.get("severity", "low"),
            "not_evaluable_count": 0,
            "case_ids": [],
            "case_ids_omitted_count": 0,
        })
        group["not_evaluable_count"] += 1
        case_id = item.get("case_id")
        seen = not_evaluable_seen_case_ids.setdefault(key, set())
        if case_id not in seen:
            seen.add(case_id)
            if len(group["case_ids"]) < 20:
                group["case_ids"].append(case_id)
            else:
                group["case_ids_omitted_count"] += 1

    return {
        "workflow_id": report["workflow"]["id"],
        "run_id": report["run_id"],
        "total_failed_checks": total,
        "total_not_evaluable_checks": len(not_evaluable),
        "not_evaluable_checks_returned": len(selected_not_evaluable),
        "not_evaluable_checks_truncated": len(not_evaluable) > len(selected_not_evaluable),
        "not_evaluable_groups": sorted(
            not_evaluable_grouped.values(),
            key=lambda group: (
                SEVERITY_ORDER.get(group["severity"], 9),
                -group["not_evaluable_count"],
            ),
        ),
        "not_evaluable_checks": selected_not_evaluable,
        "failures_returned": len(selected),
        "truncated": total > len(selected),
        "failure_groups": sorted(grouped.values(), key=lambda group: (SEVERITY_ORDER.get(group["severity"], 9), -group["failure_count"])),
        "failures": selected,
        "note": "Failure explanations reflect deterministic criterion results. Root-cause narratives are not inferred unless supported by supplied workflow evidence.",
    }
