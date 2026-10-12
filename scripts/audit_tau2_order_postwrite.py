"""Audit a Tau2 order snapshot against its product/variant catalog snapshots.

Input JSON may contain one of:
- "order_snapshot" plus "product_snapshots" for an explicit snapshot audit;
- "trajectory" plus "order_id" for a single Tau2 message trace; or
- a full Tau2 benchmark artifact with a "simulations" list, auditing every matching
  write/order in each simulation (or one zero-based simulation index).

Exit codes: 0=PASS, 1=FAIL, 2=NOT_EVALUABLE.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from ai_workflow_assurance_mcp.tau2_postwrite import (
    audit_tau2_benchmark_result_postwrite,
    audit_tau2_order_items_against_catalog,
    audit_tau2_trace_postwrite,
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
        help="JSON file containing snapshots, a trajectory, or a full Tau2 benchmark artifact",
    )
    parser.add_argument(
        "--write-tool-name",
        default=None,
        help="Target write tool name (default: modify_pending_order_items)",
    )
    parser.add_argument(
        "--simulation-index",
        type=int,
        default=None,
        help="Optional zero-based simulation index when the input has a simulations list",
    )
    args = parser.parse_args(argv)

    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result = _not_evaluable(f"Could not read valid JSON input: {exc}")
    else:
        if not isinstance(payload, dict):
            result = _not_evaluable("The top-level JSON value must be an object.")
        elif "simulations" in payload:
            result = audit_tau2_benchmark_result_postwrite(
                payload,
                write_tool_name=(
                    args.write_tool_name
                    or payload.get("write_tool_name", "modify_pending_order_items")
                ),
                simulation_index=args.simulation_index,
            )
        elif "trajectory" in payload:
            result = audit_tau2_trace_postwrite(
                payload.get("trajectory"),
                payload.get("order_id"),
                write_tool_name=(
                    args.write_tool_name
                    or payload.get("write_tool_name", "modify_pending_order_items")
                ),
            )
        else:
            result = audit_tau2_order_items_against_catalog(
                payload.get("order_snapshot"),
                payload.get("product_snapshots"),
            )

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return {"PASS": 0, "FAIL": 1, "NOT_EVALUABLE": 2}[result["decision"]]


if __name__ == "__main__":
    raise SystemExit(main())
