"""Run the synthetic invoice example without an MCP host or an LLM API key."""
from __future__ import annotations

import json
from pathlib import Path

from ai_workflow_assurance_mcp.core import compare_reports, create_release_report, evaluate_suite

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_DIR = ROOT / "examples" / "invoice_matching"


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    spec = read_json(EXAMPLE_DIR / "workflow.json")
    baseline = evaluate_suite(spec, read_json(EXAMPLE_DIR / "cases_baseline.json"))
    candidate = evaluate_suite(spec, read_json(EXAMPLE_DIR / "cases_candidate.json"))
    result = {
        "baseline_summary": baseline["summary"],
        "candidate_summary": candidate["summary"],
        "comparison": compare_reports(baseline, candidate),
        "candidate_release_report": create_release_report(spec, candidate),
        "note": "Synthetic demonstration only. Not evidence about a production system.",
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
