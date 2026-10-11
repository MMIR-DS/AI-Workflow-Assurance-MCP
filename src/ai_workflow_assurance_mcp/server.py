"""MCP transport adapter. All substantive logic lives in ``core.py``."""

from __future__ import annotations

from functools import wraps
from typing import Any, Callable, TypeVar

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from ai_workflow_assurance_mcp import __version__
from ai_workflow_assurance_mcp.core import (
    AssuranceInputError,
    compare_reports,
    create_release_report,
    evaluate_suite,
    explain_report_failures,
    parse_json_text,
    summarize_thresholds,
    summarize_workflow_metadata,
    validate_spec,
)
from ai_workflow_assurance_mcp.evidence_sources import MAX_MANIFEST_BYTES, Tau2ManifestFileSource

F = TypeVar("F", bound=Callable[..., Any])


def _map_input_errors_to_tool_errors(function: F) -> F:
    """Expose expected validation errors to the calling model without leaking tracebacks."""
    @wraps(function)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        try:
            return function(*args, **kwargs)
        except AssuranceInputError as exc:
            raise ToolError(str(exc)) from exc

    return wrapped  # type: ignore[return-value]


mcp = MCPServer(
    "AI Workflow Assurance",
    version=__version__,
    instructions=(
        "Evaluate supplied outputs of AI-enabled business workflows against deterministic criteria. "
        "The server does not execute arbitrary agents or tools. Treat all reports as scoped evidence, "
        "not a universal safety certificate. Inputs are JSON text; outputs are structured JSON objects."
    ),
)


def _parse_and_validate_spec(workflow_spec_json: str) -> dict[str, Any]:
    spec = parse_json_text(workflow_spec_json, "workflow_spec_json")
    errors = validate_spec(spec)
    if errors:
        raise AssuranceInputError("Invalid workflow specification: " + " ".join(errors))
    return spec


@mcp.tool()
@_map_input_errors_to_tool_errors
def inspect_tau2_evidence_manifest(manifest_json: str) -> dict[str, Any]:
    """Validate and normalize a supplied tau2 simulator manifest; does not authenticate it."""
    if not isinstance(manifest_json, str):
        raise AssuranceInputError("manifest_json must be JSON text.")
    if len(manifest_json.encode("utf-8", errors="replace")) > MAX_MANIFEST_BYTES:
        raise AssuranceInputError(
            f"manifest_json exceeds the {MAX_MANIFEST_BYTES}-byte size limit."
        )
    manifest = parse_json_text(manifest_json, "manifest_json")
    try:
        envelope = Tau2ManifestFileSource.normalize_manifest(manifest)
    except ValueError as exc:
        raise AssuranceInputError(f"Could not inspect evidence manifest: {exc}") from exc
    return {
        "source_name": envelope.source_name,
        "source_version": envelope.source_version,
        "assurance_scope": envelope.assurance_scope,
        "source_authenticity": envelope.source_authenticity,
        "release_eligible": envelope.release_eligible,
        "collected_at": (
            envelope.collected_at.isoformat() if envelope.collected_at is not None else None
        ),
        "evidence": envelope.evidence,
    }


@mcp.tool()
def validate_workflow_spec(workflow_spec_json: str) -> dict[str, Any]:
    """Validate a workflow specification and its deterministic release thresholds."""
    try:
        spec = parse_json_text(workflow_spec_json, "workflow_spec_json")
    except AssuranceInputError as exc:
        return {"valid": False, "workflow": None, "criterion_count": 0, "thresholds": None, "errors": [str(exc)]}
    errors = validate_spec(spec)
    if not isinstance(spec, dict):
        return {"valid": False, "errors": errors}
    return {
        "valid": not errors,
        "workflow": summarize_workflow_metadata(spec),
        "criterion_count": len(spec.get("criteria", [])) if isinstance(spec.get("criteria"), list) else 0,
        "thresholds": summarize_thresholds(spec.get("thresholds")),
        "errors": errors,
        "limitations": ["Validation checks schema and supported operators only; it does not prove the criteria are complete or appropriate for the business risk."],
    }


@mcp.tool()
@_map_input_errors_to_tool_errors
def run_eval_suite(
    workflow_spec_json: str,
    cases_json: str,
    summary_only: bool = True,
) -> dict[str, Any]:
    """Run deterministic checks; details are omitted by default to protect model context."""
    spec = _parse_and_validate_spec(workflow_spec_json)
    cases = parse_json_text(cases_json, "cases_json")
    report = evaluate_suite(spec, cases)
    if summary_only:
        return {
            "schema_version": report["schema_version"],
            "run_id": report["run_id"],
            "executed_at": report["executed_at"],
            "workflow": report["workflow"],
            "audit": report["audit"],
            "summary": report["summary"],
            "case_results_omitted": True,
            "assurance_scope": report["assurance_scope"],
        }
    return report


@mcp.tool()
@_map_input_errors_to_tool_errors
def compare_eval_runs(
    workflow_spec_json: str,
    baseline_cases_json: str,
    candidate_cases_json: str,
    include_case_details: bool = False,
) -> dict[str, Any]:
    """Compare two runs; per-case detail is opt-in to keep default output bounded."""
    spec = _parse_and_validate_spec(workflow_spec_json)
    baseline_cases = parse_json_text(baseline_cases_json, "baseline_cases_json")
    candidate_cases = parse_json_text(candidate_cases_json, "candidate_cases_json")
    baseline = evaluate_suite(spec, baseline_cases)
    candidate = evaluate_suite(spec, candidate_cases)
    comparison = compare_reports(baseline, candidate)
    if not include_case_details:
        detailed_changes = comparison.pop("case_changes", [])
        comparison["case_details_omitted"] = True
        comparison["case_change_count"] = len(detailed_changes)
        comparison["case_change_preview"] = detailed_changes[:20]
        for field in ("regressed_case_ids", "improved_case_ids", "critical_regression_case_ids"):
            ids = comparison.get(field, [])
            comparison[field + "_count"] = len(ids)
            comparison[field + "_preview"] = ids[:20]
            comparison.pop(field, None)
    return {
        "baseline_summary": baseline["summary"],
        "candidate_summary": candidate["summary"],
        "comparison": comparison,
        "assurance_scope": "Compares supplied observations only; it does not execute the external workflow or verify that labels are representative.",
    }


@mcp.tool()
@_map_input_errors_to_tool_errors
def explain_failures(
    workflow_spec_json: str,
    cases_json: str,
    max_items: int = 25,
) -> dict[str, Any]:
    """Evaluate supplied cases and group failed checks by criterion and severity."""
    spec = _parse_and_validate_spec(workflow_spec_json)
    cases = parse_json_text(cases_json, "cases_json")
    report = evaluate_suite(spec, cases)
    return explain_report_failures(report, max_items=max_items)


@mcp.tool()
@_map_input_errors_to_tool_errors
def generate_release_report(workflow_spec_json: str, cases_json: str) -> dict[str, Any]:
    """Evaluate the supplied cases and apply release thresholds in one server-side operation."""
    spec = _parse_and_validate_spec(workflow_spec_json)
    cases = parse_json_text(cases_json, "cases_json")
    report = evaluate_suite(spec, cases)
    release = create_release_report(spec, report)
    failed_case_ids = [item["case_id"] for item in report["case_results"] if not item["passed"]]
    return {
        "evaluation_summary": report["summary"],
        "release_report": release,
        "failed_case_count": len(failed_case_ids),
        "failed_case_ids_preview": failed_case_ids[:20],
        "failed_case_ids_omitted_count": max(0, len(failed_case_ids) - 20),
    }


def main() -> None:
    # stdio is the safest default for a locally launched MCP server.
    mcp.run()


if __name__ == "__main__":
    main()
