"""Write an operational Tau2 status without conflating it with AWA's decision."""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

MAX_RETRY_AFTER_SECONDS = 120
MAX_PROVIDER_ATTEMPTS = 2  # initial request plus at most one retry


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _retry_after_seconds(log_text: str) -> int | None:
    """Extract Retry-After from a preserved header/log line; never guess a delay."""
    match = re.search(r"(?im)^\s*retry-after\s*:\s*([^\s,;]+)", log_text)
    if not match:
        return None
    raw = match.group(1).strip()
    if raw.isdigit():
        return int(raw)
    try:
        when = parsedate_to_datetime(raw)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max(0, int((when - datetime.now(timezone.utc)).total_seconds()))
    except (TypeError, ValueError, OverflowError):
        return None


def build_status(
    outcome: str, log_text: str, results_path: Path, release_report_path: Path
) -> dict[str, Any]:
    """Separate runner health, provider diagnostics, and AWA's release decision."""
    normalized_outcome = outcome.strip().lower()
    provider_error = (
        "in_flight_budget_exhausted"
        if "in_flight_budget_exhausted" in log_text
        else "weight_exceeds_budget"
        if "weight_exceeds_budget" in log_text
        else None
    )

    # A known provider rejection takes precedence even if a wrapper accidentally exits 0.
    if provider_error:
        execution_status = "infrastructure_error"
    elif normalized_outcome == "success":
        execution_status = "completed"
    elif normalized_outcome == "skipped":
        execution_status = "not_run"
    elif normalized_outcome == "failure":
        execution_status = "execution_failed"
    else:
        execution_status = "unknown"

    retry_after = _retry_after_seconds(log_text)
    retry_recommended = provider_error == "in_flight_budget_exhausted"
    release = _read_json(release_report_path)
    decision = release.get("decision") if release else None
    if decision not in {"GO", "HOLD", "NO_GO"}:
        decision = "NOT_EVALUABLE"

    return {
        "schema_version": "1.1",
        "execution_status": execution_status,
        "tau2_step_outcome": normalized_outcome or "unknown",
        "provider_error": provider_error,
        "retry_policy": {
            "retry_recommended": retry_recommended,
            "retry_after_seconds_observed": retry_after,
            "retry_after_seconds_capped": (
                min(retry_after, MAX_RETRY_AFTER_SECONDS)
                if retry_after is not None else None
            ),
            "max_provider_attempts": MAX_PROVIDER_ATTEMPTS,
            "automatic_retry_enabled": False,
            "note": (
                "Diagnostic recommendation only; this report does not perform retries. "
                "Honor a valid Retry-After, cap waiting at 120 seconds, and allow at most "
                "one retry only after the pinned client preserves response metadata."
            ),
        },
        "results_file_present": results_path.is_file(),
        "assurance_decision": decision,
        "assurance_report_present": release is not None and decision != "NOT_EVALUABLE",
        "interpretation": (
            "Execution status describes the Tau2 runner; assurance_decision is taken "
            "only from a recognized AWA release report. Missing or invalid reports are "
            "NOT_EVALUABLE, never GO."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tau2-outcome", required=True)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--release-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        log_text = args.log.read_text(encoding="utf-8")
    except OSError:
        log_text = ""

    status = build_status(
        args.tau2_outcome, log_text, args.results, args.release_report
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(status, indent=2, sort_keys=True) + "\\n", encoding="utf-8"
    )
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
