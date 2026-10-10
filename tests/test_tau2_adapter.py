from __future__ import annotations

import json
from pathlib import Path

from scripts.adapt_tau2_results import evaluate_trace
from scripts.verify_tau2_mutations import MUTATION_EXPECTATIONS, run_mutation_checks

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "tau2_task0_trace_minimal.json"
SPEC_PATH = ROOT / "examples" / "tau2_retail_workflow.json"


def _load_inputs() -> tuple[dict, dict]:
    return (
        json.loads(FIXTURE.read_text(encoding="utf-8")),
        json.loads(SPEC_PATH.read_text(encoding="utf-8")),
    )


def test_task0_release_uses_order_catalog_and_action_return_payloads() -> None:
    results, spec = _load_inputs()
    case, metadata, report, release = evaluate_trace(results, spec)
    assert release["decision"] == "GO"
    assert report["summary"]["pass_rate"] == 1.0
    assert report["summary"]["total_checks"] == 16
    assert case["actual"]["price_difference_reconciles"] is True
    assert case["actual"]["no_unrelated_state_mutation"] is True
    assert case["actual"]["selected_variants_match_product_and_request"] is True
    assert metadata["computed_price_difference_usd"] == "-16.63"
    assert metadata["independence_scope"]["release_decision_uses_tau2_reward"] is False
    assert metadata["independence_scope"]["release_decision_uses_tau2_db_match"] is False
    assert metadata["independence_scope"]["release_decision_uses_tau2_action_checks"] is False


def test_release_decision_does_not_depend_on_tau2_reward_oracle_fields() -> None:
    results, spec = _load_inputs()
    results["simulations"][0]["reward_info"] = {
        "reward": 0.0,
        "db_check": {"db_match": False, "db_reward": 0.0},
        "action_checks": [{"action_match": False, "action_reward": 0.0} for _ in range(5)],
    }
    case, metadata, report, release = evaluate_trace(results, spec)
    assert release["decision"] == "GO"
    assert report["summary"]["critical_failures"] == 0
    assert case["actual"]["final_state_matches_expected"] is True
    assert metadata["tau2_oracle_for_comparison_only"]["reward"] == 0.0
    assert metadata["tau2_oracle_for_comparison_only"]["db_match"] is False
    assert metadata["tau2_oracle_for_comparison_only"]["action_checks_all_match"] is False


def test_saved_raw_trace_mutations_fail_closed_without_changing_tau2_oracle() -> None:
    results, spec = _load_inputs()
    outcomes = run_mutation_checks(results, spec)
    assert outcomes["summary"]["baseline_decision"] == "GO"
    assert outcomes["summary"]["mutation_count"] == len(MUTATION_EXPECTATIONS) == 6
    assert outcomes["summary"]["all_mutations_no_go"] is True
    assert outcomes["summary"]["tau2_oracle_unchanged_for_all_mutations"] is True
    for name, expected_field in MUTATION_EXPECTATIONS.items():
        item = outcomes["mutations"][name]
        assert item["release"]["decision"] == "NO_GO"
        assert item["case"]["actual"][expected_field] is False
        assert item["tau2_oracle_unchanged"] is True


def test_mutation_report_distinguishes_state_catalog_price_and_payment_failures() -> None:
    results, spec = _load_inputs()
    outcomes = run_mutation_checks(results, spec)
    assert outcomes["mutations"]["unrelated_order_state_mutated"]["case"]["actual"]["no_unrelated_state_mutation"] is False
    assert outcomes["mutations"]["price_difference_mismatch"]["case"]["actual"]["price_difference_reconciles"] is False
    assert outcomes["mutations"]["selected_variant_unavailable"]["case"]["actual"]["selected_variants_match_product_and_request"] is False
    assert outcomes["mutations"]["wrong_product_family"]["case"]["actual"]["selected_variants_match_product_and_request"] is False
    assert outcomes["mutations"]["payment_method_mismatch"]["case"]["actual"]["payment_policy_respected"] is False


def test_missing_tool_evidence_fails_closed() -> None:
    results, spec = _load_inputs()
    results["simulations"][0]["messages"] = [
        message for message in results["simulations"][0]["messages"]
        if not (message.get("role") == "tool" and message.get("id") == "keyboard-product-1")
    ]
    case, _, report, release = evaluate_trace(results, spec)
    assert case["actual"]["selected_variants_match_product_and_request"] is False
    assert case["actual"]["price_difference_reconciles"] is False
    assert release["decision"] == "NO_GO"
    assert report["summary"]["critical_failures"] >= 1
