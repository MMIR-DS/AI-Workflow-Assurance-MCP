"""Contracts for read-only evidence-source adapters.

The protocol describes a read-only interface; it does not itself authenticate a
source, enforce operating-system permissions, or authorize production releases.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


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
    """Read an existing tau2 simulator manifest from disk without changing it.

    The manifest's upstream report does not provide a trusted collection
    timestamp, so this adapter deliberately leaves collected_at unset.
    """

    def __init__(self, manifest_path: str | Path) -> None:
        self._manifest_path = Path(manifest_path)

    def read_evidence(self) -> EvidenceEnvelope:
        try:
            manifest = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"could not read a valid JSON manifest: {exc}") from exc
        if not isinstance(manifest, dict):
            raise ValueError("manifest must be a JSON object.")
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
        authenticity = provenance.get("source_authenticity")
        if not isinstance(source_version, str) or not source_version.strip():
            raise ValueError("manifest must include a checked-out source commit.")
        if authenticity != "not_verified":
            raise ValueError("tau2 simulator manifest must remain explicitly unverified.")

        evidence = {
            key: manifest[key]
            for key in (
                "decision",
                "simulation_task_id",
                "order_id",
                "database_evidence",
                "checks",
                "summary",
                "limitations",
                "data_minimization",
            )
            if key in manifest
        }
        return EvidenceEnvelope(
            source_name="tau2-pinned-simulator-manifest",
            source_version=source_version,
            assurance_scope="pinned_simulator_replay_evidence_only",
            source_authenticity="not_verified",
            release_eligible=False,
            evidence=evidence,
        )
