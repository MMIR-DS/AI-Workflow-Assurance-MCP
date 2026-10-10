"""Run focused, deterministic source-code mutation checks against core regression tests.

This is a small mutation smoke test, not a substitute for a full mutation-testing
engine. Each mutant changes one known source expression and must be killed by a
specific regression test. No model calls or external services are used.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CORE_RELATIVE = Path("src/ai_workflow_assurance_mcp/core.py")
TEST_RELATIVE = Path("tests/test_core.py")

MUTANTS: list[dict[str, str]] = [
    {
        "id": "bool_int_equality",
        "description": "Remove strict type equality for boolean comparisons.",
        "source": "return type(left) is type(right) and left == right",
        "replacement": "return left == right",
        "test": "tests/test_core.py::WorkflowAssuranceTests::test_nested_equality_does_not_treat_bool_as_integer",
    },
    {
        "id": "json_depth_boundary",
        "description": "Allow one additional container level beyond the documented JSON depth limit.",
        "source": "if depth >= max_depth:",
        "replacement": "if depth > max_depth:",
        "test": "tests/test_core.py::WorkflowAssuranceTests::test_json_nesting_depth_is_limited_for_text_and_python_inputs",
    },
    {
        "id": "release_threshold_gate",
        "description": "Force threshold checks to fail even when the observed metric meets the limit.",
        "source": "passed = observed >= limit if comparator == \">=\" else observed <= limit",
        "replacement": "passed = False",
        "test": "tests/test_core.py::WorkflowAssuranceTests::test_release_pass_rate_threshold_is_inclusive",
    },
    {
        "id": "report_case_result_integrity",
        "description": "Invert the consistency check between a case result and its individual checks.",
        "source": "if result.get(\"passed\") != expected_case_passed:",
        "replacement": "if result.get(\"passed\") == expected_case_passed:",
        "test": "tests/test_core.py::WorkflowAssuranceTests::test_release_is_no_go_when_critical_failures_exist",
    },
    {
        "id": "expected_label_drift_guard",
        "description": "Disable the guard against changed expected labels in baseline/candidate comparisons.",
        "source": "if changed_expected:",
        "replacement": "if False and changed_expected:",
        "test": "tests/test_core.py::WorkflowAssuranceTests::test_expected_labels_cannot_change_between_compared_runs",
    },
    {
        "id": "critical_regression_precedence",
        "description": "Disable critical-regression precedence in the overall comparison trend.",
        "source": "if after_critical > before_critical:",
        "replacement": "if after_critical < before_critical:",
        "test": "tests/test_core.py::WorkflowAssuranceTests::test_critical_regression_takes_precedence_over_pass_rate_improvement",
    },
    {
        "id": "release_spec_drift_guard",
        "description": "Disable the check that release policy matches the evaluated workflow specification.",
        "source": "if stable_json_digest(spec) != report[\"audit\"][\"spec_sha256\"]:",
        "replacement": "if False and stable_json_digest(spec) != report[\"audit\"][\"spec_sha256\"]:",
        "test": "tests/test_core.py::WorkflowAssuranceTests::test_release_rejects_spec_drift_from_evaluation_report",
    }
]


def _run_test(worktree: Path, test_node: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(worktree / "src") + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", test_node],
        cwd=worktree,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def run_mutation_smoke() -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="awa-mutation-") as temporary:
        worktree = Path(temporary)
        shutil.copytree(ROOT / "src", worktree / "src")
        (worktree / "tests").mkdir()
        shutil.copy2(ROOT / TEST_RELATIVE, worktree / TEST_RELATIVE)

        core_path = worktree / CORE_RELATIVE
        original = core_path.read_text(encoding="utf-8")

        # Establish that each selected regression test passes before mutation.
        baseline_tests = sorted({item["test"] for item in MUTANTS})
        baseline_failures = []
        for test_node in baseline_tests:
            baseline = _run_test(worktree, test_node)
            if baseline.returncode != 0:
                baseline_failures.append(
                    {"test": test_node, "returncode": baseline.returncode, "output": (baseline.stdout + baseline.stderr)[-4000:]}
                )
        if baseline_failures:
            return {
                "passed": False,
                "scope": "focused source-code mutation smoke test; not full mutation testing",
                "mutants_total": len(MUTANTS),
                "mutants_killed": 0,
                "mutants_survived": len(MUTANTS),
                "baseline_passed": False,
                "baseline_failures": baseline_failures,
                "mutants": [],
            }

        for mutant in MUTANTS:
            if original.count(mutant["source"]) != 1:
                results.append({
                    "id": mutant["id"],
                    "killed": False,
                    "status": "INVALID_MUTATION_ANCHOR",
                    "detail": f"Expected exactly one source match; found {original.count(mutant['source'])}.",
                })
                continue

            mutated = original.replace(mutant["source"], mutant["replacement"], 1)
            core_path.write_text(mutated, encoding="utf-8")
            process = _run_test(worktree, mutant["test"])
            killed = process.returncode != 0
            results.append({
                "id": mutant["id"],
                "description": mutant["description"],
                "test": mutant["test"],
                "killed": killed,
                "status": "KILLED" if killed else "SURVIVED",
                "test_returncode": process.returncode,
                "test_output_tail": (process.stdout + process.stderr)[-2500:],
            })
            core_path.write_text(original, encoding="utf-8")

    killed_count = sum(1 for result in results if result.get("killed"))
    return {
        "passed": killed_count == len(MUTANTS) and len(results) == len(MUTANTS),
        "scope": "focused source-code mutation smoke test; not full mutation testing",
        "baseline_passed": True,
        "mutants_total": len(MUTANTS),
        "mutants_killed": killed_count,
        "mutants_survived": len(MUTANTS) - killed_count,
        "mutation_score": killed_count / len(MUTANTS) if MUTANTS else 1.0,
        "model_calls": 0,
        "external_services": 0,
        "mutants": results,
        "limitations": [
            "Only seven hand-selected source mutations are tested.",
            "The mutation score applies only to this small selected set, not to all possible defects.",
            "This smoke test complements but does not replace broader mutation-testing tools and code review.",
        ],
    }


def main() -> int:
    report = run_mutation_smoke()
    print(json.dumps(report, indent=2, ensure_ascii=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
