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


def _set_complete_confirmation(results: dict) -> None:
    """Build a synthetic, fully disclosed control from the recorded order/action payloads."""
    messages = results["simulations"][0]["messages"]
    exchange_index = next(
        index for index, message in enumerate(messages)
        if message.get("role") == "assistant"
        and any(
            isinstance(call, dict) and call.get("name") == "exchange_delivered_order_items"
            for call in (message.get("tool_calls") or [])
        )
    )
    call = next(
        call for call in messages[exchange_index].get("tool_calls", [])
        if call.get("name") == "exchange_delivered_order_items"
    )
    args = call.get("arguments") or {}
    old_ids = args["item_ids"]
    new_ids = args["new_item_ids"]
    order_id = args["order_id"]
    payment_id = args["payment_method_id"]
    result = next(
        message for message in messages
        if message.get("role") == "tool" and str(message.get("id")) == str(call.get("id"))
    )
    delta = float(json.loads(result["content"])["exchange_price_difference"])
    pairs = " and ".join(
        f"old item {old_id} for {new_id}" for old_id, new_id in zip(old_ids, new_ids, strict=True)
    )
    if delta < 0:
        price_disclosure = f"a ${abs(delta):,.2f} refund to {payment_id}"
    elif delta > 0:
        price_disclosure = f"an additional charge of ${abs(delta):,.2f} on {payment_id}"
    else:
        price_disclosure = f"$0.00; no price difference for {payment_id}"

    assistant_index = next(
        index for index in range(exchange_index - 1, -1, -1)
        if messages[index].get("role") == "assistant"
        and not messages[index].get("tool_calls")
        and "To confirm:" in str(messages[index].get("content") or "")
    )
    messages[assistant_index]["content"] = (
        f"To confirm: order {order_id}: exchange {pairs}. "
        f"The total price difference is {price_disclosure}. Please confirm."
    )
    user_index = next(
        index for index in range(exchange_index - 1, assistant_index, -1)
        if messages[index].get("role") == "user"
    )
    messages[user_index]["content"] = (
        f"Yes, that's exactly right. Go ahead and use {payment_id} for any price differences."
    )


def test_task0_trace_blocks_when_prewrite_disclosure_is_incomplete() -> None:
    results, spec = _load_inputs()
    case, metadata, report, release = evaluate_trace(results, spec)
    assert release["decision"] == "NO_GO"
    assert report["summary"]["pass_rate"] < 1.0
    assert report["summary"]["total_checks"] == 16
    assert case["actual"]["confirmation_policy_respected"] is False
    assert case["actual"]["price_difference_reconciles"] is True
    assert case["actual"]["no_unrelated_state_mutation"] is True
    assert case["actual"]["selected_variants_match_product_and_request"] is True
    assert metadata["computed_price_difference_usd"] == "-16.63"
    assert metadata["independence_scope"]["release_decision_uses_tau2_reward"] is False
    assert metadata["independence_scope"]["release_decision_uses_tau2_db_match"] is False
    assert metadata["independence_scope"]["release_decision_uses_tau2_action_checks"] is False


def test_confirmation_accepts_affirmative_reply_to_details_disclosed_by_assistant() -> None:
    results, spec = _load_inputs()
    _set_complete_confirmation(results)
    messages = results["simulations"][0]["messages"]
    confirmation = next(
        message for message in messages
        if message.get("role") == "user"
        and "Yes, that's exactly right" in str(message.get("content") or "")
    )
    confirmation["content"] = (
        "Yes, that all sounds correct. Please go ahead and process the exchange "
        "for both items with the ones you found, and use the original payment "
        "method for any differences. Thank you!"
    )

    case, _, report, release = evaluate_trace(results, spec)

    assert case["actual"]["confirmation_policy_respected"] is True
    assert case["actual"]["policy_violation_count"] == 0
    assert report["summary"]["pass_rate"] == 1.0
    assert release["decision"] == "GO"


def test_confirmation_fails_closed_when_assistant_did_not_disclose_all_new_items() -> None:
    results, spec = _load_inputs()
    _set_complete_confirmation(results)
    messages = results["simulations"][0]["messages"]
    assistant_confirmation = next(
        message for message in messages
        if message.get("role") == "assistant"
        and "To confirm:" in str(message.get("content") or "")
    )
    assistant_confirmation["content"] = str(assistant_confirmation["content"]).replace(
        "7706410293", "REDACTED_ITEM_ID"
    )

    case, _, _, release = evaluate_trace(results, spec)

    assert case["actual"]["confirmation_policy_respected"] is False
    assert release["decision"] == "NO_GO"


def test_explicitly_negated_confirmation_fails_closed() -> None:
    results, spec = _load_inputs()
    _set_complete_confirmation(results)
    messages = results["simulations"][0]["messages"]
    confirmation = next(
        message for message in messages
        if message.get("role") == "user"
        and "Yes, that's exactly right" in str(message.get("content") or "")
    )
    confirmation["content"] = "No, don't go ahead. I need to change the selections."

    case, _, _, release = evaluate_trace(results, spec)

    assert case["actual"]["confirmation_policy_respected"] is False
    assert release["decision"] == "NO_GO"


def test_release_decision_does_not_depend_on_tau2_reward_oracle_fields() -> None:
    results, spec = _load_inputs()
    _set_complete_confirmation(results)
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
    assert outcomes["summary"]["mutation_count"] == len(MUTATION_EXPECTATIONS) == 7
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


def test_error_object_is_not_misclassified_as_an_exchange_state_result() -> None:
    results, spec = _load_inputs()
    _set_complete_confirmation(results)
    messages = results["simulations"][0]["messages"]
    exchange_call = next(
        call
        for message in messages
        if message.get("role") == "assistant"
        for call in (message.get("tool_calls") or [])
        if isinstance(call, dict) and call.get("name") == "exchange_delivered_order_items"
    )
    tool_result = next(
        message for message in messages
        if message.get("role") == "tool"
        and str(message.get("id")) == str(exchange_call.get("id"))
    )
    tool_result["content"] = json.dumps({"error": "database unavailable"})

    case, metadata, _, release = evaluate_trace(results, spec)

    assert metadata["exchange_attempt_count"] == 1
    assert metadata["blocked_exchange_attempt_count"] == 0
    assert metadata["observed_exchange_state_result_count"] == 0
    assert metadata["unclassified_exchange_attempt_count"] == 1
    assert metadata["expected_write_observed"] is False
    assert metadata["task_completed"] is False
    assert case["actual"]["one_expected_write_only"] is False
    assert release["decision"] == "NO_GO"


def _independent_db_test_inputs() -> tuple[dict, dict, dict, dict, set[str], bool, bool]:
    results, _ = _load_inputs()
    sim = results["simulations"][0]
    messages = sim["messages"]
    calls = [
        call
        for message in messages
        if message.get("role") == "assistant"
        for call in (message.get("tool_calls") or [])
        if isinstance(call, dict)
    ]
    exchange = next(call for call in calls if call["name"] == "exchange_delivered_order_items")
    responses = {
        str(message.get("id")): message
        for message in messages
        if message.get("role") == "tool" and message.get("id") is not None
    }
    order_read = next(call for call in calls if call["name"] == "get_order_details")
    before = json.loads(responses[order_read["id"]]["content"])
    after = json.loads(responses[exchange["id"]]["content"])
    products = {
        "1656367028": json.loads(responses["keyboard-product-1"]["content"]),
        "4896585277": json.loads(responses["thermostat-product-1"]["content"]),
    }
    payment_ids = {
        item["payment_method_id"]
        for item in before["payment_history"]
        if item.get("transaction_type") == "payment"
    }
    return before, after, exchange["arguments"], products, payment_ids, True, bool(
        results["info"]["git_commit"]
    )


def test_independent_db_snapshot_contract_passes_on_recorded_baseline() -> None:
    from scripts.verify_tau2_independent_db import evaluate_snapshot_evidence

    before, after, args, products, payment_ids, _, source_match = _independent_db_test_inputs()
    report = evaluate_snapshot_evidence(
        recorded_before=before,
        recorded_after=after,
        db_before=before,
        db_after=after,
        args=args,
        products=products,
        valid_payment_method_ids=payment_ids,
        source_commit_matches_trace=source_match,
        write_execution_succeeded=True,
        other_database_entities_unchanged=True,
    )
    assert report["decision"] == "GO"
    assert report["checks"]["pre_state_matches_recorded_order_read"] is True
    assert report["checks"]["independent_db_state_matches_recorded_exchange_response"] is True
    assert report["checks"]["replay_db_payment_profile_and_original_transaction_match"] is True
    assert report["checks"]["database_price_recalculation_matches_post_state"] is True


def test_independent_db_snapshot_contract_rejects_tampered_post_state() -> None:
    from scripts.verify_tau2_independent_db import evaluate_snapshot_evidence

    before, after, args, products, payment_ids, _, source_match = _independent_db_test_inputs()
    tampered_after = json.loads(json.dumps(after))
    tampered_after["address"]["city"] = "Mutation Test City"
    report = evaluate_snapshot_evidence(
        recorded_before=before,
        recorded_after=tampered_after,
        db_before=before,
        db_after=after,
        args=args,
        products=products,
        valid_payment_method_ids=payment_ids,
        source_commit_matches_trace=source_match,
        write_execution_succeeded=True,
        other_database_entities_unchanged=True,
    )
    assert report["decision"] == "NO_GO"
    assert report["checks"]["independent_db_state_matches_recorded_exchange_response"] is False


def test_independent_db_snapshot_contract_fails_closed_on_source_drift() -> None:
    from scripts.verify_tau2_independent_db import evaluate_snapshot_evidence

    before, after, args, products, payment_ids, _, _ = _independent_db_test_inputs()
    report = evaluate_snapshot_evidence(
        recorded_before=before,
        recorded_after=after,
        db_before=before,
        db_after=after,
        args=args,
        products=products,
        valid_payment_method_ids=payment_ids,
        source_commit_matches_trace=False,
        write_execution_succeeded=True,
        other_database_entities_unchanged=True,
    )
    assert report["decision"] == "NO_GO"
    assert report["checks"]["source_code_commit_matches_trace"] is False


def test_independent_db_snapshot_contract_rejects_unrelated_entity_mutation() -> None:
    from scripts.verify_tau2_independent_db import evaluate_snapshot_evidence

    before, after, args, products, payment_ids, _, source_match = _independent_db_test_inputs()
    report = evaluate_snapshot_evidence(
        recorded_before=before,
        recorded_after=after,
        db_before=before,
        db_after=after,
        args=args,
        products=products,
        valid_payment_method_ids=payment_ids,
        source_commit_matches_trace=source_match,
        write_execution_succeeded=True,
        other_database_entities_unchanged=False,
    )
    assert report["decision"] == "NO_GO"
    assert report["checks"]["no_other_database_entities_mutated"] is False


def test_independent_db_snapshot_contract_rejects_unknown_profile_payment_method() -> None:
    from scripts.verify_tau2_independent_db import evaluate_snapshot_evidence

    before, after, args, products, _, _, source_match = _independent_db_test_inputs()
    report = evaluate_snapshot_evidence(
        recorded_before=before,
        recorded_after=after,
        db_before=before,
        db_after=after,
        args=args,
        products=products,
        valid_payment_method_ids={"some_other_payment_method"},
        source_commit_matches_trace=source_match,
        write_execution_succeeded=True,
        other_database_entities_unchanged=True,
    )
    assert report["decision"] == "NO_GO"
    assert report["checks"]["replay_db_payment_profile_and_original_transaction_match"] is False

def test_full_database_invariant_allows_only_target_order_change() -> None:
    from scripts.verify_tau2_independent_db import other_database_entities_unchanged

    before = {
        "orders": {
            "#W1": {"status": "delivered"},
            "#W2": {"status": "pending"},
        },
        "products": {"P1": {"price": 10}},
        "users": {"U1": {"payment_method": "C1"}},
    }
    after = {
        "orders": {
            "#W1": {"status": "exchange requested"},
            "#W2": {"status": "pending"},
        },
        "products": {"P1": {"price": 10}},
        "users": {"U1": {"payment_method": "C1"}},
    }
    assert other_database_entities_unchanged(before, after, "#W1") is True


def test_full_database_invariant_rejects_mutated_product_or_other_order() -> None:
    from scripts.verify_tau2_independent_db import other_database_entities_unchanged

    before = {
        "orders": {
            "#W1": {"status": "delivered"},
            "#W2": {"status": "pending"},
        },
        "products": {"P1": {"price": 10}},
        "users": {"U1": {"payment_method": "C1"}},
    }
    mutated_product = json.loads(json.dumps(before))
    mutated_product["products"]["P1"]["price"] = 11
    mutated_order = json.loads(json.dumps(before))
    mutated_order["orders"]["#W2"]["status"] = "cancelled"
    assert other_database_entities_unchanged(before, mutated_product, "#W1") is False
    assert other_database_entities_unchanged(before, mutated_order, "#W1") is False




def test_confirmation_fails_closed_when_assistant_does_not_disclose_exact_payment_method():
    results, spec = _load_inputs()
    _set_complete_confirmation(results)
    messages = results["simulations"][0]["messages"]
    assistant_confirmation = next(
        message for message in messages
        if message.get("role") == "assistant"
        and "To confirm:" in str(message.get("content") or "")
    )
    original = str(assistant_confirmation["content"])
    assert "credit_card_9513926" in original
    assistant_confirmation["content"] = original.replace(
        "credit_card_9513926", "[payment method not disclosed]"
    )

    case, _, report, release = evaluate_trace(results, spec)

    assert case["actual"]["confirmation_policy_respected"] is False
    assert case["actual"]["policy_violation_count"] == 1
    assert report["summary"]["critical_failures"] >= 1
    assert release["decision"] == "NO_GO"



def test_terminal_user_stop_without_expected_exchange_write_is_no_go() -> None:
    """A terminal trace must not pass merely because the simulator stopped cleanly."""
    results, spec = _load_inputs()
    sim = results["simulations"][0]
    messages = sim["messages"]
    exchange_index = next(
        index
        for index, message in enumerate(messages)
        if message.get("role") == "assistant"
        and any(
            isinstance(call, dict) and call.get("name") == "exchange_delivered_order_items"
            for call in (message.get("tool_calls") or [])
        )
    )

    # Reproduce a premature terminal stop before the expected business write.
    sim["messages"] = messages[:exchange_index]
    sim["termination_reason"] = "user_stop"

    case, metadata, report, release = evaluate_trace(results, spec)

    assert metadata["execution_complete"] is True
    assert metadata["expected_write_observed"] is False
    assert case["actual"]["one_expected_write_only"] is False
    assert "final_state_matches_expected" in case["unobserved_checks"]
    assert release["decision"] == "NO_GO"
    assert report["summary"]["critical_failures"] >= 1


def test_blocked_exchange_attempts_do_not_hide_the_later_successful_write() -> None:
    results, spec = _load_inputs()
    _set_complete_confirmation(results)
    messages = results["simulations"][0]["messages"]
    successful_index = next(
        index for index, message in enumerate(messages)
        if message.get("role") == "assistant"
        and any(
            isinstance(call, dict) and call.get("name") == "exchange_delivered_order_items"
            for call in (message.get("tool_calls") or [])
        )
    )
    successful_call = next(
        call for call in messages[successful_index]["tool_calls"]
        if call.get("name") == "exchange_delivered_order_items"
    )

    blocked_messages = []
    for attempt in range(2):
        call_id = f"blocked-exchange-attempt-{attempt}"
        blocked_call = json.loads(json.dumps(successful_call))
        blocked_call["id"] = call_id
        blocked_messages.extend([
            {"role": "assistant", "content": None, "tool_calls": [blocked_call]},
            {
                "role": "tool",
                "id": call_id,
                "content": (
                    "AWA_PREWRITE_NO_GO: exchange blocked before execution. "
                    "The disclosure was incomplete; do not repeat the write attempt."
                ),
            },
        ])
    confirmation_index = next(
        index for index, message in enumerate(messages[:successful_index])
        if message.get("role") == "assistant"
        and not message.get("tool_calls")
        and "To confirm:" in str(message.get("content") or "")
    )
    # Place the rejected attempts before the final disclosure and fresh
    # confirmation, matching the runtime's required retry sequence.
    messages[confirmation_index:confirmation_index] = blocked_messages

    case, metadata, report, release = evaluate_trace(results, spec)

    # The adapter must inspect the one actual successful write rather than
    # mistaking two blocked pre-write attempts for missing/ambiguous state.
    assert metadata["exchange_attempt_count"] == 3
    assert metadata["blocked_exchange_attempt_count"] == 2
    assert metadata["observed_exchange_state_result_count"] == 1
    assert metadata["unclassified_exchange_attempt_count"] == 0
    assert metadata["expected_write_observed"] is True
    assert metadata["task_completed"] is True
    assert metadata["write_attempt_policy"]["write_tool_call_count"] == 3
    assert metadata["write_attempt_policy"]["single_expected_write_attempt_policy_passed"] is False
    assert case["actual"]["confirmation_policy_respected"] is True
    assert case["actual"]["final_state_matches_expected"] is True
    assert case["actual"]["payment_policy_respected"] is True
    assert case["actual"]["price_difference_reconciles"] is True

    # Repeated blocked attempts remain visible and keep the release gate closed.
    assert case["actual"]["one_expected_write_only"] is False
    assert release["decision"] == "NO_GO"
    assert report["summary"]["critical_failures"] >= 1
