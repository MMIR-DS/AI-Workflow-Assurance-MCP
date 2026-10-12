from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
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


def _run_adapter_cli(observation_path: Path, spec_path: Path, output_dir: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    src = str(ROOT / "src")
    env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "adapt_retail_exchange_observation.py"),
            "--observation", str(observation_path),
            "--spec", str(spec_path),
            "--output-dir", str(output_dir),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_adapter_cli_returns_one_for_a_valid_non_go_decision(tmp_path: Path) -> None:
    observation, spec = _load()
    # An absent expected field is a validly formed spec but makes the evaluation NO_GO.
    spec["criteria"][0]["expected_path"] = "missing_expected_value"
    observation_path = tmp_path / "observation.json"
    spec_path = tmp_path / "spec.json"
    output_dir = tmp_path / "output"
    observation_path.write_text(json.dumps(observation), encoding="utf-8")
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    result = _run_adapter_cli(observation_path, spec_path, output_dir)

    assert result.returncode == 1, result.stderr
    assert json.loads(result.stdout)["decision"] == "NO_GO"
    assert (output_dir / "awa_release_report.json").exists()


def test_adapter_cli_keeps_two_for_invalid_input(tmp_path: Path) -> None:
    observation_path = tmp_path / "invalid-observation.json"
    spec_path = tmp_path / "spec.json"
    output_dir = tmp_path / "output"
    observation_path.write_text("{not-json", encoding="utf-8")
    spec_path.write_text(json.dumps(_load()[1]), encoding="utf-8")

    result = _run_adapter_cli(observation_path, spec_path, output_dir)

    assert result.returncode == 2
    assert "usage:" in result.stderr.lower()


def test_valid_evidence_bundle_passes_release_gate() -> None:
    observation, spec = _load()
    case, metadata, report, release = evaluate_observation(observation, spec)

    assert release["decision"] == "GO"
    assert report["summary"]["pass_rate"] == 1.0
    assert report["summary"]["total_checks"] == 16
    assert case["actual"]["policy_violation_count"] == 0
    assert metadata["computed_price_difference_usd"] == "5.00"
    assert metadata["evidence_contract"] == "retail-exchange-observation-v1"
    assert metadata["assurance_scope"] == "structural_and_policy_consistency_only"
    assert metadata["production_ready"] is False
    assert metadata["evidence_integrity"] == {
        "structural_validation": "passed",
        "source_authenticity": "not_verified",
        "cryptographic_signature_validation": "not_implemented",
    }


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
        ("identity_event_mismatch", "identity_policy_respected"),
        ("unknown_write_operation", "one_expected_write_only"),
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
        confirmation["collector_sequence"] = 5
        confirmation["occurred_at"] = "2026-10-10T12:00:00Z"
        observation["events"].append(confirmation)
    elif mutation == "extra_write":
        observation["events"].append({
            "type": "write", "operation": "modify_order",
            "order_id": "ORD-1001", "succeeded": True,
            "source_event_id": "evt-extra-write",
            "collector_sequence": 5, "occurred_at": "2026-10-10T12:00:00Z",
        })
    elif mutation == "claimed_email_without_receipt":
        observation["notification_evidence"] = {
            "assistant_claimed_sent": True,
            "provider_delivery_status": "unknown",
        }
    elif mutation == "new_order_added":
        observation["new_order_ids_after"].append("ORD-1003")
    elif mutation == "identity_event_mismatch":
        observation["events"][0]["source_event_id"] = "evt-auth-other"
    elif mutation == "unknown_write_operation":
        observation["events"].append({
            "type": "write", "operation": "unexpected_mutation",
            "order_id": "ORD-1001", "succeeded": True,
            "source_event_id": "evt-unknown-write",
            "collector_sequence": 5, "occurred_at": "2026-10-10T12:00:00Z",
        })

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


def test_adapter_rejects_non_object_requested_options() -> None:
    observation, _ = _load()
    observation["requested_exchange"]["requested_options"] = "not-an-object"

    with pytest.raises(ValueError, match="requested_options must be a JSON object"):
        normalize_observation(observation)


def test_adapter_rejects_non_object_option_entry() -> None:
    observation, _ = _load()
    observation["requested_exchange"]["requested_options"]["ITEM-12"] = "blue"

    with pytest.raises(ValueError, match="Each requested_options entry must be a JSON object"):
        normalize_observation(observation)


def test_adapter_rejects_options_for_unrequested_variant() -> None:
    observation, _ = _load()
    observation["requested_exchange"]["requested_options"]["ITEM-999"] = {"color": "blue"}

    with pytest.raises(ValueError, match="only contain requested new_item_ids"):
        normalize_observation(observation)



def test_adapter_rejects_partial_requested_options_map() -> None:
    observation, _ = _load()
    observation["requested_exchange"]["requested_options"] = {
        "ITEM-12": {"color": "blue", "size": "large"}
    }

    with pytest.raises(ValueError, match="must cover every requested new_item_id"):
        normalize_observation(observation)



def test_adapter_rejects_missing_event_source_id() -> None:
    observation, _ = _load()
    observation["events"][0].pop("source_event_id")

    with pytest.raises(ValueError, match="Every event must have a non-empty string source_event_id"):
        normalize_observation(observation)


def test_adapter_rejects_duplicate_event_source_ids() -> None:
    observation, _ = _load()
    observation["events"][1]["source_event_id"] = observation["events"][0]["source_event_id"]

    with pytest.raises(ValueError, match="must be unique"):
        normalize_observation(observation)


def test_adapter_rejects_missing_confirmation_id_linkage() -> None:
    observation, spec = _load()
    observation["confirmation_evidence"].pop("confirmation_id")
    observation["events"][2].pop("confirmation_id")

    case, _, _, release = evaluate_observation(observation, spec)
    assert case["actual"]["confirmation_policy_respected"] is False
    assert release["decision"] == "NO_GO"


def test_adapter_rejects_malformed_required_item_lists() -> None:
    observation, _ = _load()
    observation["requested_exchange"]["old_item_ids"] = "ITEM-11"

    with pytest.raises(ValueError, match="old_item_ids must be a non-empty list"):
        normalize_observation(observation)


def test_adapter_rejects_missing_collector_sequence() -> None:
    observation, _ = _load()
    observation["events"][1].pop("collector_sequence")

    with pytest.raises(ValueError, match="positive integer collector_sequence"):
        normalize_observation(observation)


def test_adapter_rejects_non_monotonic_collector_sequence() -> None:
    observation, _ = _load()
    observation["events"][2]["collector_sequence"] = 1

    with pytest.raises(ValueError, match="strictly increasing"):
        normalize_observation(observation)


def test_adapter_rejects_boolean_collector_sequence() -> None:
    observation, _ = _load()
    observation["events"][0]["collector_sequence"] = True

    with pytest.raises(ValueError, match="positive integer collector_sequence"):
        normalize_observation(observation)


def test_adapter_rejects_timezone_naive_collection_timestamp() -> None:
    observation, _ = _load()
    observation["collected_at"] = "2026-10-10T10:00:00"

    with pytest.raises(ValueError, match="must include a timezone"):
        normalize_observation(observation)


def test_adapter_rejects_stale_evidence_when_freshness_policy_is_configured() -> None:
    observation, spec = _load()
    evaluation_time = datetime(2026, 10, 10, 12, 10, tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="Evidence is stale"):
        evaluate_observation(
            observation, spec, evaluation_time=evaluation_time, max_evidence_age_seconds=300
        )


def test_adapter_reports_freshness_policy_as_unconfigured_by_default() -> None:
    observation, spec = _load()
    _, metadata, _, _ = evaluate_observation(observation, spec)

    assert metadata["freshness_validation"] == {
        "status": "not_configured", "max_evidence_age_seconds": None
    }


def test_adapter_passes_freshness_policy_when_evidence_is_recent() -> None:
    observation, spec = _load()
    evaluation_time = datetime(2026, 10, 10, 12, 1, tzinfo=timezone.utc)

    _, metadata, _, _ = evaluate_observation(
        observation, spec, evaluation_time=evaluation_time, max_evidence_age_seconds=300
    )

    assert metadata["freshness_validation"] == {
        "status": "passed", "max_evidence_age_seconds": 300
    }


def test_adapter_rejects_non_finite_freshness_limit() -> None:
    observation, _ = _load()

    with pytest.raises(ValueError, match="non-negative number"):
        normalize_observation(observation, max_evidence_age_seconds=float("nan"))
