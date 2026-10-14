"""Validation routines for workflow specifications and observed cases."""

from __future__ import annotations

from typing import Any

from ai_workflow_assurance_mcp.core_support import (
    _SLUG,
    MAX_CASES,
    MAX_CRITERIA,
    MAX_JSON_DEPTH,
    MAX_VALIDATION_ERRORS,
    OPERATORS,
    SEVERITY_ORDER,
    _bounded_errors,
    _exceeds_json_depth,
    _is_number,
    _valid_path,
)


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
