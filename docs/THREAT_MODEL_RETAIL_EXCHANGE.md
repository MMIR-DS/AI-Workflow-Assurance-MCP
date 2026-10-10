# Retail Exchange Adapter Threat Model

## Status and intended use

This is a threat model for the reference retail-exchange evidence adapter, not a security certification. The current adapter evaluates a caller-supplied JSON bundle and can return a policy decision of `GO`; that decision means only that the supplied evidence passed the configured checks. It does **not** mean the evidence is authentic, the collector is trusted, or the workflow is production-ready.

Current machine-readable scope:
- `assurance_scope: structural_and_policy_consistency_only`
- `production_ready: false`
- `source_authenticity: not_verified`
- `cryptographic_signature_validation: not_implemented`

## Assets to protect

1. Correctness of the workflow release decision.
2. Customer identity and authorization evidence.
3. Original and resulting order state, including unrelated fields.
4. Explicit customer intent and confirmation.
5. Catalog availability, variant options, payment consistency, and price reconciliation.
6. Event ordering, identifiers, and completeness.
7. Integrity and interpretation of generated case, evaluation, release, and metadata reports.

## Trust boundaries

- **External systems → source adapter:** identity provider, order service/database, catalog/inventory, payment records, and notification provider.
- **Source adapter → evidence bundle:** collection, normalization, timestamp/sequence handling, and serialization.
- **Evidence bundle → AWA evaluator:** caller-supplied JSON is treated as data, not as inherently trusted proof.
- **Evaluator → reports/CI:** policy results and metadata may be consumed by a person or an automated release gate.

The evaluator currently has no independent connection to those source systems and cannot establish that a bundle reflects reality.

## Threats, current controls, and residual risk

| Threat | Current control | Residual risk |
|---|---|---|
| Missing or duplicate event IDs | Rejects empty and duplicate IDs within a bundle | IDs can be fabricated; uniqueness inside one file is not provenance |
| Confirmation forged, missing, or out of scope | Checks confirmation fields and event linkage/order | Cannot prove a real customer generated the event |
| Identity event mismatched to evidence | Checks event ID and user/order consistency | Cannot authenticate the identity provider or collector |
| Unexpected or repeated writes | Counts all write events and requires one expected write | Omitted or falsified events can hide real writes |
| Stale or fabricated before/after snapshots | Checks field-level consistency and documented order scope | No live independent read in this adapter |
| Catalog, payment, or price evidence manipulated | Cross-checks supplied fields and recomputes price difference | All supplied values may originate from an untrusted collector |
| Event order falsified | Evaluates the supplied list order | Source timestamps/sequence and clock integrity are not verified here |
| Replay of a valid old bundle | No production replay protection | Run ID alone does not prove freshness or prevent replay |
| Misleading interpretation of GO | Explicit scope and non-production metadata; docs explain the boundary | Downstream consumers may ignore metadata unless they enforce it |
| Output modified after evaluation | Git/CI can preserve code history; metadata describes scope | No signed report or tamper-evident evidence chain is implemented |

## Required before production use

Do not connect this reference adapter directly to a production release gate until a deployment-specific design implements and tests all applicable controls:

1. **Authenticate collectors and sources.** Use workload identity or equivalent; authorize each source independently. Never trust a self-reported `source_system` field as proof.
2. **Use least privilege.** Prefer read-only source credentials for evidence collection. Any workflow write must be controlled by the application being evaluated, not by this evaluator.
3. **Preserve source provenance.** Record immutable source event IDs, source sequence/version, source timestamps and collection timestamps. Define deterministic ordering and tie-breaking; reject missing or contradictory ordering data where required.
4. **Prevent replay and detect staleness.** Bind evidence to a unique run/transaction, enforce a freshness window, and reject reused nonces or source versions where the source supports them.
5. **Verify authentic attestations.** If sources sign receipts or snapshots, verify signatures against managed trust anchors and documented key-rotation/revocation policy. A checksum alone is not authentication.
6. **Corroborate state independently.** Read post-write state directly from the system of record through a separate read path; define snapshot scope and consistency semantics.
7. **Fail closed at the production boundary.** Require verified provenance from an external, explicitly defined trust layer in addition to a policy `GO`. The current adapter's `production_ready: false` must not be overridden by a successful policy score.
8. **Protect reports and secrets.** Restrict artifact access, redact personal/payment data, avoid secrets in logs, and retain audit records under an explicit retention policy.
9. **Test the deployment, not just the parser.** Include forged-source, stale-snapshot, replay, reordered-event, partial-source-outage, signature/key-rotation, and report-tampering tests.

## Non-goals and assumptions

- This document does not claim the current adapter authenticates users, verifies signatures, prevents replay, or independently reads a live store.
- The synthetic fixture is for deterministic testing only.
- Passing unit tests and CI demonstrate tested code behavior for the tested cases; they do not establish broad production reliability or source authenticity.
- A production integration needs a system-specific data contract, threat review, privacy review, operational owner, and rollback plan.
