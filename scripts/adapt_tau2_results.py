"""Normalize a tau2 retail result into deterministic AWA case and release reports.

This prototype deliberately records where it relies on tau2's oracle. It does not
independently diff the simulator's full initial/final database snapshots.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ai_workflow_assurance_mcp.core import create_release_report, evaluate_suite


def _parse_tool_result(message: dict[str, Any]) -> Any:
    try:
        return json.loads(message.get("content", ""))
    except (json.JSONDecodeError, TypeError):
        return None


def normalize_simulation(results: dict[str, Any], sim: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    messages = [m for m in sim.get("messages", []) if isinstance(m, dict)]
    calls = []
    for index, message in enumerate(messages):
        if message.get("role") == "assistant":
            for call in message.get("tool_calls") or []:
                if isinstance(call, dict):
                    calls.append({"index": index, "name": call.get("name"), "arguments": call.get("arguments") or {}, "id": call.get("id")})
    names = [call["name"] for call in calls]
    task = next((t for t in results.get("tasks", []) if str(t.get("id")) == str(sim.get("task_id"))), {})
    expected_actions = (task.get("evaluation_criteria") or {}).get("actions") or []
    oracle = sim.get("reward_info") or {}
    action_checks = oracle.get("action_checks") or []
    all_actions_match = bool(action_checks) and all(x.get("action_match") is True for x in action_checks) and len(action_checks) == len(expected_actions)
    db_match = (oracle.get("db_check") or {}).get("db_match") is True

    identity = [c["index"] for c in calls if c["name"] == "find_user_id_by_name_zip"]
    reads = [c["index"] for c in calls if c["name"] in {"get_order_details", "get_product_details"}]
    exchanges = [c for c in calls if c["name"] == "exchange_delivered_order_items"]
    writes = [c for c in calls if c["name"] in {"exchange_delivered_order_items", "cancel_order", "modify_pending_order", "create_order", "return_delivered_order_items"}]
    mutations = [c["index"] for c in writes]

    order_status = None
    exchange_result = None
    for message in messages:
        if message.get("role") != "tool":
            continue
        parsed = _parse_tool_result(message)
        if isinstance(parsed, dict):
            if order_status is None and isinstance(parsed.get("status"), str):
                order_status = parsed["status"]
            if exchanges and message.get("id") == exchanges[0].get("id"):
                exchange_result = parsed
    if exchange_result is None:
        exchange_result = next((_parse_tool_result(m) for m in reversed(messages) if m.get("role") == "tool" and isinstance(_parse_tool_result(m), dict) and _parse_tool_result(m).get("status") == "exchange requested"), None)
    final_status = exchange_result.get("status") if isinstance(exchange_result, dict) else None

    pre_mutation_user_text = "\n".join(str(m.get("content") or "") for i, m in enumerate(messages) if m.get("role") == "user" and (not mutations or i < mutations[0])).lower()
    explicit_confirmation = any(token in pre_mutation_user_text for token in ("yes, that's exactly right", "i confirm", "please proceed", "go ahead"))
    args = exchanges[0].get("arguments", {}) if exchanges else {}
    expected_exchange = next((a for a in expected_actions if a.get("name") == "exchange_delivered_order_items"), {})
    expected_args = expected_exchange.get("arguments") or {}
    exchange_matches = bool(expected_exchange) and args == expected_args
    multi_item_complete = len(exchanges) == 1 and len(args.get("item_ids", [])) == 2 and len(args.get("new_item_ids", [])) == 2 and exchange_matches
    payment_confirmed = bool(args.get("payment_method_id") and args["payment_method_id"] in pre_mutation_user_text)
    final_text = "\n".join(str(m.get("content") or "") for m in messages if m.get("role") == "assistant" and m.get("content"))
    notified = bool(exchanges and db_match and "email" in final_text.lower() and any(s in final_text.lower() for s in ("exchange request has been submitted", "exchange is complete", "exchange has been processed")))
    no_new_order = "create_order" not in names
    no_transfer = not any("transfer_to_human" in str(name) or "transfer_to_agent" in str(name) for name in names)
    only_expected_write = all(c["name"] == "exchange_delivered_order_items" for c in writes)

    actual = {
        "identity_policy_respected": bool(identity and reads and identity[0] < min(reads)),
        "status_verification_policy_respected": bool(reads and mutations and min(reads) < min(mutations) and order_status == "delivered"),
        "confirmation_policy_respected": bool(explicit_confirmation and mutations),
        "exchange_eligibility_policy_respected": bool(order_status == "delivered" and exchanges),
        "same_product_variant_policy_respected": bool(exchange_matches and all_actions_match),
        "payment_policy_respected": bool(payment_confirmed and exchange_matches),
        "multi_item_scope_respected": multi_item_complete,
        "final_state_matches_expected": db_match,
        "notification_policy_respected": notified,
        "no_unrelated_state_mutation": bool(db_match and only_expected_write),
        "no_unrequested_new_order": no_new_order,
        "escalation_policy_respected": no_transfer,
        "final_order_status": final_status,
    }
    actual["policy_violation_count"] = sum(value is False for key, value in actual.items() if isinstance(value, bool))
    expected = {
        "identity_policy_respected": True, "status_verification_policy_respected": True,
        "confirmation_policy_respected": True, "exchange_eligibility_policy_respected": True,
        "same_product_variant_policy_respected": True, "payment_policy_respected": True,
        "multi_item_scope_respected": True, "final_state_matches_expected": True,
        "notification_policy_respected": True, "no_unrelated_state_mutation": True,
        "no_unrequested_new_order": True, "escalation_policy_respected": True,
        "policy_violation_count": 0, "final_order_status": "exchange requested",
    }

    costs = []
    for message in messages:
        raw = message.get("raw_data")
        usage = raw.get("usage") if isinstance(raw, dict) else None
        cost = usage.get("cost") if isinstance(usage, dict) else None
        if isinstance(cost, (int, float)) and not isinstance(cost, bool) and cost >= 0:
            costs.append(float(cost))
    duration = sim.get("duration")
    case = {
        "case_id": f"retail-task-{sim.get('task_id')}-trial-{sim.get('trial', 0)}",
        "expected": expected, "actual": actual, "human_review_observed": not no_transfer,
        "cost_usd": sum(costs) if costs else None,
        "latency_ms": round(duration * 1000) if isinstance(duration, (int, float)) else None,
    }
    info = results.get("info") or {}
    metadata = {
        "task_id": str(sim.get("task_id")), "trial": sim.get("trial"),
        "termination_reason": sim.get("termination_reason"), "tau2_reward": oracle.get("reward"),
        "tau2_db_match": db_match, "tau2_action_checks_all_match": all_actions_match,
        "tau2_action_check_count": len(action_checks), "tau2_git_commit": info.get("git_commit"),
        "model": (info.get("agent_info") or {}).get("llm"),
        "oracle_basis": [
            "Identity, order-status, confirmation and notification checks are derived from the recorded message/tool trace.",
            "Final-state and unrelated-mutation checks use tau2's db_match oracle; no independent database diff was available.",
            "Variant/payment checks also reference tau2 expected action checks and the task's expected exchange action.",
            "Expected values are a manually reviewed oracle for public retail task 0 only; do not reuse unchanged for other tasks.",
        ],
    }
    return case, metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    results = json.loads(args.results.read_text(encoding="utf-8"))
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    sims = results.get("simulations")
    if not isinstance(sims, list) or not sims:
        parser.error("tau2 results contain no simulations")
    normalized = [normalize_simulation(results, sim) for sim in sims if isinstance(sim, dict)]
    cases = [item[0] for item in normalized]
    report = evaluate_suite(spec, cases)
    release = create_release_report(spec, report)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "awa_cases.json": cases, "awa_eval_report.json": report,
        "awa_release_report.json": release, "adapter_metadata.json": [item[1] for item in normalized],
    }
    for name, value in outputs.items():
        (args.output_dir / name).write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps({"cases": len(cases), "pass_rate": report["summary"]["pass_rate"], "decision": release["decision"], "blocking_checks": release["blocking_checks"]}, indent=2))
    return 0 if release["decision"] == "GO" else 2


if __name__ == "__main__":
    raise SystemExit(main())
