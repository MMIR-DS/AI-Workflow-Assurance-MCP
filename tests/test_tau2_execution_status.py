import json
from pathlib import Path

from scripts.write_tau2_execution_status import build_status


def test_provider_failure_is_separate_from_assurance_decision(tmp_path: Path) -> None:
    results = tmp_path / "results.json"
    results.write_text("{}", encoding="utf-8")
    release = tmp_path / "release.json"
    status = build_status(
        "failure",
        "HTTP 402 reason=in_flight_budget_exhausted",
        results,
        release,
    )
    assert status["execution_status"] == "infrastructure_error"
    assert status["provider_error"] == "in_flight_budget_exhausted"
    assert status["results_file_present"] is True
    assert status["assurance_decision"] == "NOT_EVALUABLE"
    assert status["assurance_report_present"] is False
    assert status["retry_policy"]["manual_rerun_recommended"] is True
    assert status["retry_policy"]["automatic_retry_enabled"] is False
    assert status["retry_policy"]["max_provider_attempts"] == 1


def test_completed_execution_uses_awa_decision_only_from_release_report(
    tmp_path: Path,
) -> None:
    results = tmp_path / "results.json"
    results.write_text("{}", encoding="utf-8")
    release = tmp_path / "release.json"
    release.write_text(json.dumps({"decision": "NO_GO"}), encoding="utf-8")
    status = build_status("success", "", results, release)
    assert status["execution_status"] == "completed"
    assert status["assurance_decision"] == "NO_GO"
    assert status["assurance_report_present"] is True


def test_provider_error_overrides_inconsistent_success_outcome(tmp_path: Path) -> None:
    status = build_status(
        "success",
        "HTTP 402 reason=in_flight_budget_exhausted",
        tmp_path / "missing.json",
        tmp_path / "missing-release.json",
    )
    assert status["execution_status"] == "infrastructure_error"


def test_retry_after_integer_is_observed_with_log_prefix(tmp_path: Path) -> None:
    status = build_status(
        "failure",
        "2026-10-17 ERROR reason=in_flight_budget_exhausted\n"
        "2026-10-17 ERROR Retry-After: 240\n",
        tmp_path / "missing.json",
        tmp_path / "missing-release.json",
    )
    policy = status["retry_policy"]
    assert policy["retry_after_seconds_observed"] == 240
    assert policy["manual_rerun_recommended"] is True
    assert policy["max_provider_attempts"] == 1
    assert policy["automatic_retry_enabled"] is False


def test_retry_after_http_date_is_parsed(tmp_path: Path) -> None:
    status = build_status(
        "failure",
        "provider rejected request; Retry-After: Wed, 21 Oct 2099 07:28:00 GMT",
        tmp_path / "missing.json",
        tmp_path / "missing-release.json",
    )
    assert status["retry_policy"]["retry_after_seconds_observed"] > 0


def test_invalid_retry_after_is_not_guessed(tmp_path: Path) -> None:
    status = build_status(
        "failure",
        "reason=in_flight_budget_exhausted\nRetry-After: later\n",
        tmp_path / "missing.json",
        tmp_path / "missing-release.json",
    )
    assert status["retry_policy"]["retry_after_seconds_observed"] is None


def test_unknown_or_missing_evidence_never_becomes_go(tmp_path: Path) -> None:
    status = build_status(
        "failure",
        "generic failure",
        tmp_path / "missing.json",
        tmp_path / "missing-release.json",
    )
    assert status["execution_status"] == "execution_failed"
    assert status["results_file_present"] is False
    assert status["assurance_decision"] == "NOT_EVALUABLE"


def test_unrecognized_release_decision_is_not_evaluable(tmp_path: Path) -> None:
    release = tmp_path / "release.json"
    release.write_text(json.dumps({"decision": "PASS"}), encoding="utf-8")
    status = build_status("success", "", tmp_path / "results.json", release)
    assert status["assurance_decision"] == "NOT_EVALUABLE"
    assert status["assurance_report_present"] is False

def test_openrouter_insufficient_credit_error_is_not_treated_as_transient(
    tmp_path: Path,
) -> None:
    log = (
        'OpenrouterException - {"error":{"message":"This request requires more '
        'credits, or fewer max_tokens. You requested up to 512 tokens, but can '
        'only afford 391.","code":402,"metadata":{"limit_source":"openrouter_credits"}}}'
    )
    status = build_status(
        "success",
        log,
        tmp_path / "results.json",
        tmp_path / "missing-release.json",
    )
    assert status["execution_status"] == "infrastructure_error"
    assert status["provider_error"] == "insufficient_credits_or_token_budget"
    assert status["retry_policy"]["manual_rerun_recommended"] is False
    assert status["retry_policy"]["automatic_retry_enabled"] is False


def test_recorded_infrastructure_termination_overrides_success_exit(
    tmp_path: Path,
) -> None:
    results = tmp_path / "results.json"
    results.write_text(
        json.dumps({"simulations": [{"termination_reason": "infrastructure_error"}]}),
        encoding="utf-8",
    )
    status = build_status(
        "success",
        "",
        results,
        tmp_path / "missing-release.json",
    )
    assert status["execution_status"] == "infrastructure_error"
    assert status["simulation_termination_reasons"] == ["infrastructure_error"]
