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
    assert case["actual"]["final_state_matches_expected"] is None
    assert case["actual"]["policy_violation_count"] is None
    # Missing downstream evidence must not be reported as a successful case.
    assert case["actual"]["identity_policy_respected"] is False
