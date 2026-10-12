"""Independent post-write invariants for Tau2 retail order snapshots.

This audit compares persisted order rows with their authoritative product/variant
snapshots. It is intentionally separate from Tau2's replay-based reward/DB oracle.
"""
from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any


def _field(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _money(value: Any) -> Decimal | None:
    """Normalize a JSON-style numeric price to cents without accepting booleans."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    try:
        amount = Decimal(str(value))
        if not amount.is_finite():
            return None
        return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return None


def _catalog_entries(product_snapshots: Any) -> list[Any] | None:
    """Accept a list of product snapshots or a mapping of product IDs to snapshots."""
    if isinstance(product_snapshots, (list, tuple)):
        return list(product_snapshots)
    if isinstance(product_snapshots, Mapping):
        if _field(product_snapshots, "product_id") and isinstance(
            _field(product_snapshots, "variants"), Mapping
        ):
            return [product_snapshots]
        return list(product_snapshots.values())
    return None


def audit_tau2_order_items_against_catalog(
    order_snapshot: Any,
    product_snapshots: Any,
) -> dict[str, Any]:
    """Audit each order item's product, variant, price, and options against catalog data.

    Decision semantics:
    - PASS: all order items are fully evaluable and match their catalog variants.
    - FAIL: at least one definite item/catalog invariant is violated.
    - NOT_EVALUABLE: no definite mismatch was found, but evidence is missing/malformed.
      A caller must not treat NOT_EVALUABLE as a successful audit.

    Product snapshots use Tau2's get_product_details shape:
    {product_id, variants: {item_id: {item_id, price, options, ...}}}.
    """
    order_id = _field(order_snapshot, "order_id")
    items = _field(order_snapshot, "items")
    product_entries = _catalog_entries(product_snapshots)

    checked: dict[str, str] = {
        "order_snapshot_is_well_formed": "PASS",
        "catalog_snapshots_are_well_formed": "PASS",
        "every_item_has_a_catalog_product_snapshot": "PASS",
        "item_variants_exist_in_catalog": "PASS",
        "item_prices_match_catalog": "PASS",
        "item_options_match_catalog": "PASS",
    }
    violations: list[dict[str, Any]] = []
    not_evaluable: list[dict[str, Any]] = []
    validated_item_count = 0

    def set_status(check: str, status: str) -> None:
        current = checked[check]
        if current == "FAIL":
            return
        if status == "FAIL" or (status == "NOT_EVALUABLE" and current != "FAIL"):
            checked[check] = status

    def record_unknown(
        check: str,
        detail: str,
        *,
        item_index: int | None = None,
        product_id: str | None = None,
        item_id: str | None = None,
    ) -> None:
        set_status(check, "NOT_EVALUABLE")
        entry: dict[str, Any] = {"check": check, "detail": detail}
        if item_index is not None:
            entry["item_index"] = item_index
        if product_id is not None:
            entry["product_id"] = product_id
        if item_id is not None:
            entry["item_id"] = item_id
        not_evaluable.append(entry)

    def record_violation(
        check: str,
        *,
        item_index: int,
        product_id: str,
        item_id: str,
        expected: Any,
        actual: Any,
    ) -> None:
        set_status(check, "FAIL")
        violations.append(
            {
                "check": check,
                "item_index": item_index,
                "product_id": product_id,
                "item_id": item_id,
                "expected": expected,
                "actual": actual,
            }
        )

    order_shape_valid = (
        isinstance(order_id, str)
        and bool(order_id.strip())
        and isinstance(items, (list, tuple))
        and bool(items)
    )
    if not order_shape_valid:
        record_unknown(
            "order_snapshot_is_well_formed",
            "Expected a non-empty order_id and a non-empty items list.",
        )

    if product_entries is None:
        record_unknown(
            "catalog_snapshots_are_well_formed",
            "Expected a product snapshot, a sequence of snapshots, or a product-ID mapping.",
        )
        product_entries = []

    products_by_id: dict[str, Mapping[str, Any]] = {}
    seen_product_ids: set[str] = set()
    ambiguous_product_ids: set[str] = set()
    for product in product_entries:
        product_id = _field(product, "product_id")
        variants = _field(product, "variants")
        if not (
            isinstance(product, Mapping)
            and isinstance(product_id, str)
            and product_id
            and isinstance(variants, Mapping)
        ):
            record_unknown(
                "catalog_snapshots_are_well_formed",
                "Each product snapshot must contain product_id and a variants mapping.",
            )
            continue
        if product_id in seen_product_ids:
            ambiguous_product_ids.add(product_id)
            products_by_id.pop(product_id, None)
            record_unknown(
                "catalog_snapshots_are_well_formed",
                "Duplicate product_id snapshots are ambiguous.",
                product_id=product_id,
            )
            continue
        seen_product_ids.add(product_id)
        products_by_id[product_id] = product

    # A product duplicated anywhere in the input remains ambiguous, even if a third
    # entry with the same ID appears later.
    for product_id in ambiguous_product_ids:
        products_by_id.pop(product_id, None)

    if isinstance(items, (list, tuple)):
        for index, item in enumerate(items):
            product_id = _field(item, "product_id")
            item_id = _field(item, "item_id")
            actual_price_value = _field(item, "price")
            actual_options = _field(item, "options")

            if not isinstance(item, Mapping):
                record_unknown(
                    "order_snapshot_is_well_formed",
                    "An order item is not an object/mapping.",
                    item_index=index,
                )
                continue
            if not (
                isinstance(product_id, str)
                and product_id
                and isinstance(item_id, str)
                and item_id
            ):
                record_unknown(
                    "order_snapshot_is_well_formed",
                    "An order item is missing a non-empty product_id or item_id.",
                    item_index=index,
                )
                continue

            product = products_by_id.get(product_id)
            if product is None:
                record_unknown(
                    "every_item_has_a_catalog_product_snapshot",
                    "No unique, valid catalog snapshot was supplied for this product_id.",
                    item_index=index,
                    product_id=product_id,
                    item_id=item_id,
                )
                continue

            variants = _field(product, "variants")
            if not isinstance(variants, Mapping):
                record_unknown(
                    "catalog_snapshots_are_well_formed",
                    "The product's variants field is not a mapping.",
                    item_index=index,
                    product_id=product_id,
                    item_id=item_id,
                )
                continue

            variant = variants.get(item_id)
            if not isinstance(variant, Mapping):
                record_violation(
                    "item_variants_exist_in_catalog",
                    item_index=index,
                    product_id=product_id,
                    item_id=item_id,
                    expected="variant present under this product_id",
                    actual="variant missing",
                )
                continue

            if _field(variant, "item_id") != item_id:
                record_violation(
                    "item_variants_exist_in_catalog",
                    item_index=index,
                    product_id=product_id,
                    item_id=item_id,
                    expected=item_id,
                    actual=_field(variant, "item_id"),
                )
                continue

            expected_price = _money(_field(variant, "price"))
            if expected_price is None:
                record_unknown(
                    "item_prices_match_catalog",
                    "Catalog variant price is missing or not a finite numeric amount.",
                    item_index=index,
                    product_id=product_id,
                    item_id=item_id,
                )
            else:
                actual_price = _money(actual_price_value)
                if actual_price is None:
                    record_violation(
                        "item_prices_match_catalog",
                        item_index=index,
                        product_id=product_id,
                        item_id=item_id,
                        expected=str(expected_price),
                        actual=actual_price_value,
                    )
                elif actual_price != expected_price:
                    record_violation(
                        "item_prices_match_catalog",
                        item_index=index,
                        product_id=product_id,
                        item_id=item_id,
                        expected=str(expected_price),
                        actual=str(actual_price),
                    )

            expected_options = _field(variant, "options")
            if not isinstance(expected_options, Mapping):
                record_unknown(
                    "item_options_match_catalog",
                    "Catalog variant options are missing or not a mapping.",
                    item_index=index,
                    product_id=product_id,
                    item_id=item_id,
                )
            elif not isinstance(actual_options, Mapping):
                record_violation(
                    "item_options_match_catalog",
                    item_index=index,
                    product_id=product_id,
                    item_id=item_id,
                    expected=dict(expected_options),
                    actual=actual_options,
                )
            elif dict(actual_options) != dict(expected_options):
                record_violation(
                    "item_options_match_catalog",
                    item_index=index,
                    product_id=product_id,
                    item_id=item_id,
                    expected=dict(expected_options),
                    actual=dict(actual_options),
                )
            validated_item_count += 1

    if any(status == "FAIL" for status in checked.values()):
        decision = "FAIL"
    elif any(status == "NOT_EVALUABLE" for status in checked.values()):
        decision = "NOT_EVALUABLE"
    else:
        decision = "PASS"

    return {
        "decision": decision,
        "checked": checked,
        "blocking_checks": [
            name for name, status in checked.items() if status != "PASS"
        ],
        "violations": violations,
        "not_evaluable": not_evaluable,
        "evidence_summary": {
            "order_id": order_id if isinstance(order_id, str) else None,
            "order_item_count": len(items) if isinstance(items, (list, tuple)) else None,
            "catalog_product_count": len(products_by_id),
            "validated_item_count": validated_item_count,
            "violation_count": len(violations),
            "not_evaluable_count": len(not_evaluable),
        },
        "scope": "tau2_order_snapshot_vs_product_catalog_not_production_data_integrity_proof",
    }
