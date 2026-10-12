"""Audit a Tau2 order snapshot against its product/variant catalog snapshots.

Input JSON shape:
{
  "order_snapshot": {"order_id": "...", "items": [...]},
  "product_snapshots": [{"product_id": "...", "variants": {...}}]
}

Exit codes: 0=PASS, 1=FAIL, 2=NOT_EVALUABLE.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from ai_workflow_assurance_mcp.tau2_postwrite import (
    audit_tau2_order_items_against_catalog,
)


def _not_evaluable(detail: str) -> dict[str, Any]:
    return {
        "decision": "NOT_EVALUABLE",
        "checked": {},
        "blocking_checks": ["input_json_is_valid"],
        "violations": [],
        "not_evaluable": [{"check": "input_json_is_valid", "detail": detail}],
        "evidence_summary": {
            "order_id": None,
            "order_item_count": None,
            "catalog_product_count": 0,
            "validated_item_count": 0,
            "violation_count": 0,
            "not_evaluable_count": 1,
        },
        "scope": "tau2_order_snapshot_vs_product_catalog_not_production_data_integrity_proof",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="JSON file containing order_snapshot and product_snapshots",
    )
    args = parser.parse_args(argv)

    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result = _not_evaluable(f"Could not read valid JSON input: {exc}")
    else:
        if not isinstance(payload, dict):
            result = _not_evaluable("The top-level JSON value must be an object.")
        else:
            result = audit_tau2_order_items_against_catalog(
                payload.get("order_snapshot"),
                payload.get("product_snapshots"),
            )

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return {"PASS": 0, "FAIL": 1, "NOT_EVALUABLE": 2}[result["decision"]]


if __name__ == "__main__":
    raise SystemExit(main())
