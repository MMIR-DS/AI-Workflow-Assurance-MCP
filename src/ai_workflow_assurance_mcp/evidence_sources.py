"""Contracts for read-only evidence-source adapters.

The protocol describes a read-only interface; it does not itself authenticate a
source, enforce operating-system permissions, or authorize production releases.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

MAX_MANIFEST_BYTES = 1_048_576


@dataclass(frozen=True)
class EvidenceEnvelope:
    """Normalized evidence plus explicit provenance and trust-boundary metadata."""

    source_name: str
    source_version: str
    assurance_scope: str
    source_authenticity: str
    release_eligible: bool
    evidence: dict[str, Any]
    collected_at: datetime | None = None

    def __post_init__(self) -> None:
        for field_name in ("source_name", "source_version", "assurance_scope"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string.")
        if self.source_authenticity not in {"not_verified", "verified"}:
            raise ValueError("source_authenticity must be 'not_verified' or 'verified'.")
        if not isinstance(self.release_eligible, bool):
            raise ValueError("release_eligible must be a boolean.")
        if not isinstance(self.evidence, dict):
            raise ValueError("evidence must be a JSON object.")
        if self.collected_at is not None:
            if not isinstance(self.collected_at, datetime) or self.collected_at.tzinfo is None:
                raise ValueError("collected_at must be a timezone-aware datetime or None.")
            if self.collected_at.utcoffset() is None:
                raise ValueError("collected_at must have a valid UTC offset.")
        if self.source_authenticity != "verified" and self.release_eligible:
            raise ValueError("unverified source evidence cannot be release eligible.")
        if self.assurance_scope == "pinned_simulator_replay_evidence_only" and self.release_eligible:
            raise ValueError("simulator replay evidence cannot be release eligible.")


@runtime_checkable
class ReadOnlyEvidenceSource(Protocol):
    """Minimal adapter contract: read evidence; no mutation methods are part of it."""

    def read_evidence(self) -> EvidenceEnvelope:
        """Collect or load a normalized evidence envelope."""


class Tau2ManifestFileSource:
    """Read a known tau2 simulator manifest and return a strict safe projection.

    This adapter is deliberately schema-specific. It rejects unknown check names
    and inconsistent counts, while recursively projecting nested snapshots onto
    an order/item allowlist to avoid passing through unexpected customer fields.
    """

    _required_checks = frozenset({
        "source_code_commit_matches_trace",
        "pre_state_matches_recorded_order_read",
        "write_execution_succeeded",
        "no_other_database_entities_mutated",
        "independent_db_state_matches_recorded_exchange_response",
        "replay_db_payment_profile_and_original_transaction_match",
        "unrelated_order_fields_unchanged_in_database",
        "database_price_recalculation_matches_post_state",
        "database_transition_matches_write_request",
        "tamper_probe_is_detected",
    })
    _order_fields = (
        "order_id",
        "status",
        "exchange_items",
        "exchange_new_items",
        "exchange_price_difference",
    )
    _item_fields = ("item_id", "product_id", "price", "options")
    _redacted_fields = [
        "address",
        "user_id",
        "fulfillments",
        "payment_history",
        "exchange_payment_method_id",
        "return_payment_method_id",
        "cancel_reason",
    ]
    _limitations = [
        "This manifest packages a deterministic replay against a pinned simulator; it is not a snapshot of the original model run's live in-memory database.",
        "The replay report and its source data are not cryptographically authenticated by this adapter.",
        "SHA-256 fingerprints support change detection; they are not digital signatures or proof of provenance.",
        "A successful simulated replay is not evidence of production readiness or general workflow reliability.",
    ]

    def __init__(self, manifest_path: str | Path) -> None:
        self._manifest_path = Path(manifest_path)

    @classmethod
    def _safe_order_projection(cls, order: Any) -> dict[str, Any]:
        if not isinstance(order, dict):
            raise ValueError("database evidence order snapshots must be JSON objects.")
        projection: dict[str, Any] = {}
        for key in ("order_id", "status"):
            if key in order:
                value = order[key]
                if not isinstance(value, str) or len(value) > 256:
                    raise ValueError(f"order snapshot {key} must be a string of at most 256 characters.")
                projection[key] = value
        for key in ("exchange_items", "exchange_new_items"):
            if key in order:
                value = order[key]
                if value is not None and (
                    not isinstance(value, list)
                    or any(not isinstance(item, str) or len(item) > 256 for item in value)
                ):
                    raise ValueError(f"order snapshot {key} must be null or a list of short strings.")
                projection[key] = value
        if "exchange_price_difference" in order:
            value = order["exchange_price_difference"]
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (str, int, float))
                or isinstance(value, str) and len(value) > 64
            ):
                raise ValueError("order snapshot exchange_price_difference has an unsupported value type.")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("order snapshot exchange_price_difference must be finite.")
            projection["exchange_price_difference"] = value
        if "items" in order:
            items = order["items"]
            if not isinstance(items, list):
                raise ValueError("order snapshot items must be a list when present.")
            safe_items = []
            for item in items:
                if not isinstance(item, dict):
                    raise ValueError("order snapshot items must contain JSON objects.")
                safe_item: dict[str, Any] = {}
                for key in ("item_id", "product_id"):
                    if key in item:
                        value = item[key]
                        if not isinstance(value, str) or len(value) > 256:
                            raise ValueError(f"item {key} must be a string of at most 256 characters.")
                        safe_item[key] = value
                if "price" in item:
                    value = item["price"]
                    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                        raise ValueError("item price must be a string or finite number.")
                    if isinstance(value, str) and len(value) > 64:
                        raise ValueError("item price string is too long.")
                    if isinstance(value, float) and not math.isfinite(value):
                        raise ValueError("item price must be finite.")
                    safe_item["price"] = value
                if "options" in item:
                    options = item["options"]
                    if options is not None and (
                        not isinstance(options, list)
                        or any(not isinstance(option, str) or len(option) > 256 for option in options)
                    ):
                        raise ValueError("item options must be null or a list of short strings.")
                    safe_item["options"] = options
                safe_items.append(safe_item)
            projection["items"] = safe_items
        return projection

    def read_evidence(self) -> EvidenceEnvelope:
        try:
            if self._manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
                raise ValueError(
                    f"manifest exceeds the {MAX_MANIFEST_BYTES}-byte size limit."
                )
            manifest = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"could not read a valid JSON manifest: {exc}") from exc
        except (OSError, UnicodeError) as exc:
            raise ValueError(f"could not read a valid JSON manifest: {exc}") from exc
        return self.normalize_manifest(manifest)

    @classmethod
    def normalize_manifest(cls, manifest: Any) -> EvidenceEnvelope:
        """Validate and normalize a supplied manifest object without file I/O."""
        if not isinstance(manifest, dict):
            raise ValueError("manifest must be a JSON object.")
        if manifest.get("schema_version") != "1.0.0":
            raise ValueError("unsupported manifest schema_version.")
        if manifest.get("manifest_type") != "awa-tau2-source-evidence-v1":
            raise ValueError("unsupported manifest_type.")
        if manifest.get("assurance_scope") != "pinned_simulator_replay_evidence_only":
            raise ValueError("unexpected assurance_scope.")
        if manifest.get("production_ready") is not False:
            raise ValueError("tau2 simulator manifest must set production_ready to false.")
        if manifest.get("release_eligible") is not False:
            raise ValueError("tau2 simulator manifest must set release_eligible to false.")

        provenance = manifest.get("source_provenance")
        if not isinstance(provenance, dict):
            raise ValueError("manifest source_provenance must be an object.")
        source_version = provenance.get("checked_out_commit")
        if (
            not isinstance(source_version, str)
            or len(source_version) != 40
            or any(char not in "0123456789abcdef" for char in source_version)
        ):
            raise ValueError("manifest checked-out source commit must be 40 lowercase hexadecimal characters.")
        if provenance.get("source_authenticity") != "not_verified":
            raise ValueError("tau2 simulator manifest must remain explicitly unverified.")

        decision = manifest.get("decision")
        if not isinstance(decision, str) or decision not in {"GO", "HOLD", "NO_GO"}:
            raise ValueError("manifest decision must be GO, HOLD, or NO_GO.")
        checks = manifest.get("checks")
        if not isinstance(checks, dict) or set(checks) != cls._required_checks:
            raise ValueError("manifest checks must contain exactly the supported tau2 check names.")
        if any(not isinstance(value, bool) for value in checks.values()):
            raise ValueError("every manifest check must be a boolean.")
        summary = manifest.get("summary")
        if not isinstance(summary, dict):
            raise ValueError("manifest summary must be an object.")
        passed_checks = summary.get("passed_checks")
        total_checks = summary.get("total_checks")
        if (
            isinstance(passed_checks, bool)
            or not isinstance(passed_checks, int)
            or isinstance(total_checks, bool)
            or not isinstance(total_checks, int)
            or total_checks != len(checks)
            or passed_checks != sum(checks.values())
        ):
            raise ValueError("manifest summary counts do not reconcile with the supported checks.")
        if (decision == "GO") != all(checks.values()):
            raise ValueError("manifest decision does not reconcile with the supported checks.")

        database = manifest.get("database_evidence")
        if not isinstance(database, dict):
            raise ValueError("manifest database_evidence must be an object.")
        before = cls._safe_order_projection(database.get("before"))
        after = cls._safe_order_projection(database.get("after"))
        for label, snapshot in (("before", before), ("after", after)):
            if str(snapshot.get("order_id", "")) != str(manifest.get("order_id", "")):
                raise ValueError(f"database_evidence.{label} does not match manifest order_id.")
        hashes = {}
        for label in ("full_database_before_sha256", "full_database_after_sha256"):
            value = database.get(label)
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(char not in "0123456789abcdef" for char in value)
            ):
                raise ValueError("database fingerprints must be 64 lowercase SHA-256 hexadecimal characters.")
            hashes[label] = value
        collateral = database.get("other_database_entities_unchanged")
        write_count = database.get("write_count_in_trace")
        if not isinstance(collateral, bool):
            raise ValueError("other_database_entities_unchanged must be a boolean.")
        if collateral is not checks["no_other_database_entities_mutated"]:
            raise ValueError("collateral-mutation metadata does not reconcile with its check.")
        if isinstance(write_count, bool) or not isinstance(write_count, int) or write_count < 0:
            raise ValueError("write_count_in_trace must be a non-negative integer.")
        if decision == "GO" and write_count != 1:
            raise ValueError("a GO manifest must contain exactly one write in the trace.")
        if database.get("tool_return_value_used_for_decision") is not False:
            raise ValueError("manifest must confirm the tool return value was not used for the decision.")
        tamper_probe = database.get("tamper_probe")
        if (
            not isinstance(tamper_probe, dict)
            or tamper_probe.get("detected") is not checks["tamper_probe_is_detected"]
            or not isinstance(tamper_probe.get("mutated_field"), str)
        ):
            raise ValueError("tamper probe metadata does not reconcile with its check.")

        minimization = manifest.get("data_minimization")
        if not isinstance(minimization, dict) or minimization.get("raw_order_snapshots_included") is not False:
            raise ValueError("manifest must explicitly exclude raw order snapshots.")
        simulation_task_id = manifest.get("simulation_task_id")
        order_id = manifest.get("order_id")
        if isinstance(simulation_task_id, bool) or not isinstance(simulation_task_id, (str, int)):
            raise ValueError("simulation_task_id must be a string or integer.")
        if not isinstance(order_id, str) or not order_id.strip():
            raise ValueError("order_id must be a non-empty string.")

        safe_database = {
            "before": before,
            "after": after,
            **hashes,
            "other_database_entities_unchanged": collateral,
            "write_count_in_trace": write_count,
            "tool_return_value_used_for_decision": False,
            "tamper_probe": {
                "mutated_field": tamper_probe["mutated_field"],
                "detected": tamper_probe["detected"],
            },
        }
        evidence = {
            "decision": decision,
            "simulation_task_id": simulation_task_id,
            "order_id": order_id,
            "database_evidence": safe_database,
            "checks": {key: checks[key] for key in sorted(cls._required_checks)},
            "summary": {"passed_checks": passed_checks, "total_checks": total_checks},
            "limitations": list(cls._limitations),
            "data_minimization": {
                "raw_order_snapshots_included": False,
                "redacted_fields": list(cls._redacted_fields),
            },
        }
        return EvidenceEnvelope(
            source_name="tau2-pinned-simulator-manifest",
            source_version=source_version,
            assurance_scope="pinned_simulator_replay_evidence_only",
            source_authenticity="not_verified",
            release_eligible=False,
            evidence=evidence,
        )
