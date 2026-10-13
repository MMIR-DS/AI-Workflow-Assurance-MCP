from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from ai_workflow_assurance_mcp.tau2_postwrite import (
    audit_tau2_benchmark_result_postwrite,
    audit_tau2_order_items_against_catalog,
    audit_tau2_trace_postwrite,
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


def test_postwrite_audit_accepts_catalog_snapshots_keyed_by_product_id() -> None:
    keyed_catalogs = {
        snapshot["product_id"]: {
            key: value for key, value in snapshot.items() if key != "product_id"
        }
        for snapshot in _catalog_snapshots()
    }

    result = audit_tau2_order_items_against_catalog(_order_snapshot(), keyed_catalogs)

    assert result["decision"] == "PASS"
    assert result["evidence_summary"]["catalog_product_count"] == 3
    assert result["evidence_summary"]["validated_item_count"] == 3


def test_postwrite_audit_does_not_override_conflicting_product_id_in_keyed_snapshot() -> None:
    catalogs = _catalog_snapshots()
    keyed_catalogs = {
        "product-camera": {**catalogs[0], "product_id": "different-product"},
        "product-lamp": catalogs[1],
        "product-shirt": catalogs[2],
    }

    result = audit_tau2_order_items_against_catalog(_order_snapshot(), keyed_catalogs)

    assert result["decision"] == "NOT_EVALUABLE"
    assert result["checked"]["every_item_has_a_catalog_product_snapshot"] == "NOT_EVALUABLE"


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
    # Only the unaffected shirt matches its catalog price and options completely.
    assert result["evidence_summary"]["validated_item_count"] == 1
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
    # The camera's price is unknown, so only the lamp and shirt are fully validated.
    assert result["evidence_summary"]["validated_item_count"] == 2


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


def _trace_with_write(
    order: dict,
    catalogs: list[dict],
    *,
    postwrite_read: dict | None = None,
    blocked: bool = False,
) -> list[dict]:
    trajectory: list[dict] = []
    for index, catalog in enumerate(catalogs):
        call_id = f"product-read-{index}"
        trajectory.append(
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": call_id,
                        "name": "get_product_details",
                        "arguments": {"product_id": catalog["product_id"]},
                    }
                ],
            }
        )
        trajectory.append(
            {
                "role": "tool",
                "id": call_id,
                "content": json.dumps(catalog),
                "error": False,
            }
        )

    trajectory.append(
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "pending-items-write",
                    "name": "modify_pending_order_items",
                    "arguments": {
                        "order_id": order["order_id"],
                        "item_ids": ["old-a", "old-b", "old-c"],
                        "new_item_ids": ["camera-new", "lamp-new", "shirt-new"],
                        "payment_method_id": "credit_card_test",
                    },
                }
            ],
        }
    )
    trajectory.append(
        {
            "role": "tool",
            "id": "pending-items-write",
            "content": (
                "AWA_PREWRITE_NO_GO: disabled"
                if blocked
                else json.dumps(order)
            ),
            "error": blocked,
        }
    )

    if postwrite_read is not None:
        trajectory.append(
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "postwrite-order-read",
                        "name": "get_order_details",
                        "arguments": {"order_id": order["order_id"]},
                    }
                ],
            }
        )
        trajectory.append(
            {
                "role": "tool",
                "id": "postwrite-order-read",
                "content": json.dumps(postwrite_read),
                "error": False,
            }
        )
    return trajectory


def test_trace_audit_extracts_write_result_and_catalog_snapshots() -> None:
    trajectory = _trace_with_write(_order_snapshot(), _catalog_snapshots())

    result = audit_tau2_trace_postwrite(trajectory, "#W9348897")

    assert result["decision"] == "PASS"
    assert result["evidence_summary"]["write_call_id"] == "pending-items-write"
    assert result["evidence_summary"]["post_write_snapshot_source"] == "successful_write_result"
    assert result["evidence_summary"]["catalog_product_count"] == 3


def test_trace_audit_rejects_duplicate_tool_call_ids_even_when_one_result_exists() -> None:
    trajectory = _trace_with_write(_order_snapshot(), _catalog_snapshots())
    # Two product-read calls share an ID, so the single tool result cannot be
    # unambiguously attributed to either call.
    trajectory.insert(
        1,
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "product-read-0",
                    "name": "get_product_details",
                    "arguments": {"product_id": "product-camera"},
                }
            ],
        },
    )

    result = audit_tau2_trace_postwrite(trajectory, "#W9348897")

    assert result["decision"] == "NOT_EVALUABLE"
    assert "product-camera" in result["evidence_summary"]["catalog_product_ids_missing"]


def test_trace_audit_rejects_ambiguous_write_call_id() -> None:
    trajectory = _trace_with_write(_order_snapshot(), _catalog_snapshots())
    # Reuse the same ID for a later write attempt and its tool result. The auditor
    # must not accept either result as authoritative state for the target order.
    trajectory.extend(
        [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "pending-items-write",
                        "name": "modify_pending_order_items",
                        "arguments": {
                            "order_id": "#W9348897",
                            "item_ids": ["old-a"],
                            "new_item_ids": ["camera-new"],
                            "payment_method_id": "credit_card_test",
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "id": "pending-items-write",
                "content": json.dumps(_order_snapshot()),
                "error": False,
            },
        ]
    )

    result = audit_tau2_trace_postwrite(trajectory, "#W9348897")

    assert result["decision"] == "NOT_EVALUABLE"
    assert result["blocking_checks"] == ["successful_postwrite_order_snapshot_available"]
    assert result["evidence_summary"]["latest_write_outcome"] == "missing_result"


def test_trace_audit_rejects_duplicate_tool_results_for_same_call_id() -> None:
    trajectory = _trace_with_write(_order_snapshot(), _catalog_snapshots())
    # A duplicate result makes the ID-to-result relationship ambiguous.
    trajectory.insert(
        2,
        {
            "role": "tool",
            "id": "product-read-0",
            "content": json.dumps(_catalog_snapshots()[0]),
            "error": False,
        },
    )

    result = audit_tau2_trace_postwrite(trajectory, "#W9348897")

    assert result["decision"] == "NOT_EVALUABLE"
    assert "product-camera" in result["evidence_summary"]["catalog_product_ids_missing"]


def test_trace_audit_returns_not_evaluable_for_malformed_message_records() -> None:
    trajectory = _trace_with_write(_order_snapshot(), _catalog_snapshots())
    trajectory.append({"role": "assistant", "tool_calls": "not-a-list"})

    result = audit_tau2_trace_postwrite(trajectory, "#W9348897")

    assert result["decision"] == "NOT_EVALUABLE"
    assert result["blocking_checks"] == ["trajectory_messages_are_well_formed"]


def test_trace_audit_fails_on_corrupted_multi_item_write_result() -> None:
    order = _order_snapshot()
    for item in order["items"][:2]:
        item["price"] = 46.66
        item["options"] = dict(_SHIRT_OPTIONS)
    trajectory = _trace_with_write(order, _catalog_snapshots())

    result = audit_tau2_trace_postwrite(trajectory, "#W9348897")

    assert result["decision"] == "FAIL"
    assert result["checked"]["item_prices_match_catalog"] == "FAIL"
    assert result["checked"]["item_options_match_catalog"] == "FAIL"


def test_trace_audit_prefers_order_read_after_write_result() -> None:
    write_result = _order_snapshot()
    later_read = _order_snapshot()
    later_read["items"][0]["price"] = 46.66
    later_read["items"][0]["options"] = dict(_SHIRT_OPTIONS)
    trajectory = _trace_with_write(
        write_result,
        _catalog_snapshots(),
        postwrite_read=later_read,
    )

    result = audit_tau2_trace_postwrite(trajectory, "#W9348897")

    assert result["decision"] == "FAIL"
    assert (
        result["evidence_summary"]["post_write_snapshot_source"]
        == "get_order_details_after_latest_write_attempt"
    )


def test_trace_audit_returns_not_evaluable_when_write_was_blocked() -> None:
    trajectory = _trace_with_write(
        _order_snapshot(),
        _catalog_snapshots(),
        blocked=True,
    )

    result = audit_tau2_trace_postwrite(trajectory, "#W9348897")

    assert result["decision"] == "NOT_EVALUABLE"
    assert result["blocking_checks"] == ["successful_postwrite_order_snapshot_available"]


def test_trace_audit_returns_not_evaluable_when_catalog_snapshot_is_missing() -> None:
    trajectory = _trace_with_write(_order_snapshot(), _catalog_snapshots()[:2])

    result = audit_tau2_trace_postwrite(trajectory, "#W9348897")

    assert result["decision"] == "NOT_EVALUABLE"
    assert result["evidence_summary"]["catalog_product_ids_missing"] == ["product-shirt"]


def _run_trace_cli(
    tmp_path: Path, trajectory: list[dict], order_id: str
) -> tuple[subprocess.CompletedProcess[str], dict]:
    input_path = tmp_path / "tau2-trace.json"
    input_path.write_text(
        json.dumps({"trajectory": trajectory, "order_id": order_id}),
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


def test_postwrite_audit_cli_accepts_tau2_trace_input(tmp_path: Path) -> None:
    trajectory = _trace_with_write(_order_snapshot(), _catalog_snapshots())

    completed, result = _run_trace_cli(tmp_path, trajectory, "#W9348897")

    assert completed.returncode == 0
    assert result["decision"] == "PASS"
    assert result["evidence_summary"]["post_write_snapshot_source"] == "successful_write_result"


def test_postwrite_audit_cli_fails_on_corrupted_tau2_trace(tmp_path: Path) -> None:
    order = _order_snapshot()
    for item in order["items"][:2]:
        item["price"] = 46.66
        item["options"] = dict(_SHIRT_OPTIONS)
    trajectory = _trace_with_write(order, _catalog_snapshots())

    completed, result = _run_trace_cli(tmp_path, trajectory, "#W9348897")

    assert completed.returncode == 1
    assert result["decision"] == "FAIL"


def _append_blocked_write_attempt(
    trajectory: list[dict], order_id: str
) -> list[dict]:
    trajectory = list(trajectory)
    trajectory.extend(
        [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "pending-items-write-2",
                        "name": "modify_pending_order_items",
                        "arguments": {
                            "order_id": order_id,
                            "item_ids": ["old-a"],
                            "new_item_ids": ["camera-new"],
                            "payment_method_id": "credit_card_test",
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "id": "pending-items-write-2",
                "content": "AWA_PREWRITE_NO_GO: disabled",
                "error": True,
            },
        ]
    )
    return trajectory


def test_trace_audit_does_not_reuse_previous_success_after_later_blocked_write() -> None:
    trajectory = _trace_with_write(_order_snapshot(), _catalog_snapshots())
    trajectory = _append_blocked_write_attempt(trajectory, "#W9348897")

    result = audit_tau2_trace_postwrite(trajectory, "#W9348897")

    assert result["decision"] == "NOT_EVALUABLE"
    assert result["blocking_checks"] == [
        "successful_postwrite_order_snapshot_available"
    ]
    assert result["evidence_summary"]["latest_write_outcome"] == "blocked"


def test_trace_audit_accepts_fresh_read_after_later_blocked_write() -> None:
    trajectory = _trace_with_write(_order_snapshot(), _catalog_snapshots())
    trajectory = _append_blocked_write_attempt(trajectory, "#W9348897")
    current_order = _order_snapshot()
    trajectory.extend(
        [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "order-read-after-block",
                        "name": "get_order_details",
                        "arguments": {"order_id": "#W9348897"},
                    }
                ],
            },
            {
                "role": "tool",
                "id": "order-read-after-block",
                "content": json.dumps(current_order),
                "error": False,
            },
        ]
    )

    result = audit_tau2_trace_postwrite(trajectory, "#W9348897")

    assert result["decision"] == "PASS"
    assert (
        result["evidence_summary"]["post_write_snapshot_source"]
        == "get_order_details_after_latest_write_attempt"
    )
    assert result["evidence_summary"]["latest_write_outcome"] == "blocked"


def test_trace_audit_does_not_reuse_catalog_result_from_before_duplicate_call_id() -> None:
    trajectory = _trace_with_write(_order_snapshot(), _catalog_snapshots())
    # Reuse an old call ID but omit its result: a global ID search could accidentally
    # find the earlier successful result and claim the latest catalog evidence is valid.
    trajectory.append(
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "product-read-0",
                    "name": "get_product_details",
                    "arguments": {"product_id": "product-camera"},
                }
            ],
        }
    )

    result = audit_tau2_trace_postwrite(trajectory, "#W9348897")

    assert result["decision"] == "NOT_EVALUABLE"
    assert result["checked"]["every_item_has_a_catalog_product_snapshot"] == "NOT_EVALUABLE"
    assert result["evidence_summary"]["catalog_product_ids_missing"] == ["product-camera"]


def _benchmark_result_with_orders(orders: list[dict]) -> dict:
    return {
        "simulations": [
            {
                "task_id": f"task-{index}",
                "trial": 0,
                "reward_info": {"reward": 1.0},
                "messages": _trace_with_write(order, _catalog_snapshots()),
            }
            for index, order in enumerate(orders)
        ]
    }


def test_benchmark_artifact_audit_passes_all_simulations() -> None:
    first_order = _order_snapshot()
    second_order = _order_snapshot()
    second_order["order_id"] = "#W1234567"
    payload = _benchmark_result_with_orders([first_order, second_order])

    result = audit_tau2_benchmark_result_postwrite(payload)

    assert result["decision"] == "PASS"
    assert result["evidence_summary"]["simulation_count"] == 2
    assert result["evidence_summary"]["order_audit_count"] == 2
    assert result["evidence_summary"]["fail_count"] == 0
    assert result["evidence_summary"]["benchmark_reward_used_as_integrity_oracle"] is False
    assert [item["decision"] for item in result["simulation_results"]] == [
        "PASS",
        "PASS",
    ]


def test_benchmark_artifact_audit_detects_corruption_even_when_reward_is_one() -> None:
    valid_order = _order_snapshot()
    corrupted_order = _order_snapshot()
    for item in corrupted_order["items"][:2]:
        item["price"] = 46.66
        item["options"] = dict(_SHIRT_OPTIONS)
    payload = _benchmark_result_with_orders([valid_order, corrupted_order])

    result = audit_tau2_benchmark_result_postwrite(payload)

    assert result["decision"] == "FAIL"
    assert result["simulation_results"][0]["decision"] == "PASS"
    assert result["simulation_results"][1]["decision"] == "FAIL"
    assert result["simulation_results"][1]["order_audits"][0]["decision"] == "FAIL"
    # reward_info is intentionally ignored as a data-integrity oracle.
    assert payload["simulations"][1]["reward_info"]["reward"] == 1.0
    assert result["evidence_summary"]["benchmark_reward_used_as_integrity_oracle"] is False


def test_benchmark_artifact_audit_is_not_evaluable_without_a_target_write() -> None:
    payload = {
        "simulations": [
            {
                "task_id": "read-only-task",
                "messages": [{"role": "assistant", "content": "No write operation."}],
            }
        ]
    }

    result = audit_tau2_benchmark_result_postwrite(payload)

    assert result["decision"] == "NOT_EVALUABLE"
    assert result["simulation_results"][0]["decision"] == "NOT_APPLICABLE"
    assert result["evidence_summary"]["simulations_without_matching_write"] == 1
    assert result["evidence_summary"]["not_applicable_simulation_count"] == 1
    assert result["evidence_summary"]["not_evaluable_count"] == 0
    assert "no_applicable_write_simulations" in result["blocking_checks"]




def test_benchmark_artifact_excludes_read_only_tasks_from_write_audit_aggregate() -> None:
    payload = _benchmark_result_with_orders([_order_snapshot()])
    payload["simulations"].append(
        {
            "task_id": "read-only-task",
            "messages": [{"role": "assistant", "content": "Read-only result; no write."}],
        }
    )

    result = audit_tau2_benchmark_result_postwrite(payload)

    assert result["decision"] == "PASS"
    assert result["simulation_results"][0]["decision"] == "PASS"
    assert result["simulation_results"][1]["decision"] == "NOT_APPLICABLE"
    assert result["evidence_summary"]["applicable_simulation_count"] == 1
    assert result["evidence_summary"]["not_applicable_simulation_count"] == 1
    assert result["evidence_summary"]["not_evaluable_count"] == 0

def test_benchmark_artifact_marks_missing_messages_as_not_well_formed() -> None:
    payload = _benchmark_result_with_orders([_order_snapshot()])
    payload["simulations"].append({"task_id": "missing-messages"})

    result = audit_tau2_benchmark_result_postwrite(payload)

    assert result["decision"] == "NOT_EVALUABLE"
    assert result["checked"]["benchmark_simulations_are_well_formed"] == "NOT_EVALUABLE"
    assert result["simulation_results"][0]["decision"] == "PASS"
    assert result["simulation_results"][1]["decision"] == "NOT_EVALUABLE"


def test_benchmark_artifact_marks_malformed_tool_calls_as_not_well_formed() -> None:
    payload = _benchmark_result_with_orders([_order_snapshot()])
    payload["simulations"][0]["messages"].append(
        {"role": "assistant", "tool_calls": "not-a-list"}
    )

    result = audit_tau2_benchmark_result_postwrite(payload)

    assert result["decision"] == "NOT_EVALUABLE"
    assert result["checked"]["benchmark_simulations_are_well_formed"] == "NOT_EVALUABLE"
    assert result["simulation_results"][0]["decision"] == "NOT_EVALUABLE"


def test_benchmark_artifact_audit_can_select_one_simulation() -> None:
    valid_order = _order_snapshot()
    corrupted_order = _order_snapshot()
    for item in corrupted_order["items"][:2]:
        item["price"] = 46.66
        item["options"] = dict(_SHIRT_OPTIONS)
    payload = _benchmark_result_with_orders([valid_order, corrupted_order])

    result = audit_tau2_benchmark_result_postwrite(payload, simulation_index=0)

    assert result["decision"] == "PASS"
    assert result["evidence_summary"]["simulation_count"] == 1
    assert result["evidence_summary"]["selected_simulation_indices"] == [0]


def _run_benchmark_cli(
    tmp_path: Path, payload: dict, *, extra_args: list[str] | None = None
) -> tuple[subprocess.CompletedProcess[str], dict]:
    input_path = tmp_path / "tau2-benchmark-result.json"
    input_path.write_text(json.dumps(payload), encoding="utf-8")
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "audit_tau2_order_postwrite.py"
    )
    command = [sys.executable, str(script_path), "--input", str(input_path)]
    if extra_args:
        command.extend(extra_args)
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed, json.loads(completed.stdout)


def test_postwrite_audit_cli_accepts_complete_tau2_benchmark_artifact(
    tmp_path: Path,
) -> None:
    payload = _benchmark_result_with_orders([_order_snapshot()])

    completed, result = _run_benchmark_cli(tmp_path, payload)

    assert completed.returncode == 0
    assert result["decision"] == "PASS"
    assert result["evidence_summary"]["simulation_count"] == 1


def test_postwrite_audit_cli_accepts_simulation_index_for_full_artifact(
    tmp_path: Path,
) -> None:
    valid_order = _order_snapshot()
    corrupted_order = _order_snapshot()
    for item in corrupted_order["items"][:2]:
        item["price"] = 46.66
        item["options"] = dict(_SHIRT_OPTIONS)
    payload = _benchmark_result_with_orders([valid_order, corrupted_order])

    completed, result = _run_benchmark_cli(
        tmp_path,
        payload,
        extra_args=["--simulation-index", "1"],
    )

    assert completed.returncode == 1
    assert result["decision"] == "FAIL"
    assert result["evidence_summary"]["selected_simulation_indices"] == [1]


def test_benchmark_artifact_with_empty_simulations_is_not_evaluable() -> None:
    result = audit_tau2_benchmark_result_postwrite({"simulations": []})

    assert result["decision"] == "NOT_EVALUABLE"
    assert result["blocking_checks"] == ["at_least_one_simulation_selected"]
    assert result["evidence_summary"]["not_evaluable_count"] == 1
