"""Regression tests for independent whole-database mutation detection."""
from __future__ import annotations

import copy
import unittest

from scripts.verify_tau2_independent_db import other_database_entities_unchanged


class OtherDatabaseEntitiesUnchangedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.before = {
            "orders": {
                "target": {"status": "delivered", "items": [{"item_id": "i1"}]},
                "other": {"status": "pending", "user_id": "u1"},
            },
            "products": {"p1": {"name": "Keyboard", "variants": {"v1": {"price": 10}}}},
            "users": {"u1": {"name": "A"}, "u2": {"name": "B"}},
        }

    def test_target_order_can_change_when_everything_else_is_unchanged(self) -> None:
        after = copy.deepcopy(self.before)
        after["orders"]["target"]["status"] = "exchange requested"
        after["orders"]["target"]["exchange_items"] = ["i1"]
        self.assertTrue(other_database_entities_unchanged(self.before, after, "target"))

    def test_mutation_to_another_order_is_rejected(self) -> None:
        after = copy.deepcopy(self.before)
        after["orders"]["other"]["status"] = "cancelled"
        self.assertFalse(other_database_entities_unchanged(self.before, after, "target"))

    def test_added_or_deleted_order_is_rejected(self) -> None:
        added = copy.deepcopy(self.before)
        added["orders"]["new"] = {"status": "pending"}
        deleted = copy.deepcopy(self.before)
        del deleted["orders"]["other"]
        self.assertFalse(other_database_entities_unchanged(self.before, added, "target"))
        self.assertFalse(other_database_entities_unchanged(self.before, deleted, "target"))

    def test_product_or_user_mutation_is_rejected(self) -> None:
        changed_product = copy.deepcopy(self.before)
        changed_product["products"]["p1"]["variants"]["v1"]["price"] = 11
        changed_user = copy.deepcopy(self.before)
        changed_user["users"]["u2"]["name"] = "Changed"
        self.assertFalse(other_database_entities_unchanged(self.before, changed_product, "target"))
        self.assertFalse(other_database_entities_unchanged(self.before, changed_user, "target"))

    def test_missing_target_or_root_is_rejected(self) -> None:
        missing_target = copy.deepcopy(self.before)
        del missing_target["orders"]["target"]
        missing_root = copy.deepcopy(self.before)
        del missing_root["users"]
        self.assertFalse(other_database_entities_unchanged(self.before, missing_target, "target"))
        self.assertFalse(other_database_entities_unchanged(self.before, missing_root, "target"))


if __name__ == "__main__":
    unittest.main()


class SnapshotEvidenceDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        from scripts.verify_tau2_independent_db import ORDER_KEYS

        self.before = {
            "order_id": "target",
            "user_id": "u1",
            "address": {"city": "Baku"},
            "items": [{"item_id": "old1", "product_id": "p1", "price": 10}],
            "status": "delivered",
            "fulfillments": [],
            "payment_history": [{"transaction_type": "payment", "payment_method_id": "pm1"}],
            "cancel_reason": None,
            "exchange_items": None,
            "exchange_new_items": None,
            "exchange_payment_method_id": None,
            "exchange_price_difference": None,
            "return_items": None,
            "return_payment_method_id": None,
        }
        self.after = copy.deepcopy(self.before)
        self.after.update({
            "status": "exchange requested",
            "exchange_items": ["old1"],
            "exchange_new_items": ["v2"],
            "exchange_payment_method_id": "pm1",
            "exchange_price_difference": 5.0,
        })
        self.args = {
            "order_id": "target",
            "payment_method_id": "pm1",
            "item_ids": ["old1"],
            "new_item_ids": ["v2"],
        }
        self.products = {
            "p1": {
                "variants": {
                    "v2": {"price": 15, "available": True},
                },
            },
        }
        self.kwargs = {
            "recorded_before": copy.deepcopy(self.before),
            "recorded_after": copy.deepcopy(self.after),
            "db_before": copy.deepcopy(self.before),
            "db_after": copy.deepcopy(self.after),
            "args": copy.deepcopy(self.args),
            "products": copy.deepcopy(self.products),
            "valid_payment_method_ids": {"pm1"},
            "source_commit_matches_trace": True,
            "write_execution_succeeded": True,
            "other_database_entities_unchanged": True,
        }
        self.assertEqual(set(self.before), ORDER_KEYS)

    def evaluate(self, **overrides):
        from scripts.verify_tau2_independent_db import evaluate_snapshot_evidence

        kwargs = copy.deepcopy(self.kwargs)
        kwargs.update(overrides)
        return evaluate_snapshot_evidence(**kwargs)

    def test_valid_evidence_is_go(self) -> None:
        report = self.evaluate()
        self.assertEqual(report["decision"], "GO")
        self.assertEqual(report["summary"]["passed_checks"], report["summary"]["total_checks"])

    def test_each_top_level_gate_fails_closed(self) -> None:
        failures = [
            {"source_commit_matches_trace": False},
            {"write_execution_succeeded": False},
            {"other_database_entities_unchanged": False},
            {"valid_payment_method_ids": {"another-method"}},
        ]
        for override in failures:
            with self.subTest(override=override):
                self.assertEqual(self.evaluate(**override)["decision"], "NO_GO")

    def test_recorded_and_database_state_disagreement_fails_closed(self) -> None:
        changed_before = copy.deepcopy(self.before)
        changed_before["address"]["city"] = "Elsewhere"
        changed_after = copy.deepcopy(self.after)
        changed_after["exchange_price_difference"] = -999
        self.assertEqual(
            self.evaluate(db_before=changed_before)["decision"], "NO_GO"
        )
        self.assertEqual(
            self.evaluate(recorded_after=changed_after)["decision"], "NO_GO"
        )

    def test_wrong_price_or_transition_fails_closed(self) -> None:
        wrong_price = copy.deepcopy(self.after)
        wrong_price["exchange_price_difference"] = -16.63
        wrong_status = copy.deepcopy(self.after)
        wrong_status["status"] = "delivered"
        self.assertEqual(self.evaluate(db_after=wrong_price)["decision"], "NO_GO")
        self.assertEqual(self.evaluate(db_after=wrong_status)["decision"], "NO_GO")

    def test_unrelated_order_field_mutation_fails_closed(self) -> None:
        changed = copy.deepcopy(self.after)
        changed["address"]["city"] = "Elsewhere"
        self.assertEqual(self.evaluate(db_after=changed)["decision"], "NO_GO")
