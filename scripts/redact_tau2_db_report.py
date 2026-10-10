"""Redact sensitive order details from replay reports before public artifact upload."""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

ORDER_FIELDS = (
    "order_id",
    "status",
    "items",
    "exchange_items",
    "exchange_new_items",
    "exchange_price_difference",
)
ITEM_FIELDS = ("item_id", "product_id", "price", "options")
REMOVED_ORDER_FIELDS = (
    "address",
    "user_id",
    "fulfillments",
    "payment_history",
    "exchange_payment_method_id",
    "return_payment_method_id",
    "cancel_reason",
    "return_items",
    "return_payment_method_id",
)


def _safe_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        return {}
    return {key: copy.deepcopy(item[key]) for key in ITEM_FIELDS if key in item}


def _safe_order_projection(order: Any) -> dict[str, Any]:
    if not isinstance(order, dict):
        raise ValueError("order snapshots must be JSON objects.")
    result = {key: copy.deepcopy(order[key]) for key in ORDER_FIELDS if key in order}
    if "items" in order:
        if not isinstance(order["items"], list):
            raise ValueError("order snapshot items must be a list when present.")
        result["items"] = [_safe_item(item) for item in order["items"]]
    return result


def redact_report(report: dict[str, Any]) -> dict[str, Any]:
    """Return a sanitized copy while retaining checks, counts, and fingerprints."""
    if not isinstance(report, dict):
        raise ValueError("report must be a JSON object.")
    sanitized = copy.deepcopy(report)
    evidence = sanitized.get("database_evidence")
    source = sanitized.get("source")
    if not isinstance(evidence, dict) or not isinstance(source, dict):
        raise ValueError("report must include source and database_evidence objects.")

    for key in ("before", "after", "recorded_before", "recorded_after"):
        if key in evidence:
            evidence[key] = _safe_order_projection(evidence[key])

    source["database_path"] = "[redacted local path]"
    if "write_execution_error" in evidence:
        error = evidence.pop("write_execution_error")
        evidence["write_execution_error_present"] = error is not None

    evidence["redaction"] = {
        "applied": True,
        "policy": "order-state-allowlist-v1",
        "removed_order_fields": list(REMOVED_ORDER_FIELDS),
        "removed_source_fields": ["database_path"],
        "raw_order_snapshots_included": False,
    }
    sanitized["artifact_redaction"] = {
        "applied": True,
        "policy": "order-state-allowlist-v1",
        "purpose": "minimize customer and payment details in public CI artifacts",
    }
    return sanitized


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Verifier report JSON.")
    parser.add_argument("--output", required=True, type=Path, help="Sanitized report JSON.")
    args = parser.parse_args()
    try:
        report = json.loads(args.input.read_text(encoding="utf-8"))
        sanitized = redact_report(report)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(sanitized, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "artifact_redaction": sanitized["artifact_redaction"],
        "output": str(args.output),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
