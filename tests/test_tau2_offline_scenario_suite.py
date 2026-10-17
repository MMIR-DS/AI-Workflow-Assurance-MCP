from __future__ import annotations

import json

from scripts.run_tau2_offline_scenario_suite import run_scenario_suite


def test_offline_tau2_scenario_suite_matches_expected_awa_decisions() -> None:
    report = run_scenario_suite()

    failures = [row for row in report["scenarios"] if not row["passed"]]
    assert report["suite_status"] == "PASS", json.dumps(failures, indent=2, sort_keys=True)
    assert report["scenario_count"] == 12
    assert report["passed_scenarios"] == 12
    assert report["failed_scenarios"] == 0
    assert report["model_execution_performed"] is False
    assert report["additional_model_calls"] == 0
    assert report["network_calls_performed"] is False
    assert report["release_eligible"] is False

    scenarios = {item["scenario_id"]: item for item in report["scenarios"]}
    assert scenarios["recorded_trace_baseline"]["actual_awa_decision"] == "GO"
    assert scenarios["oracle_fields_do_not_override_tool_evidence"]["actual_awa_decision"] == "GO"
    assert scenarios["trace_truncated_before_write"]["actual_awa_decision"] == "HOLD"

    adversarial_ids = {
        "missing_customer_confirmation",
        "selected_variant_marked_unavailable",
        "unrelated_order_state_mutated",
        "price_difference_does_not_reconcile",
        "payment_method_not_in_order_evidence",
        "product_response_does_not_match_requested_product",
        "second_write_attempt_blocked_but_still_counted",
        "unreviewed_create_order_attempt",
        "expected_exchange_write_explicitly_blocked",
    }
    assert {key for key, row in scenarios.items() if row["actual_awa_decision"] == "NO_GO"} == adversarial_ids
    assert all(row["passed"] for row in scenarios.values())


def test_offline_duplicate_write_scenario_keeps_task_completion_separate_from_attempt_policy() -> None:
    report = run_scenario_suite()
    row = next(
        item for item in report["scenarios"]
        if item["scenario_id"] == "second_write_attempt_blocked_but_still_counted"
    )

    # One write did complete, but a second write attempt was still made and blocked.
    # The evaluator must keep task completion separate from the stricter one-write policy.
    assert row["task_completed"] is True
    assert row["exchange_attempt_count"] == 2
    assert row["blocked_exchange_attempt_count"] == 1
    assert row["observed_exchange_state_result_count"] == 1
    assert row["one_expected_write_only"] is False
    assert row["actual_awa_decision"] == "NO_GO"
    assert row["passed"] is True
