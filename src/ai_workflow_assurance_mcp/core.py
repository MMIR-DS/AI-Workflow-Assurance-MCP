"""Deterministic assurance logic independent of the MCP transport.

Important scope boundary: this module evaluates outputs already produced by a
workflow. It does not execute arbitrary agents, tools, code, or external actions.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import uuid
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "0.4"
MAX_JSON_CHARS = 2_000_000
MAX_JSON_DEPTH = 64
MAX_PATH_PARTS = 32
MAX_CASES = 500
MAX_CRITERIA = 50
MAX_EXPLANATION_ITEMS = 100
MAX_VALIDATION_ERRORS = 100
MAX_ERROR_CHARS = 300
SMALL_SAMPLE_WARNING_SIZE = 20
MAX_EVALUATION_CHECKS = 5_000
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
OPERATORS = {"equals", "approx", "exists", "is_true", "is_false", "contains", "in_set"}
_SLUG = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_PATH_PART = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class AssuranceInputError(ValueError):
    """Raised when a workflow specification or evaluation input is invalid."""


def parse_json_text(value: str, label: str) -> Any:
    if not isinstance(value, str):
        raise AssuranceInputError(f"{label} must be supplied as JSON text.")
    if len(value) > MAX_JSON_CHARS:
        raise AssuranceInputError(f"{label} exceeds the {MAX_JSON_CHARS:,}-character input limit.")

    def reject_constant(token: str) -> Any:
        raise AssuranceInputError(f"{label} contains the non-standard JSON numeric token {token}.")

    def parse_finite_float(token: str) -> float:
        number = float(token)
        if not math.isfinite(number):
            raise AssuranceInputError(f"{label} contains a number outside the supported finite range.")
        return number

    def parse_finite_int(token: str) -> int:
        number = int(token)
        try:
            finite = math.isfinite(float(number))
        except OverflowError:
            finite = False
        if not finite:
            raise AssuranceInputError(f"{label} contains an integer outside the supported finite numeric range.")
        return number

    try:
        parsed = json.loads(
            value, parse_constant=reject_constant, parse_float=parse_finite_float, parse_int=parse_finite_int
        )
        if _exceeds_json_depth(parsed):
            raise AssuranceInputError(f"{label} exceeds the maximum JSON nesting depth of {MAX_JSON_DEPTH}.")
        return parsed
    except AssuranceInputError:
        raise
    except json.JSONDecodeError as exc:
        raise AssuranceInputError(
            f"{label} is not valid JSON (line {exc.lineno}, column {exc.colno})."
        ) from exc
    except (RecursionError, OverflowError) as exc:
        raise AssuranceInputError(f"{label} is nested too deeply or contains an unsupported numeric value.") from exc
    except ValueError as exc:
        # Python limits the number of digits in parsed integers on recent versions.
        # Keep that implementation detail inside the public input-error contract.
        raise AssuranceInputError(f"{label} contains a value that cannot be parsed safely.") from exc


def _exceeds_json_depth(value: Any, max_depth: int = MAX_JSON_DEPTH) -> bool:
    """Check JSON-compatible containers iteratively so hostile nesting cannot recurse."""
    stack: list[tuple[Any, int]] = [(value, 0)]
    deepest_seen: dict[int, int] = {}
    while stack:
        current, depth = stack.pop()
        if not isinstance(current, (dict, list)):
            continue
        # Root container has depth 0, so depth == max_depth means the
        # input contains one container more than the supported maximum.
        if depth >= max_depth:
            return True
        object_id = id(current)
        if deepest_seen.get(object_id, -1) >= depth:
            continue
        deepest_seen[object_id] = depth
        children = current.values() if isinstance(current, dict) else current
        stack.extend((child, depth + 1) for child in children)
    return False


def _canonicalize_for_digest(value: Any) -> Any:
    """Normalize numerically equal integral floats so fingerprints match evaluator semantics."""
    if isinstance(value, dict):
        return {key: _canonicalize_for_digest(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonicalize_for_digest(item) for item in value]
    if type(value) is float and math.isfinite(value) and value.is_integer():
        return int(value)
    return value


def summarize_workflow_metadata(spec: Any) -> dict[str, str | None]:
    """Bound workflow metadata echoed by validation tools."""
    if not isinstance(spec, dict):
        return {"id": None, "name": None, "version": None}
    result: dict[str, str | None] = {}
    for key in ("id", "name", "version"):
        value = spec.get(key)
        result[key] = value[:160] if isinstance(value, str) else None
    return result


def summarize_thresholds(thresholds: Any) -> dict[str, int | float]:
    """Return only known, scalar numeric thresholds suitable for bounded tool output."""
    allowed = (
        "min_pass_rate", "max_critical_failures", "max_high_failures", "max_review_rate",
        "max_avg_cost_usd", "max_avg_latency_ms", "max_case_cost_usd", "max_case_latency_ms",
    )
    if not isinstance(thresholds, dict):
        return {}
    safe: dict[str, int | float] = {}
    for key in allowed:
        value = thresholds.get(key)
        if type(value) is int or type(value) is float and math.isfinite(value):
            safe[key] = value
    return safe



def summarize_unknown_thresholds(thresholds: Any) -> list[str]:
    """Return bounded names of unsupported threshold keys for validation output."""
    allowed = {
        "min_pass_rate", "max_critical_failures", "max_high_failures", "max_review_rate",
        "max_avg_cost_usd", "max_avg_latency_ms", "max_case_cost_usd", "max_case_latency_ms",
    }
    if not isinstance(thresholds, dict):
        return []
    return sorted(str(key) for key in set(thresholds) - allowed)[:MAX_VALIDATION_ERRORS]


def _is_number(value: Any) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, ValueError):
        return False


def _valid_path(path: Any) -> bool:
    if not isinstance(path, str) or not path or len(path) > 256:
        return False
    parts = path.split(".")
    return len(parts) <= MAX_PATH_PARTS and all(
        _PATH_PART.fullmatch(part) and not part.startswith("_") for part in parts
    )


def _lookup_path(root: Any, path: str) -> tuple[bool, Any]:
    """Resolve simple dotted dictionary/list paths without eval or attribute access."""
    if not _valid_path(path):
        return False, None
    current = root
    for part in path.split("."):
        if isinstance(current, dict):
            if part not in current:
                return False, None
            current = current[part]
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            if index >= len(current):
                return False, None
            current = current[index]
        else:
            return False, None
    return True, current


def _typed_equal(left: Any, right: Any) -> bool:
    """Compare JSON values recursively without Python's bool/int equality trap."""
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) or isinstance(right, (int, float)):
        return _is_number(left) and _is_number(right) and left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_typed_equal(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_typed_equal(a, b) for a, b in zip(left, right, strict=True))
    return left == right


def _bounded_errors(errors: list[str]) -> list[str]:
    """Bound error count and individual message sizes to avoid context flooding."""
    bounded = [message[:MAX_ERROR_CHARS] for message in errors[:MAX_VALIDATION_ERRORS]]
    if len(errors) > MAX_VALIDATION_ERRORS:
        bounded.append(f"Additional validation errors omitted (limit: {MAX_VALIDATION_ERRORS}).")
    return bounded


def _bounded_report_value(value: Any, max_chars: int = 256) -> Any:
    """Keep a single failed value from ballooning the structured MCP response."""
    try:
        serialized = json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        serialized = repr(value)
    if len(serialized) <= max_chars:
        return value
    return {
        "_truncated": True,
        "preview": serialized[: max_chars - 40],
        "original_json_chars": len(serialized),
    }


def validate_spec(spec: Any) -> list[str]:
    """Return validation errors. An empty list means the specification is valid."""
    errors: list[str] = []
    if not isinstance(spec, dict):
        return ["Workflow specification must be a JSON object."]
    if _exceeds_json_depth(spec):
        return [f"Workflow specification exceeds the maximum JSON nesting depth of {MAX_JSON_DEPTH}."]

    for key in ("id", "name", "version"):
        if not isinstance(spec.get(key), str) or not spec[key].strip():
            errors.append(f"'{key}' must be a non-empty string.")
        elif len(spec[key]) > 160:
            errors.append(f"'{key}' must be 160 characters or fewer.")
    if isinstance(spec.get("id"), str) and not _SLUG.fullmatch(spec["id"]):
        errors.append("'id' must start with a letter and contain only letters, numbers, '_' or '-'.")

    criteria = spec.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        errors.append("'criteria' must be a non-empty list.")
    elif len(criteria) > MAX_CRITERIA:
        errors.append(f"'criteria' may contain at most {MAX_CRITERIA} items.")
    else:
        seen_ids: set[str] = set()
        for index, item in enumerate(criteria):
            prefix = f"criteria[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{prefix} must be an object.")
                continue
            cid = item.get("id")
            if not isinstance(cid, str) or not _SLUG.fullmatch(cid):
                errors.append(f"{prefix}.id must be a valid identifier (letters/numbers/_/-; starts with a letter).")
            elif cid in seen_ids:
                errors.append(f"Duplicate criterion id: {cid}.")
            else:
                seen_ids.add(cid)

            operator = item.get("operator")
            if not isinstance(operator, str) or operator not in OPERATORS:
                errors.append(f"{prefix}.operator must be one of {sorted(OPERATORS)}.")
            actual_path = item.get("actual_path")
            if not _valid_path(actual_path):
                errors.append(f"{prefix}.actual_path must be a safe dotted path (for example 'decision.status').")

            expected_required = isinstance(operator, str) and operator in {"equals", "approx", "contains", "in_set"}
            has_expected_path = "expected_path" in item
            has_expected_value = "expected_value" in item
            if expected_required and has_expected_path == has_expected_value:
                errors.append(f"{prefix} must define exactly one of expected_path or expected_value.")
            if not expected_required and (has_expected_path or has_expected_value):
                errors.append(f"{prefix} operator '{operator}' does not accept expected_path or expected_value.")
            if has_expected_path and not _valid_path(item.get("expected_path")):
                errors.append(f"{prefix}.expected_path must be a safe dotted path.")
            if operator == "approx":
                tolerance = item.get("tolerance")
                if not _is_number(tolerance) or float(tolerance) < 0:
                    errors.append(f"{prefix}.tolerance must be a finite number greater than or equal to zero.")
            if operator == "in_set" and has_expected_value and not isinstance(item.get("expected_value"), list):
                errors.append(f"{prefix}.expected_value must be a list when operator is 'in_set'.")
            severity = item.get("severity", "high")
            if not isinstance(severity, str) or severity not in SEVERITY_ORDER:
                errors.append(f"{prefix}.severity must be one of {list(SEVERITY_ORDER)}.")

    thresholds = spec.get("thresholds")
    if not isinstance(thresholds, dict):
        errors.append("'thresholds' must be an object.")
    else:
        min_pass_rate = thresholds.get("min_pass_rate")
        if not _is_number(min_pass_rate) or not 0 < float(min_pass_rate) <= 1:
            errors.append("thresholds.min_pass_rate must be greater than 0 and at most 1.")
        max_critical = thresholds.get("max_critical_failures")
        if not isinstance(max_critical, int) or isinstance(max_critical, bool) or max_critical < 0:
            errors.append("thresholds.max_critical_failures must be a non-negative integer.")
        if "max_high_failures" in thresholds:
            max_high = thresholds["max_high_failures"]
            if not isinstance(max_high, int) or isinstance(max_high, bool) or max_high < 0:
                errors.append("thresholds.max_high_failures must be a non-negative integer.")
        for key in ("max_review_rate",):
            if key in thresholds and (not _is_number(thresholds[key]) or not 0 <= float(thresholds[key]) <= 1):
                errors.append(f"thresholds.{key} must be between 0 and 1.")
        for key in ("max_avg_cost_usd", "max_avg_latency_ms", "max_case_cost_usd", "max_case_latency_ms"):
            if key in thresholds and (not _is_number(thresholds[key]) or float(thresholds[key]) < 0):
                errors.append(f"thresholds.{key} must be a finite non-negative number.")
        allowed = {
            "min_pass_rate", "max_critical_failures", "max_high_failures", "max_review_rate",
            "max_avg_cost_usd", "max_avg_latency_ms", "max_case_cost_usd", "max_case_latency_ms",
        }
        unknown_keys = sorted(set(thresholds) - allowed)
        for unknown in unknown_keys[:MAX_VALIDATION_ERRORS]:
            errors.append(f"Unknown release threshold: '{unknown}'.")
        if len(unknown_keys) > MAX_VALIDATION_ERRORS:
            errors.append(f"Additional unknown release thresholds omitted (limit: {MAX_VALIDATION_ERRORS}).")

    return _bounded_errors(errors)


def validate_cases(cases: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(cases, list) or not cases:
        return ["Cases must be a non-empty JSON list."]
    if _exceeds_json_depth(cases):
        return [f"Cases exceed the maximum JSON nesting depth of {MAX_JSON_DEPTH}."]
    if len(cases) > MAX_CASES:
        return [f"At most {MAX_CASES} cases are allowed per evaluation run."]
    seen: set[str] = set()
    for index, case in enumerate(cases):
        prefix = f"cases[{index}]"
        if not isinstance(case, dict):
            errors.append(f"{prefix} must be an object.")
            continue
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id.strip() or len(case_id) > 120:
            errors.append(f"{prefix}.case_id must be a non-empty string of at most 120 characters.")
        elif case_id in seen:
            errors.append(f"Duplicate case_id: {case_id}.")
        else:
            seen.add(case_id)
        if not isinstance(case.get("expected"), (dict, list)):
            errors.append(f"{prefix}.expected must be a JSON object or list.")
        if not isinstance(case.get("actual"), (dict, list)):
            errors.append(f"{prefix}.actual must be a JSON object or list.")
        if "unobserved_checks" in case:
            unobserved = case["unobserved_checks"]
            if (
                not isinstance(unobserved, list)
                or any(not isinstance(item, str) or not item.strip() for item in unobserved)
                or len(set(unobserved)) != len(unobserved)
            ):
                errors.append(f"{prefix}.unobserved_checks must be a list of unique non-empty criterion ids.")
        for key in ("cost_usd", "latency_ms"):
            if key in case and (not _is_number(case[key]) or float(case[key]) < 0):
                errors.append(f"{prefix}.{key} must be a finite non-negative number.")
        review_keys = [key for key in ("human_review_observed", "human_review_required") if key in case]
        for key in review_keys:
            if not isinstance(case[key], bool):
                errors.append(f"{prefix}.{key} must be true or false.")
        if len(review_keys) == 2 and case["human_review_observed"] != case["human_review_required"]:
            errors.append(f"{prefix}.human_review_observed conflicts with legacy human_review_required.")
    return _bounded_errors(errors)


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
        passed = actual_exists
        message = "Path exists." if passed else f"Required path '{criterion['actual_path']}' is missing."
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
        "total_cost_usd_observed": sum(costs) if costs else None,
        "avg_cost_usd_per_observed_case": sum(costs) / len(costs) if costs else None,
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
                "total_cost_usd_observed": sum(costs) if costs else None,
                "avg_cost_usd_per_observed_case": sum(costs) / len(costs) if costs else None,
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
    sort_key = lambda item: (
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


def stable_json_digest(value: Any) -> str:
    """Return a deterministic digest useful for audit references (not a signature)."""
    if _exceeds_json_depth(value):
        raise AssuranceInputError(f"Cannot fingerprint data nested deeper than {MAX_JSON_DEPTH} levels.")
    canonical = _canonicalize_for_digest(value)
    # ASCII escaping makes lone surrogate code points safe and deterministic.
    try:
        payload = json.dumps(
            canonical,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, OverflowError) as exc:
        raise AssuranceInputError(
            "Cannot fingerprint data containing unsupported or non-finite values."
        ) from exc
    return hashlib.sha256(payload).hexdigest()
