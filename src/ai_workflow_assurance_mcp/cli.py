"""File-based CLI for repeatable local workflow evaluation outside an LLM context."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ai_workflow_assurance_mcp.core import (
    MAX_JSON_CHARS,
    AssuranceInputError,
    compare_reports,
    create_release_report,
    evaluate_suite,
    explain_report_failures,
    parse_json_text,
    summarize_thresholds,
    summarize_unknown_thresholds,
    summarize_workflow_metadata,
    validate_spec,
)
from ai_workflow_assurance_mcp.evidence_sources import Tau2ManifestFileSource


def _load_json(path: str) -> Any:
    file_path = Path(path)
    try:
        # Refuse obviously oversized files before reading them into memory.
        if file_path.stat().st_size > MAX_JSON_CHARS * 4:
            raise AssuranceInputError(f"Input file '{path}' exceeds the file-size safety limit.")
        text = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise AssuranceInputError(f"Could not read '{path}': {exc}") from exc
    return parse_json_text(text, path)


def _emit(payload: Any, output_path: str | None) -> None:
    serialized = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False)
    # Keep ordinary Unicode readable, but make lone surrogates safe for UTF-8 files/stdout.
    text = serialized.encode("utf-8", errors="backslashreplace").decode("utf-8") + "\n"
    if output_path:
        try:
            Path(output_path).write_text(text, encoding="utf-8")
        except OSError as exc:
            raise AssuranceInputError(f"Could not write '{output_path}': {exc}") from exc
    else:
        sys.stdout.write(text)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ai-workflow-assurance",
        description="Run deterministic workflow acceptance checks from local JSON files.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate-spec", help="validate a workflow specification")
    validate.add_argument("--spec", required=True)
    validate.add_argument("--output")

    evaluate = subparsers.add_parser("evaluate", help="evaluate expected/actual observations")
    evaluate.add_argument("--spec", required=True)
    evaluate.add_argument("--cases", required=True)
    evaluate.add_argument("--summary-only", action="store_true", help="omit per-case details from output")
    evaluate.add_argument("--output")

    compare = subparsers.add_parser("compare", help="compare baseline and candidate observations")
    compare.add_argument("--spec", required=True)
    compare.add_argument("--baseline", required=True)
    compare.add_argument("--candidate", required=True)
    compare.add_argument("--output")

    explain = subparsers.add_parser("explain", help="group failures by criterion and severity")
    explain.add_argument("--spec", required=True)
    explain.add_argument("--cases", required=True)
    explain.add_argument("--max-items", type=int, default=25)
    explain.add_argument("--output")

    release = subparsers.add_parser("release", help="produce a threshold-based release report")
    release.add_argument("--spec", required=True)
    release.add_argument("--cases", required=True)
    release.add_argument("--output")
    release.add_argument("--fail-on-non-go", action="store_true", help="exit 1 for HOLD or NO_GO after emitting the report")

    inspect_evidence = subparsers.add_parser(
        "inspect-evidence",
        help="validate and normalize a tau2 simulator evidence manifest",
    )
    inspect_evidence.add_argument("--manifest", required=True)
    inspect_evidence.add_argument("--output")
    return parser


def main() -> None:
    parser = _parser()
    args = parser.parse_args()
    try:
        if args.command == "inspect-evidence":
            try:
                envelope = Tau2ManifestFileSource(args.manifest).read_evidence()
            except ValueError as exc:
                raise AssuranceInputError(f"Could not inspect evidence manifest: {exc}") from exc
            if args.output and Path(args.output).resolve() == Path(args.manifest).resolve():
                raise AssuranceInputError(
                    "Output path must differ from the source manifest path."
                )
            result = {
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
            _emit(result, args.output)
            return

        if args.command == "validate-spec":
            spec = _load_json(args.spec)
            errors = validate_spec(spec)
            if not isinstance(spec, dict):
                result = {"valid": False, "errors": errors}
            else:
                result = {
                    "valid": not errors,
                    "workflow": summarize_workflow_metadata(spec),
                    "criterion_count": len(spec.get("criteria", [])) if isinstance(spec.get("criteria"), list) else 0,
                    "thresholds": summarize_thresholds(spec.get("thresholds")),
                    "unknown_thresholds": summarize_unknown_thresholds(spec.get("thresholds")),
                    "errors": errors,
                }
            _emit(result, args.output)
            if errors:
                raise SystemExit(2)
            return

        spec = _load_json(args.spec)
        errors = validate_spec(spec)
        if errors:
            raise AssuranceInputError("Invalid workflow specification: " + " ".join(errors))
        if not isinstance(spec, dict):
            raise AssuranceInputError("Workflow specification must be a JSON object.")

        if args.command in {"evaluate", "explain", "release"}:
            cases = _load_json(args.cases)
            report = evaluate_suite(spec, cases)
            if args.command == "evaluate":
                if args.summary_only:
                    report = {key: value for key, value in report.items() if key != "case_results"}
                    report["case_results_omitted"] = True
                result = report
            elif args.command == "explain":
                result = explain_report_failures(report, max_items=args.max_items)
            else:
                result = create_release_report(spec, report)
        elif args.command == "compare":
            baseline_cases = _load_json(args.baseline)
            candidate_cases = _load_json(args.candidate)
            result = compare_reports(evaluate_suite(spec, baseline_cases), evaluate_suite(spec, candidate_cases))
        else:  # Defensive: argparse prevents this branch.
            raise AssuranceInputError(f"Unsupported command: {args.command}")
        _emit(result, args.output)
        if args.command == "release" and args.fail_on_non_go and result["decision"] != "GO":
            raise SystemExit(1)
    except AssuranceInputError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
