from __future__ import annotations

import unittest
from copy import deepcopy

from ai_workflow_assurance_mcp.core import create_release_report, evaluate_suite
from scripts.run_assurance_mutation_harness import CONTROL_CASE, SPEC, run_harness


class AssuranceMutationHarnessTests(unittest.TestCase):
    def test_control_passes_and_all_seeded_faults_are_detected(self) -> None:
        report = run_harness()
        self.assertTrue(report["control"]["passed"], report)
        self.assertEqual(report["seeded_faults"]["total"], 5)
        self.assertEqual(report["seeded_faults"]["detected"], 5)
        self.assertEqual(report["seeded_faults"]["missed"], 0)
        self.assertEqual(report["seeded_faults"]["detection_rate"], 1.0)
        self.assertEqual(report["false_rejection_count"], 0)

    def test_decision_and_checks_are_reproducible(self) -> None:
        report = run_harness()
        self.assertTrue(report["reproducibility"]["passed"], report)
        self.assertTrue(report["overall_passed"], report)

    def test_report_discloses_scope_and_no_model_calls(self) -> None:
        report = run_harness()
        self.assertEqual(report["model_calls"], 0)
        self.assertIn("not source-code mutation testing", report["scope"])
        self.assertTrue(report["limitations"])

    def test_release_gate_threshold_boundary_is_inclusive(self) -> None:
        spec = deepcopy(SPEC)
        case = deepcopy(CONTROL_CASE)
        case["actual"]["amount"] = 999.0
        spec["thresholds"]["min_pass_rate"] = 0.5
        spec["thresholds"]["max_critical_failures"] = 1

        report = evaluate_suite(spec, [case])
        release = create_release_report(spec, report)
        self.assertEqual(release["decision"], "GO")
        self.assertTrue(all(check["passed"] for check in release["checks"]))

        spec["thresholds"]["max_critical_failures"] = 0
        release = create_release_report(spec, evaluate_suite(spec, [case]))
        self.assertEqual(release["decision"], "NO_GO")
        self.assertIn("critical_failures", release["blocking_checks"])

    def test_missing_required_cost_observations_fail_closed_to_hold(self) -> None:
        spec = deepcopy(SPEC)
        spec["thresholds"]["max_avg_cost_usd"] = 1.0
        report = evaluate_suite(spec, [deepcopy(CONTROL_CASE)])
        release = create_release_report(spec, report)

        self.assertEqual(release["decision"], "HOLD")
        cost_check = next(check for check in release["checks"] if check["metric"] == "avg_cost_usd_per_case")
        self.assertEqual(cost_check["status"], "NOT_EVALUABLE")
        self.assertIn("avg_cost_usd_per_case", release["blocking_checks"])


if __name__ == "__main__":
    unittest.main()
