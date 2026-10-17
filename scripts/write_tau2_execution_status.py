"""Write an operational Tau2 status without conflating it with AWA's decision."""
from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _retry_after_seconds(log_text: str) -> int | None:
    """Extract Retry-After from a preserved header/log line; never guess a delay."""
    match = re.search(r"(?im)\bretry-after\s*:\s*([^\r\n]+)", log_text)
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
    lower_log = log_text.lower()
    if "in_flight_budget_exhausted" in lower_log:
        provider_error = "in_flight_budget_exhausted"
    elif "prompt tokens limit exceeded" in lower_log:
        provider_error = "prompt_token_budget_exceeded"
    elif "weight_exceeds_budget" in lower_log:
        provider_error = "weight_exceeds_budget"
    elif any(
        marker in lower_log
        for marker in (
            "limit_source=openrouter_credits",
            '"limit_source": "openrouter_credits"',
            "openrouter_credits",
            "can only afford",
            "requires more credits, or fewer max_tokens",
        )
    ):
        provider_error = "insufficient_credits_or_token_budget"
    else:
        provider_error = None

    results = _read_json(results_path)
    simulations = results.get("simulations") if results else None
    simulation_termination_reasons = (
        [
            str(simulation["termination_reason"]).strip().lower()
            for simulation in simulations
            if isinstance(simulation, dict)
            and isinstance(simulation.get("termination_reason"), str)
            and simulation["termination_reason"].strip()
        ]
        if isinstance(simulations, list)
        else []
    )
    recorded_infrastructure_error = (
        "infrastructure_error" in simulation_termination_reasons
    )

    # Tau2 may serialize infrastructure_error while its CLI exits 0.
    if provider_error or recorded_infrastructure_error:
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
    # An in-flight condition may clear with time. A credit-budget rejection needs
    # a lower cap or more available credits, not a blind rerun.
    manual_rerun_recommended = provider_error == "in_flight_budget_exhausted"
    release = _read_json(release_report_path)
    decision = release.get("decision") if release else None
    if decision not in {"GO", "HOLD", "NO_GO"}:
        decision = "NOT_EVALUABLE"

    return {
        "schema_version": "1.3",
        "execution_status": execution_status,
        "tau2_step_outcome": normalized_outcome or "unknown",
        "provider_error": provider_error,
        "retry_policy": {
            "manual_rerun_recommended": manual_rerun_recommended,
            "retry_after_seconds_observed": retry_after,
            "max_provider_attempts": 1,
            "automatic_retry_enabled": False,
            "note": (
                "The bounded workflow sets TAU2_LITELLM_NUM_RETRIES=0 to disable "
                "hidden per-call provider retries. This status report never retries "
                "or waits. An in-flight budget error may justify a separate manual "
                "rerun after the provider condition clears; a prompt-token limit error "
                "requires a shorter prompt/tool context or a higher key/workspace limit. "
                "A completion-budget error may need a lower output cap or more available "
                "credit. Retry-After is recorded only when it survives in logs."
            ),
        },
        "results_file_present": results_path.is_file(),
        "simulation_termination_reasons": simulation_termination_reasons,
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
        json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
