"""Write an operational Tau2 status without conflating it with AWA's decision."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def build_status(
    outcome: str, log_text: str, results_path: Path, release_report_path: Path
) -> dict[str, Any]:
    """Separate runner execution health from the assurance decision."""
    normalized_outcome = outcome.strip().lower()
    provider_error = (
        "in_flight_budget_exhausted"
        if "in_flight_budget_exhausted" in log_text
        else "weight_exceeds_budget"
        if "weight_exceeds_budget" in log_text
        else None
    )

    if normalized_outcome == "success":
        execution_status = "completed"
    elif normalized_outcome == "skipped":
        execution_status = "not_run"
    elif provider_error:
        execution_status = "infrastructure_error"
    elif normalized_outcome == "failure":
        execution_status = "execution_failed"
    else:
        execution_status = "unknown"

    release = _read_json(release_report_path)
    decision = release.get("decision") if release else None
    if not isinstance(decision, str) or not decision:
        decision = "NOT_EVALUABLE"

    return {
        "schema_version": "1.0",
        "execution_status": execution_status,
        "tau2_step_outcome": normalized_outcome or "unknown",
        "provider_error": provider_error,
        "results_file_present": results_path.is_file(),
        "assurance_decision": decision,
        "assurance_report_present": release is not None,
        "interpretation": (
            "Execution status describes the Tau2 runner; assurance_decision is taken "
            "only from the AWA release report. Missing reports are NOT_EVALUABLE, never GO."
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
        json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
