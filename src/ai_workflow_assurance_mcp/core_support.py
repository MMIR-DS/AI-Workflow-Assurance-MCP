"""Shared parsing, numeric, path, and digest helpers for deterministic workflow assurance."""

from __future__ import annotations

import hashlib
import json
import math
import re
from decimal import Decimal
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
OPERATORS = {"equals", "approx", "exists", "non_empty", "is_true", "is_false", "contains", "in_set"}
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


def _decimal_total(values: list[int | float]) -> Decimal:
    """Sum validated numeric observations in decimal representation, avoiding binary-float drift."""
    return sum((Decimal(str(value)) for value in values), Decimal("0"))


def _precise_sum(values: list[int | float]) -> float:
    return float(_decimal_total(values))


def _precise_average(values: list[int | float]) -> float | None:
    if not values:
        return None
    return float(_decimal_total(values) / Decimal(len(values)))


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
