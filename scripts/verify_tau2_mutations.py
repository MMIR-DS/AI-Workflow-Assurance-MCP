"""Inject raw-trace faults and verify AWA fails closed without model calls."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

try:
    from .adapt_tau2_results import evaluate_trace
except ImportError:  # Direct script execution puts the scripts/ directory on sys.path.
    from adapt_tau2_results import evaluate_trace

MUTATION_EXPECTATIONS = {
    "missing_confirmation": "confirmation_policy_respected",
    "terminal_stop_before_expected_write": "one_expected_write_only",
    "selected_variant_unavailable": "selected_variants_match_product_and_request",
    "unrelated_order_state_mutated": "no_unrelated_state_mutation",
    "price_difference_mismatch": "price_difference_reconciles",
    "payment_method_mismatch": "payment_policy_respected",
    "wrong_product_family": "selected_variants_match_product_and_request",
}


def _response(sim: dict[str, Any], name: str, arg_key: str | None = None, arg_value: Any = None) -> tuple[dict[str, Any], dict[str, Any]]:
    for message in sim.get("messages", []):
        if message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls") or []:
            if call.get("name") != name:
                continue
            args = call.get("arguments") or {}
            if arg_key is not None and args.get(arg_key) != arg_value:
                continue
            call_id = str(call.get("id", ""))
            response = next((m for m in sim.get("messages", []) if m.get("role") == "tool" and str(m.get("id", "")) == call_id), None)
            if response is None:
                raise ValueError(f"No tool response for {name}.")
            payload = json.loads(response.get("content", ""))
            if not isinstance(payload, dict):
                raise ValueError(f"Tool response for {name} is not an object.")
            return response, payload
    raise ValueError(f"Tool call not found: {name} {arg_key}={arg_value!r}")


def _store(message: dict[str, Any], payload: dict[str, Any]) -> None:
    message["content"] = json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def mutate_trace(results: dict[str, Any], name: str) -> dict[str, Any]:
    """Return a copied trace with exactly one controlled evidence mutation."""
    changed = copy.deepcopy(results)
    sims = changed.get("simulations")
    if not isinstance(sims, list) or len(sims) != 1:
        raise ValueError("Mutations require one simulation.")
    sim = sims[0]
    if name == "missing_confirmation":
        before = sim.get("messages", [])
        sim["messages"] = [m for m in before if not (m.get("role") == "user" and "yes, that's exactly right" in str(m.get("content", "")).lower())]
        if len(sim["messages"]) == len(before):
            raise ValueError("Explicit confirmation message was not found.")
    elif name == "terminal_stop_before_expected_write":
        messages = sim.get("messages", [])
        exchange_index = next(
            (
                index for index, message in enumerate(messages)
                if message.get("role") == "assistant"
                and any(
                    isinstance(call, dict)
                    and call.get("name") == "exchange_delivered_order_items"
                    for call in (message.get("tool_calls") or [])
                )
            ),
            None,
        )
        if exchange_index is None:
            raise ValueError("Expected exchange write was not found to create premature-stop mutation.")
        sim["messages"] = messages[:exchange_index]
        sim["termination_reason"] = "user_stop"
    elif name == "selected_variant_unavailable":
        message, payload = _response(sim, "get_product_details", "product_id", "1656367028")
        variant = (payload.get("variants") or {}).get("7706410293")
        if not isinstance(variant, dict):
            raise ValueError("Selected keyboard variant not found.")
        variant["available"] = False
        _store(message, payload)
    elif name == "unrelated_order_state_mutated":
        message, payload = _response(sim, "exchange_delivered_order_items")
        if not isinstance(payload.get("address"), dict):
            raise ValueError("No address in post-state.")
        payload["address"]["city"] = "Mutation Test City"
        _store(message, payload)
    elif name == "price_difference_mismatch":
        message, payload = _response(sim, "exchange_delivered_order_items")
        payload["exchange_price_difference"] = -15.00
        _store(message, payload)
    elif name == "payment_method_mismatch":
        found = False
        for message in sim.get("messages", []):
            if message.get("role") == "assistant":
                for call in message.get("tool_calls") or []:
                    if call.get("name") == "exchange_delivered_order_items":
                        call.setdefault("arguments", {})["payment_method_id"] = "credit_card_unobserved"
                        found = True
        if not found:
            raise ValueError("Exchange call not found.")
    elif name == "wrong_product_family":
        message, payload = _response(sim, "get_product_details", "product_id", "4896585277")
        payload["product_id"] = "1762337868"
        _store(message, payload)
    else:
        raise ValueError(f"Unknown mutation {name}")
    return changed


def run_mutation_checks(results: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    case0, metadata0, report0, release0 = evaluate_trace(results, spec)
    if release0["decision"] != "GO":
        raise AssertionError(f"Known-good trace should be GO, got {release0['decision']}")
    oracle0 = metadata0["tau2_oracle_for_comparison_only"]
    outcomes: dict[str, Any] = {
        "baseline": {"case": case0, "metadata": metadata0, "report": report0, "release": release0},
        "mutations": {},
    }
    for mutation, failed_field in MUTATION_EXPECTATIONS.items():
        altered = mutate_trace(results, mutation)
        case, metadata, report, release = evaluate_trace(altered, spec)
        oracle_unchanged = metadata["tau2_oracle_for_comparison_only"] == oracle0
        if not oracle_unchanged:
            raise AssertionError(f"{mutation} changed stored tau2 oracle metadata.")
        if case["actual"].get(failed_field) is not False:
            raise AssertionError(f"{mutation} did not fail {failed_field}: {case['actual']}")
        if release["decision"] != "NO_GO":
            raise AssertionError(f"{mutation} should be NO_GO, got {release['decision']}")
        outcomes["mutations"][mutation] = {
            "expected_failed_field": failed_field,
            "case": case,
            "metadata": metadata,
            "report": report,
            "release": release,
            "tau2_oracle_unchanged": oracle_unchanged,
        }
    outcomes["summary"] = {
        "baseline_decision": release0["decision"],
        "baseline_passed_checks": report0["summary"]["passed_checks"],
        "baseline_total_checks": report0["summary"]["total_checks"],
        "mutation_count": len(outcomes["mutations"]),
        "all_mutations_no_go": all(x["release"]["decision"] == "NO_GO" for x in outcomes["mutations"].values()),
        "tau2_oracle_unchanged_for_all_mutations": all(x["tau2_oracle_unchanged"] for x in outcomes["mutations"].values()),
        "mutations": {
            name: {
                "decision": item["release"]["decision"],
                "expected_failed_field": item["expected_failed_field"],
                "observed_value": item["case"]["actual"].get(item["expected_failed_field"]),
                "critical_failures": item["report"]["summary"]["critical_failures"],
                "high_failures": item["report"]["summary"]["high_failures"],
                "blocking_checks": item["release"]["blocking_checks"],
                "tau2_oracle_unchanged": item["tau2_oracle_unchanged"],
            }
            for name, item in outcomes["mutations"].items()
        },
    }
    return outcomes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--spec", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    results = json.loads(args.results.read_text(encoding="utf-8"))
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    outcome = run_mutation_checks(results, spec)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    def write_report(directory: Path, item: dict[str, Any]) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        values = {
            "awa_cases.json": [item["case"]],
            "adapter_metadata.json": [item["metadata"]],
            "awa_eval_report.json": item["report"],
            "awa_release_report.json": item["release"],
        }
        for filename, value in values.items():
            (directory / filename).write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    write_report(args.output_dir / "baseline", outcome["baseline"])
    for name, item in outcome["mutations"].items():
        write_report(args.output_dir / "mutations" / name, item)
    (args.output_dir / "mutation_summary.json").write_text(json.dumps(outcome["summary"], indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps(outcome["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
