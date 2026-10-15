from __future__ import annotations

from ai_workflow_assurance_mcp import core
from ai_workflow_assurance_mcp.core_comparison import compare_reports, explain_report_failures
from ai_workflow_assurance_mcp.core_evaluation import evaluate_suite
from ai_workflow_assurance_mcp.core_release import create_release_report
from ai_workflow_assurance_mcp.core_support import AssuranceInputError, parse_json_text, stable_json_digest
from ai_workflow_assurance_mcp.core_validation import validate_cases, validate_spec


def test_compatibility_facade_exports_every_declared_name() -> None:
    assert core.__all__
    assert all(hasattr(core, name) for name in core.__all__)


def test_stable_core_entry_points_reexport_the_implementation_functions() -> None:
    expected = {
        "AssuranceInputError": AssuranceInputError,
        "parse_json_text": parse_json_text,
        "stable_json_digest": stable_json_digest,
        "validate_cases": validate_cases,
        "validate_spec": validate_spec,
        "evaluate_suite": evaluate_suite,
        "compare_reports": compare_reports,
        "explain_report_failures": explain_report_failures,
        "create_release_report": create_release_report,
    }

    assert set(expected).issubset(core.__all__)
    for name, implementation in expected.items():
        assert getattr(core, name) is implementation, name
