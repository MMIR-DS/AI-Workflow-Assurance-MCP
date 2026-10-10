from __future__ import annotations

import unittest

from scripts.run_assurance_mutation_harness import run_harness


class AssuranceMutationHarnessTests(unittest.TestCase):
    def test_control_passes_and_all_seeded_faults_are_detected(self) -> None:
        report = run_harness()
        self.assertTrue(report["control"]["passed"], report)
        self.assertEqual(report["seeded_faults"]["total"], 3)
        self.assertEqual(report["seeded_faults"]["detected"], 3)
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


if __name__ == "__main__":
    unittest.main()
