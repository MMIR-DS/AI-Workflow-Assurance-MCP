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


def test_unknown_or_missing_evidence_never_becomes_go(tmp_path: Path) -> None:
    status = build_status(
        "failure", "generic failure", tmp_path / "missing.json", tmp_path / "missing-release.json"
    )
    assert status["execution_status"] == "execution_failed"
    assert status["results_file_present"] is False
    assert status["assurance_decision"] == "NOT_EVALUABLE"
