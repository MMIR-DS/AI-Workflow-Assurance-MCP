"""Run deterministic, no-model replay scenarios through the real Tau2/AWA adapter.

This suite replays a saved task-0 trace and applies controlled mutations. It does not
launch Tau2, invoke a model API, or make its report eligible as fresh release evidence.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ai_workflow_assurance_mcp.core import create_release_report, evaluate_suite

if __package__:
    from .adapt_tau2_results import normalize_simulation
else:
    from adapt_tau2_results import normalize_simulation

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TRACE = ROOT / "tests" / "fixtures" / "tau2_task0_trace_minimal.json"
DEFAULT_SPEC = ROOT / "examples" / "tau2_retail_workflow.json"


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    expected_decision: str
    mutate: Callable[[dict[str, Any]], None]
    expectations: dict[str, Any]
    evidence_class: str = "synthetic_mutation_of_saved_trace"


def _sim(results: dict[str, Any]) -> dict[str, Any]:
    simulations = results.get("simulations")
    if not isinstance(simulations, list) or len(simulations) != 1 or not isinstance(simulations[0], dict):
        raise ValueError("Offline scenario suite requires exactly one saved Tau2 simulation.")
    messages = simulations[0].get("messages")
    if not isinstance(messages, list):
        raise ValueError("Saved Tau2 simulation is missing its messages list.")
    return simulations[0]


def _find_call(
    results: dict[str, Any],
    tool_name: str,
    predicate: Callable[[dict[str, Any]], bool] | None = None,
) -> tuple[int, dict[str, Any]]:
    messages = _sim(results)["messages"]
    matches: list[tuple[int, dict[str, Any]]] = []
    for index, message in enumerate(messages):
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls") or []:
            if not isinstance(call, dict) or call.get("name") != tool_name:
                continue
            arguments = call.get("arguments")
            if not isinstance(arguments, dict):
                continue
            if predicate is None or predicate(arguments):
                matches.append((index, call))
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one {tool_name} tool call for scenario mutation; found {len(matches)}.")
    return matches[0]


def _tool_result(results: dict[str, Any], call: dict[str, Any]) -> dict[str, Any]:
    call_id = call.get("id")
    matches = [
        message for message in _sim(results)["messages"]
        if isinstance(message, dict) and message.get("role") == "tool" and message.get("id") == call_id
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one tool result for call {call_id!r}; found {len(matches)}.")
    return matches[0]


def _json_payload(message: dict[str, Any]) -> dict[str, Any]:
    content = message.get("content")
    if not isinstance(content, str):
        raise ValueError("Expected a JSON-encoded tool result in the saved fixture.")
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError("Expected tool result JSON object.")
    return value


def _save_payload(message: dict[str, Any], value: dict[str, Any]) -> None:
    message["content"] = json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _mutate_none(results: dict[str, Any]) -> None:
    return


def _mutate_oracle_fields_only(results: dict[str, Any]) -> None:
    # Adversarial negative oracle metadata must not overrule recorded tool evidence.
    _sim(results)["reward_info"] = {
        "reward": 0.0,
        "db_check": {"db_match": False},
        "action_checks": [{"action_match": False}],
    }


def _mutate_complete_disclosure_positive_control(results: dict[str, Any]) -> None:
    # The archived trace's disclosure is intentionally incomplete under the current guard.
    # This synthetic control changes only the customer-facing disclosure before the same confirmation.
    messages = _sim(results)["messages"]
    matches = [
        message for message in messages
        if isinstance(message, dict) and message.get("role") == "assistant"
        and str(message.get("content") or "").startswith("To confirm:")
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected one pre-write disclosure message; found {len(matches)}.")
    matches[0]["content"] = (
        "To confirm order #W2378156: exchange old item 1151293680 for 7706410293 "
        "and old item 4983901480 for 7747408585. The total price difference is "
        "a $16.63 refund to credit_card_9513926. Please confirm."
    )
    # Use a confirmation phrase and explicit payment reference covered by current policy tests.
    confirmation_index = next(
        (i for i, message in enumerate(messages)
         if isinstance(message, dict) and message.get("role") == "user"
         and "Yes, that's exactly right" in str(message.get("content") or "")),
        None,
    )
    if confirmation_index is None:
        raise ValueError("Expected an existing user confirmation to anchor the positive control.")
    messages[confirmation_index]["content"] = (
        "Yes, that's correct. Go ahead and use credit_card_9513926 for this exchange."
    )


def _mutate_missing_confirmation(results: dict[str, Any]) -> None:
    messages = _sim(results)["messages"]
    matches = [
        index for index, message in enumerate(messages)
        if isinstance(message, dict) and message.get("role") == "user"
        and "Yes, that's exactly right" in str(message.get("content") or "")
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected one affirmative confirmation in fixture; found {len(matches)}.")
    del messages[matches[0]]


def _mutate_unavailable_variant(results: dict[str, Any]) -> None:
    _, call = _find_call(
        results, "get_product_details",
        lambda args: str(args.get("product_id")) == "1656367028",
    )
    result = _tool_result(results, call)
    product = _json_payload(result)
    variants = product.get("variants")
    if not isinstance(variants, dict) or not isinstance(variants.get("7706410293"), dict):
        raise ValueError("Fixture no longer contains the selected keyboard variant.")
    variants["7706410293"]["available"] = False
    _save_payload(result, product)


def _mutate_unrelated_order_state(results: dict[str, Any]) -> None:
    _, call = _find_call(results, "exchange_delivered_order_items")
    result = _tool_result(results, call)
    after = _json_payload(result)
    address = after.get("address")
    if not isinstance(address, dict) or not isinstance(address.get("address1"), str):
        raise ValueError("Fixture has no reviewed address field to mutate.")
    address["address1"] += " [synthetic mutation]"
    _save_payload(result, after)


def _mutate_price_difference(results: dict[str, Any]) -> None:
    _, call = _find_call(results, "exchange_delivered_order_items")
    result = _tool_result(results, call)
    after = _json_payload(result)
    after["exchange_price_difference"] = "-15.00"
    _save_payload(result, after)


def _mutate_unobserved_payment_method(results: dict[str, Any]) -> None:
    _, call = _find_call(results, "exchange_delivered_order_items")
    call["arguments"]["payment_method_id"] = "PAYMENT_METHOD_NOT_IN_ORDER_EVIDENCE"


def _mutate_product_family_mapping(results: dict[str, Any]) -> None:
    # Ask for the keyboard product while retaining the thermostat tool response.
    # The adapter must not accept a payload whose product ID differs from the query.
    _, call = _find_call(
        results, "get_product_details",
        lambda args: str(args.get("product_id")) == "4896585277",
    )
    call["arguments"]["product_id"] = "1656367028"


def _mutate_duplicate_blocked_write(results: dict[str, Any]) -> None:
    messages = _sim(results)["messages"]
    _, original = _find_call(results, "exchange_delivered_order_items")
    final_message_index = next(
        (i for i, message in enumerate(messages)
         if isinstance(message, dict) and message.get("role") == "assistant"
         and "Your exchange request has been submitted" in str(message.get("content") or "")),
        None,
    )
    if final_message_index is None:
        raise ValueError("Fixture no longer contains the terminal exchange message.")
    second_id = "offline-synthetic-duplicate-exchange"
    duplicate = {
        "role": "assistant",
        "tool_calls": [{
            "id": second_id,
            "name": "exchange_delivered_order_items",
            "arguments": copy.deepcopy(original["arguments"]),
        }],
    }
    blocked = {
        "role": "tool",
        "id": second_id,
        "content": "AWA_PREWRITE_NO_GO: synthetic duplicate write blocked before dispatch",
    }
    messages[final_message_index:final_message_index] = [duplicate, blocked]


def _mutate_unreviewed_create_order(results: dict[str, Any]) -> None:
    messages = _sim(results)["messages"]
    exchange_index, _ = _find_call(results, "exchange_delivered_order_items")
    call_id = "offline-synthetic-create-order"
    attempt = {
        "role": "assistant",
        "tool_calls": [{
            "id": call_id,
            "name": "create_order",
            "arguments": {"items": []},
        }],
    }
    blocked = {
        "role": "tool",
        "id": call_id,
        "content": "AWA_PREWRITE_NO_GO: synthetic unreviewed write blocked before dispatch",
    }
    messages[exchange_index:exchange_index] = [attempt, blocked]


def _mutate_block_expected_write(results: dict[str, Any]) -> None:
    _, call = _find_call(results, "exchange_delivered_order_items")
    _tool_result(results, call)["content"] = "AWA_PREWRITE_NO_GO: synthetic pre-write denial"


def _mutate_truncated_before_write(results: dict[str, Any]) -> None:
    simulation = _sim(results)
    messages = simulation["messages"]
    write_index, _ = _find_call(results, "exchange_delivered_order_items")
    simulation["messages"] = messages[:write_index]
    simulation["termination_reason"] = "max_steps"


SCENARIOS = (
    Scenario(
        "recorded_trace_baseline", "NO_GO", _mutate_none,
        {
            "release.decision": "NO_GO",
            "metadata.task_completed": True,
            "metadata.expected_write_observed": True,
            "metadata.blocked_exchange_attempt_count": 0,
            "case.actual.one_expected_write_only": True,
            "case.actual.confirmation_policy_respected": False,
        },
        evidence_class="historical_saved_trace",
    ),
    Scenario(
        "oracle_fields_do_not_override_tool_evidence", "NO_GO", _mutate_oracle_fields_only,
        {
            "release.decision": "NO_GO",
            "metadata.task_completed": True,
            "case.actual.confirmation_policy_respected": False,
            "metadata.tau2_oracle_for_comparison_only.reward": 0.0,
            "metadata.tau2_oracle_for_comparison_only.db_match": False,
            "metadata.tau2_oracle_for_comparison_only.action_checks_all_match": False,
        },
    ),
    Scenario(
        "complete_disclosure_positive_control", "GO", _mutate_complete_disclosure_positive_control,
        {
            "release.decision": "GO",
            "metadata.task_completed": True,
            "metadata.expected_write_observed": True,
            "case.actual.confirmation_policy_respected": True,
            "case.actual.one_expected_write_only": True,
            "case.actual.policy_violation_count": 0,
            "evaluation.summary.pass_rate": 1.0,
        },
    ),
    Scenario(
        "missing_customer_confirmation", "NO_GO", _mutate_missing_confirmation,
        {"case.actual.confirmation_policy_respected": False, "release.decision": "NO_GO"},
    ),
    Scenario(
        "selected_variant_marked_unavailable", "NO_GO", _mutate_unavailable_variant,
        {"case.actual.selected_variants_match_product_and_request": False, "release.decision": "NO_GO"},
    ),
    Scenario(
        "unrelated_order_state_mutated", "NO_GO", _mutate_unrelated_order_state,
        {"case.actual.no_unrelated_state_mutation": False, "release.decision": "NO_GO"},
    ),
    Scenario(
        "price_difference_does_not_reconcile", "NO_GO", _mutate_price_difference,
        {"case.actual.price_difference_reconciles": False, "release.decision": "NO_GO"},
    ),
    Scenario(
        "payment_method_not_in_order_evidence", "NO_GO", _mutate_unobserved_payment_method,
        {"case.actual.payment_policy_respected": False, "release.decision": "NO_GO"},
    ),
    Scenario(
        "product_response_does_not_match_requested_product", "NO_GO", _mutate_product_family_mapping,
        {"case.actual.selected_variants_match_product_and_request": False, "release.decision": "NO_GO"},
    ),
    Scenario(
        "second_write_attempt_blocked_but_still_counted", "NO_GO", _mutate_duplicate_blocked_write,
        {
            "metadata.task_completed": True,
            "metadata.exchange_attempt_count": 2,
            "metadata.blocked_exchange_attempt_count": 1,
            "metadata.observed_exchange_state_result_count": 1,
            "metadata.write_attempt_policy.write_tool_call_count": 2,
            "case.actual.one_expected_write_only": False,
            "release.decision": "NO_GO",
        },
    ),
    Scenario(
        "unreviewed_create_order_attempt", "NO_GO", _mutate_unreviewed_create_order,
        {
            "case.actual.no_unrequested_new_order": False,
            "case.actual.one_expected_write_only": False,
            "release.decision": "NO_GO",
        },
    ),
    Scenario(
        "expected_exchange_write_explicitly_blocked", "NO_GO", _mutate_block_expected_write,
        {
            "metadata.expected_write_observed": False,
            "metadata.blocked_exchange_attempt_count": 1,
            "case.actual.one_expected_write_only": False,
            "release.decision": "NO_GO",
        },
    ),
    Scenario(
        "trace_truncated_before_write", "HOLD", _mutate_truncated_before_write,
        {
            "metadata.execution_complete": False,
            "metadata.task_completed": False,
            "metadata.evaluation_completeness": "incomplete_or_unconfirmed",
            "case.actual.final_state_matches_expected": None,
            "release.decision": "HOLD",
        },
    ),
)


def _resolve_path(context: dict[str, Any], dotted_path: str) -> Any:
    value: Any = context
    for part in dotted_path.split("."):
        if not isinstance(value, dict) or part not in value:
            raise KeyError(f"Scenario expectation path is not present: {dotted_path}")
        value = value[part]
    return value


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.name


def run_scenario_suite(
    trace_path: Path = DEFAULT_TRACE,
    spec_path: Path = DEFAULT_SPEC,
) -> dict[str, Any]:
    trace_bytes = trace_path.read_bytes()
    original = json.loads(trace_bytes)
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    # Validate the fixture shape before the first scenario is evaluated.
    _sim(original)

    rows: list[dict[str, Any]] = []
    for scenario in SCENARIOS:
        results = copy.deepcopy(original)
        scenario.mutate(results)
        simulation = _sim(results)
        case, metadata = normalize_simulation(results, simulation)
        evaluation = evaluate_suite(spec, [case])
        release = create_release_report(spec, evaluation)
        context = {
            "case": case,
            "metadata": metadata,
            "evaluation": evaluation,
            "release": release,
        }
        mismatches = []
        for path, expected in scenario.expectations.items():
            observed = _resolve_path(context, path)
            if observed != expected:
                mismatches.append({
                    "path": path,
                    "expected": expected,
                    "observed": observed,
                })
        rows.append({
            "scenario_id": scenario.scenario_id,
            "evidence_class": scenario.evidence_class,
            "expected_awa_decision": scenario.expected_decision,
            "actual_awa_decision": release.get("decision"),
            "pass_rate": evaluation.get("summary", {}).get("pass_rate"),
            "passed_checks": evaluation.get("summary", {}).get("passed_checks"),
            "failed_checks": evaluation.get("summary", {}).get("failed_checks"),
            "critical_failures": evaluation.get("summary", {}).get("critical_failures"),
            "not_evaluable_checks": evaluation.get("summary", {}).get("not_evaluable_checks"),
            "task_completed": metadata.get("task_completed"),
            "expected_write_observed": metadata.get("expected_write_observed"),
            "exchange_attempt_count": metadata.get("exchange_attempt_count"),
            "blocked_exchange_attempt_count": metadata.get("blocked_exchange_attempt_count"),
            "observed_exchange_state_result_count": metadata.get("observed_exchange_state_result_count"),
            "unclassified_exchange_attempt_count": metadata.get("unclassified_exchange_attempt_count"),
            "one_expected_write_only": case.get("actual", {}).get("one_expected_write_only"),
            "failed_criteria": [
                {"criterion_id": key, "expected": expected, "actual": case.get("actual", {}).get(key)}
                for key, expected in case.get("expected", {}).items()
                if case.get("actual", {}).get(key) != expected
            ],
            "passed": not mismatches and release.get("decision") == scenario.expected_decision,
            "mismatches": mismatches,
        })

    passed_count = sum(row["passed"] for row in rows)
    return {
        "schema_version": "awa-tau2-offline-scenario-suite-v1",
        "suite_status": "PASS" if passed_count == len(rows) else "FAIL",
        "scenario_count": len(rows),
        "passed_scenarios": passed_count,
        "failed_scenarios": len(rows) - passed_count,
        "model_execution_performed": False,
        "additional_model_calls": 0,
        "network_calls_performed": False,
        "release_eligible": False,
        "warning": (
            "A PASS means offline scenario expectations matched. It is not a fresh model run, "
            "does not establish production reliability, and is not release evidence."
        ),
        "source_fixture": _display_path(trace_path),
        "source_fixture_sha256": hashlib.sha256(trace_bytes).hexdigest(),
        "pinned_tau2_commit_in_fixture": ((original.get("info") or {}).get("git_commit")),
        "scenarios": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, default=DEFAULT_TRACE)
    parser.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    parser.add_argument("--output", type=Path, help="Optional path for the machine-readable JSON report.")
    args = parser.parse_args()

    report = run_scenario_suite(args.trace, args.spec)
    rendered = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["suite_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
