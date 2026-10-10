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
