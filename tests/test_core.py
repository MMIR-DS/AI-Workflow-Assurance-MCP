from __future__ import annotations

import json
import unittest

from ai_workflow_assurance_mcp.core import (
    SCHEMA_VERSION,
    AssuranceInputError,
    compare_reports,
    create_release_report,
    evaluate_suite,
    explain_report_failures,
    parse_json_text,
    stable_json_digest,
    summarize_thresholds,
    summarize_workflow_metadata,
    validate_spec,
)

SPEC = {
    "id": "invoice-match",
    "name": "Invoice matching workflow",
    "version": "1.0.0",
    "criteria": [
        {
            "id": "decision_matches",
            "operator": "equals",
            "actual_path": "decision",
            "expected_path": "decision",
            "severity": "high",
        },
        {
            "id": "review_flag_matches",
            "operator": "equals",
            "actual_path": "requires_human_review",
            "expected_path": "requires_human_review",
            "severity": "critical",
        },
        {
            "id": "amount_variance",
            "operator": "approx",
            "actual_path": "amount_variance",
            "expected_path": "amount_variance",
            "tolerance": 0.01,
            "severity": "high",
        },
    ],
    "thresholds": {
        "min_pass_rate": 0.9,
        "max_critical_failures": 0,
        "max_review_rate": 0.5,
        "max_avg_cost_usd": 0.1,
        "max_avg_latency_ms": 2000,
    },
}

BASE_CASES = [
    {
        "case_id": "exact-match",
        "expected": {"decision": "approve", "requires_human_review": False, "amount_variance": 0.0},
        "actual": {"decision": "approve", "requires_human_review": False, "amount_variance": 0.0},
        "human_review_observed": False,
        "cost_usd": 0.03,
        "latency_ms": 1000,
    },
    {
        "case_id": "amount-mismatch",
        "expected": {"decision": "review", "requires_human_review": True, "amount_variance": 25.0},
        "actual": {"decision": "approve", "requires_human_review": False, "amount_variance": 25.0},
        "human_review_observed": False,
        "cost_usd": 0.04,
        "latency_ms": 1200,
    },
]


class WorkflowAssuranceTests(unittest.TestCase):
    def test_valid_spec(self):
        self.assertEqual(validate_spec(SPEC), [])

    def test_rejects_unsafe_paths_and_unknown_operators(self):
        bad = json.loads(json.dumps(SPEC))
        bad["criteria"][0]["actual_path"] = "__class__.__mro__"
        bad["criteria"][1]["operator"] = "execute_python"
        errors = validate_spec(bad)
        self.assertTrue(any("actual_path" in error for error in errors))
        self.assertTrue(any("operator" in error for error in errors))

    def test_evaluation_counts_critical_failure(self):
        report = evaluate_suite(SPEC, BASE_CASES)
        self.assertEqual(report["summary"]["total_cases"], 2)
        self.assertEqual(report["summary"]["passed_cases"], 1)
        self.assertEqual(report["summary"]["critical_failures"], 1)
        self.assertEqual(report["summary"]["pass_rate"], 0.5)

    def test_release_is_no_go_when_critical_failures_exist(self):
        report = evaluate_suite(SPEC, BASE_CASES)
        decision = create_release_report(SPEC, report)
        self.assertEqual(decision["decision"], "NO_GO")
        self.assertIn("critical_failures", decision["blocking_checks"])

    def test_review_threshold_is_not_evaluable_without_full_coverage(self):
        cases = [{"case_id": "no-review-data", "expected": {"x": 1}, "actual": {"x": 1}, "cost_usd": 0.01, "latency_ms": 10}]
        spec = {
            "id": "simple-flow", "name": "Simple flow", "version": "1",
            "criteria": [{"id": "x_match", "operator": "equals", "actual_path": "x", "expected_path": "x"}],
            "thresholds": {"min_pass_rate": 1.0, "max_critical_failures": 0, "max_review_rate": 0.2},
        }
        report = evaluate_suite(spec, cases)
        decision = create_release_report(spec, report)
        self.assertEqual(decision["decision"], "HOLD")
        self.assertEqual(next(c for c in decision["checks"] if c["metric"] == "review_rate")["status"], "NOT_EVALUABLE")

    def test_compare_reports_flags_improvement(self):
        baseline = evaluate_suite(SPEC, BASE_CASES)
        candidate_cases = json.loads(json.dumps(BASE_CASES))
        candidate_cases[1]["actual"] = json.loads(json.dumps(candidate_cases[1]["expected"]))
        candidate_cases[1]["human_review_observed"] = True
        candidate = evaluate_suite(SPEC, candidate_cases)
        comparison = compare_reports(baseline, candidate)
        self.assertEqual(comparison["overall_trend"], "IMPROVED_WITH_TRADEOFF")
        self.assertEqual(comparison["metrics"]["pass_rate"]["comparison"], "improved")

    def test_explains_failures_critical_first(self):
        report = evaluate_suite(SPEC, BASE_CASES)
        result = explain_report_failures(report, max_items=1)
        self.assertEqual(result["failures_returned"], 1)
        self.assertEqual(result["failures"][0]["severity"], "critical")
        self.assertTrue(result["truncated"])

    def test_cannot_compare_different_workflows(self):
        report = evaluate_suite(SPEC, BASE_CASES)
        other = json.loads(json.dumps(report))
        other["workflow"]["id"] = "different-workflow"
        with self.assertRaises(AssuranceInputError):
            compare_reports(report, other)

    def test_cannot_compare_different_case_sets(self):
        baseline = evaluate_suite(SPEC, BASE_CASES)
        changed = json.loads(json.dumps(BASE_CASES))
        changed[1]["case_id"] = "new-case-id"
        candidate = evaluate_suite(SPEC, changed)
        with self.assertRaises(AssuranceInputError):
            compare_reports(baseline, candidate)

    def test_invalid_cases_are_rejected(self):
        with self.assertRaises(AssuranceInputError):
            evaluate_suite(SPEC, [{"case_id": "duplicate", "expected": {}, "actual": {}}, {"case_id": "duplicate", "expected": {}, "actual": {}}])

    def test_nonstandard_nan_token_is_rejected(self):
        with self.assertRaises(AssuranceInputError):
            parse_json_text('{"value": NaN}', "input")

    def test_unhashable_operator_does_not_crash_validation(self):
        bad = json.loads(json.dumps(SPEC))
        bad["criteria"][0]["operator"] = ["equals"]
        self.assertTrue(validate_spec(bad))

    def test_large_values_are_bounded_in_reports(self):
        spec = {
            "id": "text-flow", "name": "Text flow", "version": "1",
            "criteria": [{"id": "text_match", "operator": "equals", "actual_path": "text", "expected_path": "text"}],
            "thresholds": {"min_pass_rate": 1.0, "max_critical_failures": 0},
        }
        cases = [{"case_id": "long-text", "expected": {"text": "x" * 3000}, "actual": {"text": "y" * 3000}}]
        report = evaluate_suite(spec, cases)
        actual_value = report["case_results"][0]["checks"][0]["actual_value"]
        self.assertTrue(actual_value["_truncated"])
        self.assertLessEqual(len(actual_value["preview"]), 984)


    def test_nested_equality_does_not_treat_bool_as_integer(self):
        spec = {
            "id": "nested-type", "name": "Nested types", "version": "1",
            "criteria": [{"id": "payload_matches", "operator": "equals", "actual_path": "payload", "expected_path": "payload"}],
            "thresholds": {"min_pass_rate": 1.0, "max_critical_failures": 0},
        }
        report = evaluate_suite(spec, [{"case_id": "typed", "expected": {"payload": {"values": [1]}}, "actual": {"payload": {"values": [True]}}}])
        self.assertFalse(report["case_results"][0]["passed"])

    def test_contains_does_not_treat_bool_as_integer(self):
        spec = {
            "id": "contains-type", "name": "Contains type", "version": "1",
            "criteria": [{"id": "value_allowed", "operator": "contains", "actual_path": "values", "expected_value": 1}],
            "thresholds": {"min_pass_rate": 1.0, "max_critical_failures": 0},
        }
        report = evaluate_suite(spec, [{"case_id": "typed", "expected": {}, "actual": {"values": [True]}}])
        self.assertFalse(report["case_results"][0]["passed"])

    def test_extreme_json_numbers_become_input_errors(self):
        with self.assertRaises(AssuranceInputError):
            parse_json_text('{"value": ' + "9" * 5000 + '}', "input")
        with self.assertRaises(AssuranceInputError):
            parse_json_text('{"value": ' + "9" * 400 + '}', "input")
        with self.assertRaises(AssuranceInputError):
            parse_json_text('{"value": 1e999}', "input")

    def test_zero_minimum_pass_rate_is_rejected(self):
        spec = json.loads(json.dumps(SPEC))
        spec["thresholds"]["min_pass_rate"] = 0
        self.assertTrue(any("min_pass_rate" in error for error in validate_spec(spec)))

    def test_review_rate_requires_explicit_observation(self):
        spec = {
            "id": "review-observation", "name": "Review observation", "version": "1",
            "criteria": [{"id": "review_flag", "operator": "is_true", "actual_path": "requires_human_review", "severity": "high"}],
            "thresholds": {"min_pass_rate": 1.0, "max_critical_failures": 0, "max_review_rate": 0.5},
        }
        report = evaluate_suite(spec, [{"case_id": "no-observation", "expected": {}, "actual": {"requires_human_review": True}}])
        self.assertEqual(report["summary"]["review_observation_coverage"], 0.0)
        self.assertIsNone(report["summary"]["review_rate"])
        release = create_release_report(spec, report)
        self.assertEqual(release["decision"], "HOLD")

    def test_expected_labels_cannot_change_between_compared_runs(self):
        baseline = evaluate_suite(SPEC, BASE_CASES)
        candidate_cases = json.loads(json.dumps(BASE_CASES))
        candidate_cases[0]["expected"]["decision"] = "reject"
        candidate = evaluate_suite(SPEC, candidate_cases)
        with self.assertRaisesRegex(AssuranceInputError, "expected labels changed"):
            compare_reports(baseline, candidate)

    def test_case_level_regression_is_not_hidden_by_equal_pass_rate(self):
        spec = {
            "id": "case-regression", "name": "Case regression", "version": "1",
            "criteria": [{"id": "match", "operator": "equals", "actual_path": "decision", "expected_path": "decision"}],
            "thresholds": {"min_pass_rate": 0.5, "max_critical_failures": 0},
        }
        baseline_cases = [
            {"case_id": "a", "expected": {"decision": "ok"}, "actual": {"decision": "bad"}},
            {"case_id": "b", "expected": {"decision": "ok"}, "actual": {"decision": "ok"}},
        ]
        candidate_cases = [
            {"case_id": "a", "expected": {"decision": "ok"}, "actual": {"decision": "ok"}},
            {"case_id": "b", "expected": {"decision": "ok"}, "actual": {"decision": "bad"}},
        ]
        comparison = compare_reports(evaluate_suite(spec, baseline_cases), evaluate_suite(spec, candidate_cases))
        self.assertEqual(comparison["overall_trend"], "MIXED_CASE_CHANGES")
        self.assertEqual(comparison["regressed_case_ids"], ["b"])
        self.assertEqual(comparison["improved_case_ids"], ["a"])

    def test_critical_regression_takes_precedence_over_pass_rate_improvement(self):
        spec = {
            "id": "critical-regression", "name": "Critical regression", "version": "1",
            "criteria": [
                {"id": "decision", "operator": "equals", "actual_path": "decision", "expected_path": "decision", "severity": "high"},
                {"id": "safety", "operator": "is_true", "actual_path": "safe", "severity": "critical"},
            ],
            "thresholds": {"min_pass_rate": 0.5, "max_critical_failures": 10},
        }
        baseline_cases = [
            {"case_id": "a", "expected": {"decision": "ok"}, "actual": {"decision": "bad", "safe": True}},
            {"case_id": "b", "expected": {"decision": "ok"}, "actual": {"decision": "bad", "safe": True}},
            {"case_id": "c", "expected": {"decision": "ok"}, "actual": {"decision": "ok", "safe": True}},
            {"case_id": "d", "expected": {"decision": "ok"}, "actual": {"decision": "ok", "safe": True}},
        ]
        candidate_cases = json.loads(json.dumps(baseline_cases))
        candidate_cases[0]["actual"]["decision"] = "ok"
        candidate_cases[1]["actual"]["decision"] = "ok"
        candidate_cases[2]["actual"]["safe"] = False
        comparison = compare_reports(evaluate_suite(spec, baseline_cases), evaluate_suite(spec, candidate_cases))
        self.assertGreater(comparison["metrics"]["pass_rate"]["delta"], 0)
        self.assertEqual(comparison["overall_trend"], "REGRESSED_CRITICAL_FAILURES")

    def test_cost_threshold_compares_unrounded_values_and_max_case(self):
        spec = {
            "id": "cost-latency", "name": "Cost and latency", "version": "1",
            "criteria": [{"id": "x", "operator": "equals", "actual_path": "x", "expected_path": "x"}],
            "thresholds": {"min_pass_rate": 1.0, "max_critical_failures": 0, "max_avg_cost_usd": 0.1, "max_case_latency_ms": 2000},
        }
        cases = [{"case_id": f"normal-{i}", "expected": {"x": 1}, "actual": {"x": 1}, "cost_usd": 0.1, "latency_ms": 100} for i in range(99)]
        cases.append({"case_id": "outlier", "expected": {"x": 1}, "actual": {"x": 1}, "cost_usd": 0.1000004, "latency_ms": 100000})
        report = evaluate_suite(spec, cases)
        self.assertGreater(report["summary"]["avg_cost_usd_per_observed_case"], 0.1)
        release = create_release_report(spec, report)
        self.assertEqual(release["decision"], "NO_GO")
        self.assertIn("avg_cost_usd_per_case", release["blocking_checks"])
        self.assertIn("max_case_latency_ms", release["blocking_checks"])

 
    def test_release_rejects_spec_drift_from_evaluation_report(self):
        report = evaluate_suite(SPEC, BASE_CASES)
        changed_spec = json.loads(json.dumps(SPEC))
        changed_spec["thresholds"]["min_pass_rate"] = 0.1
        with self.assertRaisesRegex(AssuranceInputError, "does not match the specification"):
            create_release_report(changed_spec, report)

    def test_forged_summary_inconsistent_with_case_results_is_rejected(self):
        report = evaluate_suite(SPEC, BASE_CASES)
        forged = json.loads(json.dumps(report))
        forged["summary"]["pass_rate"] = 1.0
        with self.assertRaisesRegex(AssuranceInputError, "does not match case_results"):
            create_release_report(SPEC, forged)

    def test_report_contains_reproducibility_digests(self):
        report = evaluate_suite(SPEC, BASE_CASES)
        self.assertEqual(len(report["audit"]["spec_sha256"]), 64)
        self.assertEqual(len(report["audit"]["criteria_sha256"]), 64)
        self.assertEqual(len(report["audit"]["thresholds_sha256"]), 64)
        self.assertEqual(len(report["audit"]["cases_sha256"]), 64)
        self.assertEqual(len(report["case_results"][0]["expected_sha256"]), 64)


    def test_conflicting_review_observation_aliases_are_rejected(self):
        cases = [{
            "case_id": "conflicting-review",
            "expected": {"x": 1},
            "actual": {"x": 1, "requires_human_review": True},
            "human_review_observed": False,
            "human_review_required": True,
        }]
        spec = {
            "id": "review-conflict", "name": "Review conflict", "version": "1",
            "criteria": [{"id": "x", "operator": "equals", "actual_path": "x", "expected_path": "x"}],
            "thresholds": {"min_pass_rate": 1.0, "max_critical_failures": 0},
        }
        with self.assertRaisesRegex(AssuranceInputError, "conflicts with legacy"):
            evaluate_suite(spec, cases)


    def test_lone_surrogate_can_be_fingerprinted_and_evaluated(self):
        self.assertEqual(len(stable_json_digest({"value": "\ud800"})), 64)
        spec = {
            "id": "surrogate-flow", "name": "Surrogate flow", "version": "1",
            "criteria": [{"id": "value_matches", "operator": "equals", "actual_path": "value", "expected_path": "value"}],
            "thresholds": {"min_pass_rate": 1.0, "max_critical_failures": 0},
        }
        report = evaluate_suite(spec, [{"case_id": "surrogate", "expected": {"value": "\ud800"}, "actual": {"value": "\ud800"}}])
        self.assertTrue(report["case_results"][0]["passed"])
        self.assertIn("\\ud800", json.dumps(report, ensure_ascii=True))

    def test_json_nesting_depth_is_limited_for_text_and_python_inputs(self):
        deeply_nested = "[" * 70 + "0" + "]" * 70
        with self.assertRaisesRegex(AssuranceInputError, "nesting depth"):
            parse_json_text(deeply_nested, "deep")
        # The documented cap is 64 containers. 64 is accepted; 65 is rejected.
        acceptable = "[" * 64 + "0" + "]" * 64
        self.assertEqual(parse_json_text(acceptable, "depth-ok"), json.loads(acceptable))
        over_limit = "[" * 65 + "0" + "]" * 65
        with self.assertRaisesRegex(AssuranceInputError, "nesting depth"):
            parse_json_text(over_limit, "depth-over")
        spec = {
            "id": "deep-flow", "name": "Deep flow", "version": "1",
            "criteria": [{"id": "value_matches", "operator": "equals", "actual_path": "value", "expected_path": "value"}],
            "thresholds": {"min_pass_rate": 1.0, "max_critical_failures": 0},
        }
        nested: object = 1
        for _ in range(70):
            nested = [nested]
        with self.assertRaisesRegex(AssuranceInputError, "Invalid cases"):
            evaluate_suite(spec, [{"case_id": "deep", "expected": {"value": nested}, "actual": {"value": nested}}])

    def test_digest_normalizes_integral_float_to_equal_integer(self):
        self.assertEqual(stable_json_digest({"amount": 0}), stable_json_digest({"amount": 0.0}))
        self.assertEqual(stable_json_digest({"amount": [1, 2.0]}), stable_json_digest({"amount": [1.0, 2]}))
        with self.assertRaises(AssuranceInputError):
            stable_json_digest({"amount": float("nan")})
        with self.assertRaises(AssuranceInputError):
            stable_json_digest({"amount": float("inf")})

    def test_compare_reports_accepts_numerically_equal_expected_labels(self):
        spec = {
            "id": "numeric-labels", "name": "Numeric labels", "version": "1",
            "criteria": [{"id": "amount_matches", "operator": "equals", "actual_path": "amount", "expected_path": "amount"}],
            "thresholds": {"min_pass_rate": 1.0, "max_critical_failures": 0},
        }
        baseline = evaluate_suite(spec, [{"case_id": "a", "expected": {"amount": 0.0}, "actual": {"amount": 0}}])
        candidate = evaluate_suite(spec, [{"case_id": "a", "expected": {"amount": 0}, "actual": {"amount": 0.0}}])
        self.assertFalse(compare_reports(baseline, candidate)["thresholds_changed"])

    def test_threshold_preview_omits_unknown_and_unbounded_values(self):
        preview = summarize_thresholds({
            "min_pass_rate": 0.9,
            "max_critical_failures": 0,
            "unknown": "x" * 1_000_000,
            "max_review_rate": {"nested": "bad"},
        })
        self.assertEqual(preview, {"min_pass_rate": 0.9, "max_critical_failures": 0})


    def test_workflow_metadata_preview_is_bounded(self):
        preview = summarize_workflow_metadata({"id": "x" * 1_000_000, "name": "Test", "version": 7})
        self.assertEqual(len(preview["id"]), 160)
        self.assertEqual(preview["name"], "Test")
        self.assertIsNone(preview["version"])

    def test_package_version_matches_project_metadata(self):
        import re
        from pathlib import Path

        from ai_workflow_assurance_mcp import __version__
        pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', pyproject)
        self.assertIsNotNone(match)
        self.assertEqual(__version__, match.group(1))



    def test_release_pass_rate_threshold_is_inclusive(self):
        spec = {
            "id": "inclusive-threshold", "name": "Inclusive threshold", "version": "1",
            "criteria": [{"id": "match", "operator": "equals", "actual_path": "x", "expected_path": "x"}],
            "thresholds": {"min_pass_rate": 0.5, "max_critical_failures": 0},
        }
        cases = [
            {"case_id": "pass", "expected": {"x": 1}, "actual": {"x": 1}},
            {"case_id": "fail", "expected": {"x": 1}, "actual": {"x": 0}},
        ]
        release = create_release_report(spec, evaluate_suite(spec, cases))
        self.assertEqual(release["decision"], "GO")
        check = next(item for item in release["checks"] if item["metric"] == "pass_rate")
        self.assertEqual(check["status"], "PASS")

    def test_high_failure_cap_can_block_release(self):
        spec = {
            "id": "high-cap", "name": "High failure cap", "version": "1",
            "criteria": [{"id": "decision_matches", "operator": "equals", "actual_path": "decision", "expected_path": "decision", "severity": "high"}],
            "thresholds": {"min_pass_rate": 0.5, "max_critical_failures": 0, "max_high_failures": 0},
        }
        cases = [{"case_id": "a", "expected": {"decision": "approve"}, "actual": {"decision": "reject"}}]
        release = create_release_report(spec, evaluate_suite(spec, cases))
        self.assertEqual(release["decision"], "NO_GO")
        self.assertIn("high_failures", release["blocking_checks"])

    def test_failure_group_case_ids_are_bounded(self):
        spec = {
            "id": "group-cap", "name": "Group cap", "version": "1",
            "criteria": [{"id": "decision_matches", "operator": "equals", "actual_path": "decision", "expected_path": "decision", "severity": "high"}],
            "thresholds": {"min_pass_rate": 0.5, "max_critical_failures": 0},
        }
        cases = [{"case_id": f"case-{index}", "expected": {"decision": "approve"}, "actual": {"decision": "reject"}} for index in range(40)]
        failure_report = explain_report_failures(evaluate_suite(spec, cases), max_items=100)
        group = failure_report["failure_groups"][0]
        self.assertEqual(len(group["case_ids"]), 20)
        self.assertEqual(group["case_ids_omitted_count"], 20)
        self.assertEqual(group["failure_count"], 40)

    def test_validation_error_output_is_bounded(self):
        spec = json.loads(json.dumps(SPEC))
        spec["thresholds"].update({f"unknown_{index}_" + "x" * 350: True for index in range(150)})
        errors = validate_spec(spec)
        self.assertLessEqual(len(errors), 101)
        self.assertTrue(all(len(message) <= 300 for message in errors))
        self.assertTrue(any("Additional validation errors omitted" in message for message in errors))


    def test_paths_reject_more_than_maximum_components(self):
        from ai_workflow_assurance_mcp.core import MAX_PATH_PARTS

        spec = json.loads(json.dumps(SPEC))
        spec["criteria"][0]["actual_path"] = ".".join(["x"] * (MAX_PATH_PARTS + 1))
        self.assertTrue(any("actual_path" in error for error in validate_spec(spec)))

    def test_repeated_evaluation_has_stable_decision_relevant_results(self):
        first = evaluate_suite(SPEC, BASE_CASES)
        second = evaluate_suite(SPEC, BASE_CASES)
        self.assertEqual(first["summary"], second["summary"])
        self.assertEqual(first["case_results"], second["case_results"])
        self.assertNotEqual(first["run_id"], second["run_id"])
        self.assertIn("executed_at", first)
        self.assertIn("executed_at", second)

    def test_unknown_threshold_summary_names_unsupported_keys(self):
        from ai_workflow_assurance_mcp.core import summarize_unknown_thresholds

        self.assertEqual(summarize_unknown_thresholds({"min_pass_rate": 0.9, "max_custom_metric": 5}), ["max_custom_metric"])



class NotEvaluableStatusTests(unittest.TestCase):
    def test_unobserved_check_is_not_counted_as_a_definite_failure(self):
        case = {
            "case_id": "missing-decision-evidence",
            "expected": {"decision": "approve", "requires_human_review": False, "amount_variance": 0.0},
            "actual": {"decision": None, "requires_human_review": False, "amount_variance": 0.0},
            "unobserved_checks": ["decision_matches"],
            "human_review_observed": False,
            "cost_usd": 0.01,
            "latency_ms": 100,
        }

        report = evaluate_suite(SPEC, [case])
        result = report["case_results"][0]
        decision = create_release_report(SPEC, report)

        self.assertFalse(result["passed"])
        self.assertEqual(result["status"], "NOT_EVALUABLE")
        check = next(item for item in result["checks"] if item["criterion_id"] == "decision_matches")
        self.assertEqual(check["status"], "NOT_EVALUABLE")
        self.assertFalse(check["passed"])
        self.assertEqual(report["summary"]["failed_checks"], 0)
        self.assertEqual(report["summary"]["not_evaluable_checks"], 1)
        self.assertEqual(report["summary"]["critical_failures"], 0)
        self.assertEqual(decision["decision"], "HOLD")

    def test_observed_critical_failure_still_produces_no_go_with_unknown_check(self):
        case = {
            "case_id": "known-failure-plus-unknown",
            "expected": {"decision": "approve", "requires_human_review": False, "amount_variance": 0.0},
            "actual": {"decision": None, "requires_human_review": True, "amount_variance": 0.0},
            "unobserved_checks": ["decision_matches"],
            "human_review_observed": False,
            "cost_usd": 0.01,
            "latency_ms": 100,
        }

        report = evaluate_suite(SPEC, [case])
        decision = create_release_report(SPEC, report)

        self.assertEqual(report["summary"]["failed_checks"], 1)
        self.assertEqual(report["summary"]["not_evaluable_checks"], 1)
        self.assertEqual(report["summary"]["critical_failures"], 1)
        self.assertEqual(decision["decision"], "NO_GO")

    def test_rejects_unknown_unobserved_criterion_id(self):
        case = {
            "case_id": "bad-unobserved-id",
            "expected": {"decision": "approve", "requires_human_review": False, "amount_variance": 0.0},
            "actual": {"decision": "approve", "requires_human_review": False, "amount_variance": 0.0},
            "unobserved_checks": ["not-a-real-check"],
        }
        with self.assertRaisesRegex(AssuranceInputError, "unknown criterion id"):
            evaluate_suite(SPEC, [case])


class ReportSchemaVersionTests(unittest.TestCase):
    def test_explicit_evaluation_status_uses_report_schema_04(self):
        report = evaluate_suite(SPEC, BASE_CASES)
        self.assertEqual(SCHEMA_VERSION, "0.4")
        self.assertEqual(report["schema_version"], SCHEMA_VERSION)
        self.assertIn("status", report["case_results"][0]["checks"][0])
        self.assertIn("not_evaluable_checks", report["summary"])


if __name__ == "__main__":
    unittest.main()
