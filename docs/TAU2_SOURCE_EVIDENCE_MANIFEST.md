# tau2 independent-DB evidence manifest adapter

## Purpose

`scripts/adapt_tau2_db_evidence.py` packages a report produced by `scripts/verify_tau2_independent_db.py` into a stable evidence manifest. It is a **read-only post-processor**: it reads the report, validates its structure and internal consistency, and writes a normalized manifest. It does not call a model, connect to the database, or execute workflow writes. The manifest always sets `release_eligible: false`, even when its simulator replay decision is `GO`.

This is a source-specific adapter for the repository's pinned tau2 simulator—not a live commerce integration and not a production security control.

## Run

The [independent RetailDB replay workflow](../.github/workflows/awa-independent-db-check.yml) runs this adapter after a successful replay, then redacts customer/payment fields from the report before upload. The artifact contains `awa-independent-db-report-public.json` and `awa-source-evidence-manifest.json`; the full trace and unredacted snapshots are not uploaded as artifacts. To package a saved report manually, run the following from a checkout with the project installed:

```bash
python scripts/adapt_tau2_db_evidence.py \
  --report awa-independent-db-report.json \
  --output artifacts/tau2-source-evidence-manifest.json
```

The command returns exit code 0 for a consistent `GO` report and 2 for a consistent `NO_GO`/`HOLD` report. Malformed or internally inconsistent reports are rejected with a CLI error.

## Checks performed

- Requires the exact verifier report schema and verification type.
- Requires the full expected set of independent database checks, all boolean.
- Reconciles decision and pass counts against individual checks.
- Reconciles the recorded trace commit with the checked-out simulator commit and the source-commit check.
- Validates the target order ID against both pre- and post-state snapshots.
- Validates the shape of full-database SHA-256 fingerprints.
- Requires explicit confirmation that the write method's return value was not used for the decision.
- Runs negative-control probes against pre-state status, post-state status, selected exchange items, and computed exchange price difference; each must trigger the relevant consistency gate and produce `NO_GO`.
- Records each tamper-probe result in the report, then reconciles aggregate probe metadata with the corresponding check.
- For current reports, validates that every per-field result is boolean, the declared field list matches those results, and a true aggregate means all probes passed. Legacy single-probe reports remain readable.
- Preserves checks, snapshots, hashes, and source metadata without treating them as authenticated claims.

## Trust boundary

The manifest labels its scope as `pinned_simulator_replay_evidence_only`, sets `production_ready: false`, and sets `release_eligible: false`. The manifest includes an allowlisted order-state projection rather than raw order snapshots, omitting customer address, user ID, fulfillment tracking data, payment history and payment-method IDs. A simulated `GO` is a result about the replay evidence, not authorization to release a production workflow. It does not authenticate the report, the collector, or the simulator binary. A SHA-256 fingerprint is a change-detection value, not a signature. The independent DB report represents a deterministic replay against the pinned benchmark database, not a forensic snapshot of the original model run's in-memory database.

Before using an equivalent design against a real service, replace the simulator-specific reader with a least-privilege read-only connector, authenticate the source and collector, record source versions/timestamps, verify signed attestations where available, and define freshness and replay protection at the source boundary.

## Tests

```bash
python -m pytest tests/test_tau2_evidence_manifest.py
ruff check scripts/adapt_tau2_db_evidence.py tests/test_tau2_evidence_manifest.py
```


## Public artifact data minimization

The report redactor is implemented in `scripts/redact_tau2_db_report.py`. It preserves decision checks, summary counts, fingerprints and a narrow order-state allowlist while removing addresses, user IDs, fulfillment tracking IDs, payment histories and payment-method IDs. The manifest independently applies its own order-state projection, so it does not copy raw snapshots even when run manually on an unredacted report. The original report is used only within the workflow to build the manifest; only the redacted report is uploaded.
