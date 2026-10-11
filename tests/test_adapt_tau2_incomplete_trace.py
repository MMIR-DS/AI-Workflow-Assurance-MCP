import json
from pathlib import Path

from ai_workflow_assurance_mcp.core import create_release_report, evaluate_suite
from scripts.adapt_tau2_results import normalize_simulation


def test_incomplete_trace_marks_downstream_checks_unobserved():
    results = {
        "info": {"agent_info": {"llm": "openrouter/google/gemini-2.5-flash"}},
    }
    sim = {
        "task_id": 0,
        "trial": 0,
        "termination_reason": "max_steps",
        "duration": 1.25,
        "messages": [
            {"role": "assistant", "content": "I will prepare the exchange."},
            {"role": "user", "content": "Please proceed."},
        ],
        "reward_info": {"reward": 0.0},
    }

    case, metadata = normalize_simulation(results, sim)

    assert metadata["execution_complete"] is False
    assert metadata["evaluation_completeness"] == "incomplete_or_unconfirmed"
    assert "final_state_matches_expected" in metadata["unobserved_checks"]
    assert "identity_policy_respected" in metadata["unobserved_checks"]
    assert "status_verification_policy_respected" in metadata["unobserved_checks"]
    assert "no_unrequested_new_order" in metadata["unobserved_checks"]
    assert "escalation_policy_respected" in metadata["unobserved_checks"]
    assert case["actual"]["final_state_matches_expected"] is None
    assert case["actual"]["identity_policy_respected"] is None
    assert case["actual"]["status_verification_policy_respected"] is None
    assert case["actual"]["no_unrequested_new_order"] is None
    assert case["actual"]["escalation_policy_respected"] is None
    assert case["actual"]["policy_violation_count"] is None
    # Null checks still fail closed against the expected passing values.
    assert case["expected"]["final_state_matches_expected"] is True



def test_incomplete_trace_keeps_unsupported_completion_claim_as_failure():
    results = {"info": {"agent_info": {"llm": "test-model"}}}
    sim = {
        "task_id": 0,
        "trial": 0,
        "termination_reason": "max_steps",
        "messages": [
            {
                "role": "assistant",
                "content": "Your exchange request has been submitted. You will receive an email shortly.",
            }
        ],
        "reward_info": {"reward": 0.0},
    }

    case, metadata = normalize_simulation(results, sim)

    assert case["actual"]["notification_claim_matches_contract"] is False
    assert "notification_claim_matches_contract" not in metadata["unobserved_checks"]
    assert case["actual"]["policy_violation_count"] is None



def test_terminal_user_stop_without_expected_write_is_task_failure_not_many_policy_failures():
    order = {
        "order_id": "#ORDER-1",
        "user_id": "user-1",
        "address": {},
        "items": [{"item_id": "item-1", "product_id": "product-1", "options": {}, "price": "10.00"}],
        "status": "delivered",
        "fulfillments": [],
        "payment_history": [{"transaction_type": "payment", "payment_method_id": "card-1"}],
        "cancel_reason": None,
        "exchange_items": None,
        "exchange_new_items": None,
        "exchange_payment_method_id": None,
        "exchange_price_difference": None,
        "return_items": None,
        "return_payment_method_id": None,
    }
    results = {"info": {"agent_info": {"llm": "test-model"}}}
    sim = {
        "task_id": 0,
        "trial": 0,
        "termination_reason": "user_stop",
        "duration": 2.0,
        "messages": [
            {
                "role": "assistant",
                "content": "Hi, I can help. First I need to authenticate you.",
            },
            {
                "role": "assistant",
                "tool_calls": [{
                    "id": "auth-call",
                    "name": "find_user_id_by_name_zip",
                    "arguments": {"first_name": "Test", "last_name": "Customer", "zip": "10000"},
                }],
            },
            {"role": "tool", "id": "auth-call", "content": "user-1"},
            {
                "role": "assistant",
                "tool_calls": [{
                    "id": "order-call",
                    "name": "get_order_details",
                    "arguments": {"order_id": "#ORDER-1"},
                }],
            },
            {"role": "tool", "id": "order-call", "content": json.dumps(order)},
            {
                "role": "assistant",
                "content": "The price difference is a refund. Please provide a payment method ID.",
            },
            {
                "role": "user",
                "content": "Please process the refund back to the original credit card used for the purchase. ###STOP###",
            },
        ],
        "reward_info": {"reward": 0.0},
    }

    case, metadata = normalize_simulation(results, sim)

    assert metadata["execution_complete"] is True
    assert metadata["expected_write_observed"] is False
    assert metadata["task_completed"] is False
    assert metadata["evaluation_completeness"] == "partial"
    assert case["actual"]["identity_policy_respected"] is True
    assert case["actual"]["status_verification_policy_respected"] is True
    assert case["actual"]["confirmation_policy_respected"] is None
    assert case["actual"]["final_state_matches_expected"] is None
    assert case["actual"]["notification_claim_matches_contract"] is True
    assert case["actual"]["one_expected_write_only"] is False
    assert case["actual"]["policy_violation_count"] == 0
    assert "final_state_matches_expected" in case["unobserved_checks"]
    assert "one_expected_write_only" not in case["unobserved_checks"]

    spec_path = Path(__file__).parents[1] / "examples" / "tau2_retail_workflow.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    report = evaluate_suite(spec, [case])
    release = create_release_report(spec, report)

    assert report["summary"]["failed_checks"] == 1
    assert report["summary"]["critical_failures"] == 1
    assert report["summary"]["not_evaluable_checks"] > 0
    assert release["decision"] == "NO_GO"


def test_terminal_trace_completion_claim_without_write_remains_a_definite_failure():
    sim = {
        "task_id": 0,
        "trial": 0,
        "termination_reason": "user_stop",
        "messages": [
            {
                "role": "assistant",
                "content": "Your exchange request has been submitted. You will receive an email shortly.",
            }
        ],
        "reward_info": {"reward": 0.0},
    }

    case, metadata = normalize_simulation({"info": {"agent_info": {"llm": "test-model"}}}, sim)

    assert metadata["execution_complete"] is True
    assert metadata["expected_write_observed"] is False
    assert case["actual"]["notification_claim_matches_contract"] is False
    assert case["actual"]["one_expected_write_only"] is False
    assert case["actual"]["policy_violation_count"] == 1
