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
