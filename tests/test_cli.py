from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples" / "invoice_matching"


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    src = str(ROOT / "src")
    env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return subprocess.run(
        [sys.executable, "-m", "ai_workflow_assurance_mcp.cli", *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_evaluate_summary_only_omits_case_results():
    result = _run_cli(
        "evaluate",
        "--spec", str(EXAMPLES / "workflow.json"),
        "--cases", str(EXAMPLES / "cases_candidate.json"),
        "--summary-only",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["case_results_omitted"] is True
    assert "case_results" not in payload
    assert payload["summary"]["pass_rate"] == 1.0
    assert len(payload["audit"]["cases_sha256"]) == 64


def test_cli_release_writes_json_file(tmp_path: Path):
    output = tmp_path / "release.json"
    result = _run_cli(
        "release",
        "--spec", str(EXAMPLES / "workflow.json"),
        "--cases", str(EXAMPLES / "cases_candidate.json"),
        "--output", str(output),
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["decision"] == "GO"
    assert "warnings" in report



def test_cli_validate_spec_reports_validity():
    result = _run_cli("validate-spec", "--spec", str(EXAMPLES / "workflow.json"))
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["valid"] is True
    assert payload["criterion_count"] > 0


def test_cli_compare_baseline_and_candidate():
    result = _run_cli(
        "compare",
        "--spec", str(EXAMPLES / "workflow.json"),
        "--baseline", str(EXAMPLES / "cases_baseline.json"),
        "--candidate", str(EXAMPLES / "cases_candidate.json"),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert "overall_trend" in payload
    assert payload["workflow_id"] == "invoice-match"


def test_cli_explain_returns_bounded_failure_summary():
    result = _run_cli(
        "explain",
        "--spec", str(EXAMPLES / "workflow.json"),
        "--cases", str(EXAMPLES / "cases_baseline.json"),
        "--max-items", "1",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["failures_returned"] <= 1
    assert "failure_groups" in payload


def test_cli_invalid_input_returns_nonzero_without_traceback(tmp_path: Path):
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not-json", encoding="utf-8")
    result = _run_cli("validate-spec", "--spec", str(invalid))
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
