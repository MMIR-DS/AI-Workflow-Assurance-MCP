# Read-only evidence source contract

## Why this exists

Evidence adapters should not each invent their own provenance fields or blur a
successful evaluation with source trust. The package-level
ReadOnlyEvidenceSource protocol establishes one minimal boundary:

- read_evidence() returns an EvidenceEnvelope
- explicit source name, source version, assurance scope and authenticity status
- an optional timezone-aware collection timestamp
- a normalized evidence object
- an explicit release-eligibility flag

The protocol exposes no write method. This is an interface design guarantee,
not a sandbox or permission boundary: Python cannot prevent an implementation
from performing side effects. Concrete adapters still need least-privilege
credentials, code review and tests proving their behavior is read-only.

## Current reference adapter

Tau2ManifestFileSource reads the repository's existing
awa-tau2-source-evidence-v1 JSON manifest. It does not call a model, connect
to a database, or modify the file. It rejects an unexpected manifest type,
scope, production-readiness flag, release-eligibility flag, or authenticity
label. It deliberately leaves collected_at unset because the manifest does
not establish a trusted collection timestamp.

The adapter returns a narrow evidence projection and does not propagate source
provenance a second time inside the payload. The MCP tool
`inspect_tau2_evidence_manifest` accepts the manifest as JSON text and uses the
same normalizer without reading an arbitrary filesystem path. It validates the manifest schema
version, 40-character source commit, exact check-name set, boolean check values,
reconciled summary counts, decision/check consistency, SHA-256 fingerprint
shape, write-count constraints, and tamper-probe consistency. Nested order and
item snapshots are independently projected onto explicit allowlists; unknown
customer fields, extra summary fields, and free-form limitation strings are not
passed through. The normalized envelope preserves the simulator-only scope and
always marks the evidence unverified and ineligible for release. A simulator
GO remains a replay result, not production authorization.

## Example

    from ai_workflow_assurance_mcp.evidence_sources import (
        ReadOnlyEvidenceSource,
        Tau2ManifestFileSource,
    )

    source: ReadOnlyEvidenceSource = Tau2ManifestFileSource(
        "artifacts/awa-source-evidence-manifest.json"
    )
    envelope = source.read_evidence()
    print(envelope.assurance_scope, envelope.release_eligible)

## Trust and integration boundaries

- A manifest's own source_authenticity field is an assertion, not proof.
  The tau2 adapter therefore accepts only not_verified.
- SHA-256 fingerprints detect changes relative to a known digest; they do not
  authenticate who produced the evidence.
- A collection timestamp is meaningful only when its source and clock are
  trusted. Missing timestamps stay missing; adapters must not synthesize them.
- release_eligible is metadata for downstream policy, not a substitute for
  authenticated source evidence or a release authorization process.
- A future live adapter must be specific to a named system and use a
  documented authentication method, least-privilege read-only access, freshness
  rules, and source-specific tests. No live commerce connector is implemented
  by this change.

## Tests

    python -m pytest tests/test_evidence_sources.py
    ruff check src/ai_workflow_assurance_mcp/evidence_sources.py tests/test_evidence_sources.py
