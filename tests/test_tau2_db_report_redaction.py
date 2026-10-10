from __future__ import annotations

import copy

import pytest

from scripts.redact_tau2_db_report import redact_report


def _report() -> dict:
    order = {
        "order_id": "#W2378156",
        "user_id": "synthetic-user-123",
        "address": {"address1": "123 Test St", "city": "Test City", "zip": "12345"},
        "status": "delivered",
        "items": [
            {
                "item_id": "item-1",
                "product_id": "product-1",
                "price": 10.0,
                "options": {"color": "blue"},
                "internal_note": "must not be emitted",
            }
        ],
        "fulfillments": [{"tracking_id": ["tracking-secret"]}],
        "payment_history": [{"transaction_type": "payment", "payment_method_id": "card-secret", "amount": 10.0}],
        "exchange_items": None,
        "exchange_new_items": None,
        "exchange_payment_method_id": "card-secret",
        "exchange_price_difference": None,
        "return_items": None,
        "return_payment_method_id": None,
        "cancel_reason": None,
    }
    return {
        "schema_version": "1.0.0",
        "verification_type": "pinned_tau2_retail_database_replay",
        "order_id": "#W2378156",
        "source": {"database_path": "/home/runner/private/path", "database_reader": "RetailDB"},
        "database_evidence": {
            "before": copy.deepcopy(order),
            "after": copy.deepcopy(order),
            "recorded_before": copy.deepcopy(order),
            "recorded_after": copy.deepcopy(order),
            "write_execution_error": "RuntimeError: internal path",
            "full_database_before_sha256": "1" * 64,
            "full_database_after_sha256": "2" * 64,
        },
        "checks": {"example": True},
        "summary": {"passed_checks": 1, "total_checks": 1},
    }


def test_redactor_removes_customer_payment_and_tracking_fields() -> None:
    sanitized = redact_report(_report())
    evidence = sanitized["database_evidence"]

    for key in ("before", "after", "recorded_before", "recorded_after"):
        snapshot = evidence[key]
        assert "address" not in snapshot
        assert "user_id" not in snapshot
        assert "fulfillments" not in snapshot
        assert "payment_history" not in snapshot
        assert "exchange_payment_method_id" not in snapshot
        assert "return_payment_method_id" not in snapshot
        assert "cancel_reason" not in snapshot
        assert snapshot["items"] == [{
            "item_id": "item-1",
            "product_id": "product-1",
            "price": 10.0,
            "options": {"color": "blue"},
        }]

    serialized = str(sanitized)
    for secret in ("synthetic-user-123", "Test St", "card-secret", "tracking-secret", "private/path", "internal path"):
        assert secret not in serialized


def test_redactor_preserves_decision_checks_and_fingerprints() -> None:
    report = _report()
    sanitized = redact_report(report)

    assert sanitized["checks"] == report["checks"]
    assert sanitized["summary"] == report["summary"]
    assert sanitized["database_evidence"]["full_database_before_sha256"] == "1" * 64
    assert sanitized["database_evidence"]["full_database_after_sha256"] == "2" * 64
    assert sanitized["database_evidence"]["write_execution_error_present"] is True
    assert "write_execution_error" not in sanitized["database_evidence"]
    assert sanitized["source"]["database_path"] == "[redacted local path]"
    assert sanitized["artifact_redaction"]["applied"] is True
    assert report["database_evidence"]["before"]["address"]["city"] == "Test City"


def test_redactor_rejects_non_object_snapshots() -> None:
    report = _report()
    report["database_evidence"]["after"] = ["not", "an", "object"]

    with pytest.raises(ValueError, match="order snapshots must be JSON objects"):
        redact_report(report)
