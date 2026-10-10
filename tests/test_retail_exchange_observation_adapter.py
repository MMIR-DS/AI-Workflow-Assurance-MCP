from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.adapt_retail_exchange_observation import evaluate_observation, normalize_observation

ROOT = Path(__file__).resolve().parents[1]
OBSERVATION_PATH = ROOT / "examples" / "retail_exchange_observation_v1.json"
SPEC_PATH = ROOT / "examples" / "tau2_retail_workflow.json"


def _load() -> tuple[dict, dict]:
    return (
        json.loads(OBSERVATION_PATH.read_text(encoding="utf-8")),
        json.loads(SPEC_PATH.read_text(encoding="utf-8")),
    )


def test_valid_evidence_bundle_passes_release_gate() -> None:
    observation, spec = _load()
    case, metadata, report, release = evaluate_observation(observation, spec)

    assert release["decision"] == "GO"
    assert report["summary"]["pass_rate"] == 1.0
    assert report["summary"]["total_checks"] == 16
    assert case["actual"]["policy_violation_count"] == 0
    assert metadata["computed_price_difference_usd"] == "5.00"
    assert metadata["evidence_contract"] == "retail-exchange-observation-v1"


@pytest.mark.parametrize(
    ("mutation", "expected_check"),
    [
        ("variant_unavailable", "selected_variants_match_product_and_request"),
        ("price_mismatch", "price_difference_reconciles"),
        ("wrong_payment", "payment_policy_respected"),
        ("unrelated_order_mutation", "no_unrelated_state_mutation"),
        ("confirmation_after_write", "confirmation_policy_respected"),
        ("extra_write", "one_expected_write_only"),
        ("claimed_email_without_receipt", "notification_claim_matches_contract"),
        ("new_order_added", "no_unrequested_new_order"),
    ],
)
def test_evidence_mutations_fail_closed(mutation: str, expected_check: str) -> None:
    observation, spec = _load()
    observation = copy.deepcopy(observation)

    if mutation == "variant_unavailable":
        observation["catalog_products"]["PROD-1"]["variants"]["ITEM-12"]["available"] = False
    elif mutation == "price_mismatch":
        observation["order_after"]["exchange_price_difference"] = 4.99
    elif mutation == "wrong_payment":
        observation["order_after"]["exchange_payment_method_id"] = "PAY-OTHER"
    elif mutation == "unrelated_order_mutation":
        observation["order_after"]["address"]["city"] = "Unexpected City"
    elif mutation == "confirmation_after_write":
        confirmation = observation["events"].pop(2)
        observation["events"].append(confirmation)
    elif mutation == "extra_write":
        observation["events"].append({
            "type": "write", "operation": "modify_order",
            "order_id": "ORD-1001", "succeeded": True,
        })
    elif mutation == "claimed_email_without_receipt":
        observation["notification_evidence"] = {
            "assistant_claimed_sent": True,
            "provider_delivery_status": "unknown",
        }
    elif mutation == "new_order_added":
        observation["new_order_ids_after"].append("ORD-1003")

    case, _, report, release = evaluate_observation(observation, spec)
    assert case["actual"][expected_check] is False
    assert release["decision"] == "NO_GO"
    assert report["summary"]["critical_failures"] >= 1 or report["summary"]["high_failures"] >= 1


def test_adapter_rejects_unknown_contract_version() -> None:
    observation, _ = _load()
    observation["schema_version"] = "99.0"

    with pytest.raises(ValueError, match="schema_version"):
        normalize_observation(observation)


def test_adapter_rejects_missing_event_list() -> None:
    observation, _ = _load()
    observation.pop("events")

    with pytest.raises(ValueError, match="events"):
        normalize_observation(observation)


def test_adapter_does_not_trust_boolean_like_strings() -> None:
    observation, spec = _load()
    observation["confirmation_evidence"]["confirmed"] = "true"

    case, _, _, release = evaluate_observation(observation, spec)
    assert case["actual"]["confirmation_policy_respected"] is False
    assert release["decision"] == "NO_GO"
