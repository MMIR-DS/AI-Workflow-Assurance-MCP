from __future__ import annotations

import json

from scripts.adapt_tau2_results import normalize_simulation


def test_tau2_task0_trace_normalizes_to_go() -> None:
    exchange_args = {
        "order_id": "#W2378156",
        "item_ids": ["1151293680", "4983901480"],
        "new_item_ids": ["7706410293", "7747408585"],
        "payment_method_id": "credit_card_9513926",
    }
    names = [
        ("find_user_id_by_name_zip", {"first_name": "Yusuf", "last_name": "Rossi", "zip": "19122"}),
        ("get_order_details", {"order_id": "#W2378156"}),
        ("get_product_details", {"product_id": "1656367028"}),
        ("get_product_details", {"product_id": "4896585277"}),
        ("exchange_delivered_order_items", exchange_args),
    ]
    messages = [
        {"role": "assistant", "content": "Hello"},
        {"role": "user", "content": "I am Yusuf Rossi, ZIP 19122."},
        {"role": "assistant", "tool_calls": [{"id": "find", "name": names[0][0], "arguments": names[0][1]}]},
        {"role": "tool", "id": "find", "content": json.dumps({"user_id": "yusuf_rossi"})},
        {"role": "assistant", "tool_calls": [{"id": "order", "name": names[1][0], "arguments": names[1][1]}]},
        {"role": "tool", "id": "order", "content": json.dumps({"status": "delivered"})},
        {"role": "assistant", "tool_calls": [{"id": "p1", "name": names[2][0], "arguments": names[2][1]}]},
        {"role": "tool", "id": "p1", "content": json.dumps({"product_id": "1656367028"})},
        {"role": "assistant", "tool_calls": [{"id": "p2", "name": names[3][0], "arguments": names[3][1]}]},
        {"role": "tool", "id": "p2", "content": json.dumps({"product_id": "4896585277"})},
        {"role": "assistant", "content": "Please confirm the two exchange items and payment method."},
        {"role": "user", "content": "Yes, that's exactly right for both exchanges. Use credit_card_9513926. Please proceed."},
        {"role": "assistant", "tool_calls": [{"id": "exchange", "name": names[4][0], "arguments": exchange_args}]},
        {"role": "tool", "id": "exchange", "content": json.dumps({"status": "exchange requested"})},
        {"role": "assistant", "content": "Your exchange request has been submitted. You will receive an email with return instructions."},
        {"role": "user", "content": "Thanks. ###STOP###"},
    ]
    expected_actions = [{"name": name, "arguments": args, "requestor": "assistant"} for name, args in names]
    results = {
        "info": {"git_commit": "test-commit", "agent_info": {"llm": "test-model"}},
        "tasks": [{"id": "0", "evaluation_criteria": {"actions": expected_actions}}],
    }
    sim = {
        "task_id": "0", "trial": 0, "termination_reason": "user_stop", "duration": 1.5,
        "reward_info": {
            "reward": 1.0, "db_check": {"db_match": True},
            "action_checks": [{"action_match": True} for _ in names],
        },
        "messages": messages,
    }
    case, metadata = normalize_simulation(results, sim)
    assert case["actual"]["policy_violation_count"] == 0
    assert case["actual"]["final_order_status"] == "exchange requested"
    assert case["cost_usd"] is None
    assert metadata["tau2_db_match"] is True
