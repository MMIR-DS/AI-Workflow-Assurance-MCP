"""Threshold-based release decision construction over validated assurance reports."""

from __future__ import annotations

from typing import Any

from ai_workflow_assurance_mcp.core_comparison import (
    _validate_report,
)

from ai_workflow_assurance_mcp.core_support import (
    AssuranceInputError,
    SMALL_SAMPLE_WARNING_SIZE,
    stable_json_digest,
)

from ai_workflow_assurance_mcp.core_validation import (
    validate_spec,
)

def create_release_report(spec: dict[str, Any], report: dict[str, Any]) -> dict[str, Any]:
    errors = validate_spec(spec) + _validate_report(report, "eval_report")
    if errors:
        raise AssuranceInputError("Invalid release inputs: " + " ".join(errors))
    if spec["id"] != report["workflow"]["id"]:
        raise AssuranceInputError("Workflow specification and evaluation report have different workflow ids.")
    if stable_json_digest(spec) != report["audit"]["spec_sha256"]:
        raise AssuranceInputError("Workflow specification does not match the specification used to evaluate this report.")
    thresholds = spec["thresholds"]
    summary = report["summary"]
    checks: list[dict[str, Any]] = []

    def add_check(name: str, observed: Any, comparator: str, limit: Any, note: str = "") -> None:
        if observed is None:
            status = "NOT_EVALUABLE"
            passed = None
        else:
            passed = observed >= limit if comparator == ">=" else observed <= limit
            status = "PASS" if passed else "FAIL"
        checks.append({"metric": name, "observed": observed, "comparator": comparator, "threshold": limit, "status": status, "passed": passed, "note": note})

    # Missing observations must never disappear behind another passing aggregate
    # (for example, a high overall pass rate when an unrelated low-severity check fails).
    # The current spec schema has no explicit allowance for NOT_EVALUABLE checks, so any
    # such check prevents GO; independent release-gate FAILs still take precedence as NO_GO.
    not_evaluable_count = summary.get("not_evaluable_checks", 0)
    if not_evaluable_count > 0:
        checks.append({
            "metric": "not_evaluable_evidence",
            "observed": not_evaluable_count,
            "comparator": "<=",
            "threshold": 0,
            "status": "NOT_EVALUABLE",
            "passed": None,
            "note": (
                "At least one criterion could not be evaluated. No policy in the current "
                "spec schema authorizes ignoring unobserved evidence for a GO decision."
            ),
        })
    else:
        add_check(
            "not_evaluable_evidence",
            0,
            "<=",
            0,
            "No criterion was marked NOT_EVALUABLE.",
        )

    if summary.get("not_evaluable_cases", 0) > 0 and summary.get("failed_checks", 0) == 0:
        add_check(
            "pass_rate",
            None,
            ">=",
            float(thresholds["min_pass_rate"]),
            "At least one case has unobserved checks and no observed failed check; a passing suite rate cannot be established.",
        )
    else:
        add_check("pass_rate", summary.get("pass_rate"), ">=", float(thresholds["min_pass_rate"]))
    add_check("critical_failures", summary.get("critical_failures"), "<=", thresholds["max_critical_failures"])
    if "max_high_failures" in thresholds:
        add_check("high_failures", summary.get("high_failures"), "<=", thresholds["max_high_failures"])
    if "max_review_rate" in thresholds:
        review_rate = summary.get("review_rate")
        coverage = summary.get("review_observation_coverage", 0)
        if coverage < 1:
            review_rate = None
        add_check("review_rate", review_rate, "<=", float(thresholds["max_review_rate"]), "Requires human-review observation for every case.")
    if "max_avg_cost_usd" in thresholds:
        cost = summary.get("avg_cost_usd_per_observed_case")
        if summary.get("cost_observation_coverage", 0) < 1:
            cost = None
        add_check("avg_cost_usd_per_case", cost, "<=", float(thresholds["max_avg_cost_usd"]), "Requires cost observation for every case.")
    if "max_avg_latency_ms" in thresholds:
        latency = summary.get("avg_latency_ms_observed")
        if summary.get("latency_observation_coverage", 0) < 1:
            latency = None
        add_check("avg_latency_ms", latency, "<=", float(thresholds["max_avg_latency_ms"]), "Requires latency observation for every case.")
    if "max_case_cost_usd" in thresholds:
        case_cost = summary.get("max_cost_usd_observed")
        if summary.get("cost_observation_coverage", 0) < 1:
            case_cost = None
        add_check("max_case_cost_usd", case_cost, "<=", float(thresholds["max_case_cost_usd"]), "Requires cost observation for every case.")
    if "max_case_latency_ms" in thresholds:
        case_latency = summary.get("max_latency_ms_observed")
        if summary.get("latency_observation_coverage", 0) < 1:
            case_latency = None
        add_check("max_case_latency_ms", case_latency, "<=", float(thresholds["max_case_latency_ms"]), "Requires latency observation for every case.")

    statuses = [check["status"] for check in checks]
    if "FAIL" in statuses:
        decision = "NO_GO"
    elif "NOT_EVALUABLE" in statuses:
        decision = "HOLD"
    else:
        decision = "GO"
    warnings: list[dict[str, str]] = []
    criteria = spec.get("criteria", [])
    if not any(item.get("severity", "high") == "critical" for item in criteria if isinstance(item, dict)):
        warnings.append({"code": "NO_CRITICAL_CRITERIA", "message": "No criterion is marked critical; max_critical_failures will not provide a meaningful critical-failure gate."})
    if any(item.get("severity", "high") == "high" for item in criteria if isinstance(item, dict)) and "max_high_failures" not in thresholds:
        warnings.append({"code": "NO_HIGH_FAILURE_CAP", "message": "High-severity failures are not independently capped; the pass-rate threshold remains the only gate for them."})
    if summary.get("total_cases", 0) < SMALL_SAMPLE_WARNING_SIZE:
        warnings.append({"code": "SMALL_SAMPLE_SIZE", "message": f"Only {summary.get('total_cases', 0)} cases were evaluated. Fewer than {SMALL_SAMPLE_WARNING_SIZE} cases is a heuristic warning, not a statistical power assessment."})
    if thresholds.get("max_critical_failures", 0) > 0:
        warnings.append({"code": "CRITICAL_FAILURES_ALLOWED", "message": "The release policy explicitly permits some critical criterion failures; confirm this allowance is intentional."})
    return {
        "workflow": report["workflow"],
        "run_id": report["run_id"],
        "audit": report["audit"],
        "decision": decision,
        "checks": checks,
        "warnings": warnings,
        "blocking_checks": [check["metric"] for check in checks if check["status"] in {"FAIL", "NOT_EVALUABLE"}],
        "release_note": "GO means only that this supplied test suite met its configured thresholds. It is not a guarantee of safety, correctness in untested situations, legal compliance, or production readiness. Digests detect changes but are not signatures or proof of source authenticity.",
    }
