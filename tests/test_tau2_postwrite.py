from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from ai_workflow_assurance_mcp.tau2_postwrite import (
    audit_tau2_order_items_against_catalog,
)


_CAMERA_OPTIONS = {
    "resolution": "4K",
    "waterproof": "yes",
    "color": "black",
}
_LAMP_OPTIONS = {
    "color": "black",
    "brightness": "medium",
    "power source": "AC adapter",
}
_SHIRT_OPTIONS = {
    "color": "red",
    "size": "L",
    "material": "cotton",
    "style": "v-neck",
}


def _catalog_snapshots() -> list[dict]:
    return [
        {
            "product_id": "product-camera",
            "variants": {
                "camera-new": {
                    "item_id": "camera-new",
                    "price": 466.75,
                    "options": _CAMERA_OPTIONS,
                    "available": True,
                }
            },
        },
        {
            "product_id": "product-lamp",
            "variants": {
                "lamp-new": {
                    "item_id": "lamp-new",
                    "price": 135.24,
                    "options": _LAMP_OPTIONS,
                    "available": True,
                }
            },
        },
        {
            "product_id": "product-shirt",
            "variants": {
                "shirt-new": {
                    "item_id": "shirt-new",
                    "price": 46.66,
                    "options": _SHIRT_OPTIONS,
                    "available": True,
                }
            },
        },
    ]


def _order_snapshot() -> dict:
    return {
        "order_id": "#W9348897",
        "status": "pending (item modified)",
        "items": [
            {
                "product_id": "product-camera",
                "item_id": "camera-new",
                "price": 466.75,
                "options": dict(_CAMERA_OPTIONS),
            },
            {
                "product_id": "product-lamp",
                "item_id": "lamp-new",
                "price": 135.24,
                "options": dict(_LAMP_OPTIONS),
            },
            {
                "product_id": "product-shirt",
                "item_id": "shirt-new",
                "price": 46.66,
                "options": dict(_SHIRT_OPTIONS),
            },
        ],
    }


def test_postwrite_audit_passes_when_each_item_matches_its_catalog_variant() -> None:
    result = audit_tau2_order_items_against_catalog(
        _order_snapshot(),
        _catalog_snapshots(),
    )

    assert result["decision"] == "PASS"
    assert result["blocking_checks"] == []
    assert result["violations"] == []
    assert result["evidence_summary"]["validated_item_count"] == 3


def test_postwrite_audit_detects_tau2_last_variant_price_and_options_corruption() -> None:
    order = _order_snapshot()
    # Reproduce the confirmed pinned Tau2 defect: camera and lamp retain their
    # item IDs/product IDs but inherit the final T-shirt variant's price/options.
    for item in order["items"][:2]:
        item["price"] = 46.66
        item["options"] = dict(_SHIRT_OPTIONS)

    result = audit_tau2_order_items_against_catalog(order, _catalog_snapshots())

    assert result["decision"] == "FAIL"
    assert result["checked"]["item_prices_match_catalog"] == "FAIL"
    assert result["checked"]["item_options_match_catalog"] == "FAIL"
    assert result["evidence_summary"]["violation_count"] == 4
    assert {
        (violation["item_index"], violation["check"])
        for violation in result["violations"]
    } == {
        (0, "item_prices_match_catalog"),
        (0, "item_options_match_catalog"),
        (1, "item_prices_match_catalog"),
        (1, "item_options_match_catalog"),
    }


def test_postwrite_audit_does_not_pass_when_a_product_snapshot_is_missing() -> None:
    result = audit_tau2_order_items_against_catalog(
        _order_snapshot(),
        _catalog_snapshots()[:2],
    )

    assert result["decision"] == "NOT_EVALUABLE"
    assert (
        result["checked"]["every_item_has_a_catalog_product_snapshot"]
        == "NOT_EVALUABLE"
    )
    assert result["evidence_summary"]["not_evaluable_count"] == 1


def test_postwrite_audit_fails_when_item_id_is_absent_from_its_product_catalog() -> None:
    order = _order_snapshot()
    order["items"][0]["item_id"] = "wrong-variant"

    result = audit_tau2_order_items_against_catalog(order, _catalog_snapshots())

    assert result["decision"] == "FAIL"
    assert result["checked"]["item_variants_exist_in_catalog"] == "FAIL"
    assert result["violations"][0]["check"] == "item_variants_exist_in_catalog"


def test_postwrite_audit_treats_malformed_catalog_price_as_not_evaluable() -> None:
    snapshots = _catalog_snapshots()
    snapshots[0]["variants"]["camera-new"]["price"] = None

    result = audit_tau2_order_items_against_catalog(_order_snapshot(), snapshots)

    assert result["decision"] == "NOT_EVALUABLE"
    assert result["checked"]["item_prices_match_catalog"] == "NOT_EVALUABLE"
    assert result["checked"]["item_options_match_catalog"] == "PASS"


def test_postwrite_audit_compares_prices_to_cents_and_options_by_mapping_value() -> None:
    order = _order_snapshot()
    order["items"][0]["price"] = 466.750000
    order["items"][0]["options"] = {
        "color": "black",
        "waterproof": "yes",
        "resolution": "4K",
    }

    result = audit_tau2_order_items_against_catalog(order, _catalog_snapshots())

    assert result["decision"] == "PASS"


def _run_cli(
    tmp_path: Path, order: dict, catalogs: list[dict]
) -> tuple[subprocess.CompletedProcess[str], dict]:
    input_path = tmp_path / "postwrite-audit.json"
    input_path.write_text(
        json.dumps(
            {
                "order_snapshot": order,
                "product_snapshots": catalogs,
            }
        ),
        encoding="utf-8",
    )
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "audit_tau2_order_postwrite.py"
    )
    completed = subprocess.run(
        [sys.executable, str(script_path), "--input", str(input_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed, json.loads(completed.stdout)


def test_postwrite_audit_cli_returns_zero_for_pass(tmp_path: Path) -> None:
    completed, result = _run_cli(tmp_path, _order_snapshot(), _catalog_snapshots())

    assert completed.returncode == 0
    assert result["decision"] == "PASS"


def test_postwrite_audit_cli_returns_one_for_catalog_mismatch(tmp_path: Path) -> None:
    order = _order_snapshot()
    order["items"][0]["price"] = 46.66
    order["items"][0]["options"] = dict(_SHIRT_OPTIONS)

    completed, result = _run_cli(tmp_path, order, _catalog_snapshots())

    assert completed.returncode == 1
    assert result["decision"] == "FAIL"


def test_postwrite_audit_cli_returns_two_when_evidence_is_incomplete(tmp_path: Path) -> None:
    completed, result = _run_cli(tmp_path, _order_snapshot(), _catalog_snapshots()[:2])

    assert completed.returncode == 2
    assert result["decision"] == "NOT_EVALUABLE"
