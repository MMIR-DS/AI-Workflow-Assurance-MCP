# Retail exchange evidence adapter (v1)

## Purpose

This adapter maps a normalized, vendor-neutral evidence bundle for an online-retail exchange into an AI Workflow Assurance (AWA) case and release report. It is intended to evaluate a workflow that authenticates a customer, reads a delivered order, confirms the exact exchange, checks available replacement variants and payment consistency, performs one exchange write, and verifies the resulting state.

The included example is **synthetic test data**, not a live store integration. The adapter does not call a model, authenticate a customer, execute a write, or fetch a database snapshot. A source-specific adapter must collect the evidence from the system of record and serialize it to the contract below.

## Run the example

From a clean checkout with the development extra installed:

```bash
python -m pip install -e ".[dev]"
python scripts/adapt_retail_exchange_observation.py \
  --observation examples/retail_exchange_observation_v1.json \
  --spec examples/tau2_retail_workflow.json \
  --output-dir artifacts/retail-exchange-demo
```

The bundled fixture should produce `GO`. The process exits with code `0` for `GO` and `2` for `HOLD`/`NO_GO`. A malformed contract produces a CLI usage error. Output files are `awa_case.json`, `awa_eval_report.json`, `awa_release_report.json`, and `adapter_metadata.json`.

## Contract: `retail-exchange-observation-v1`

The input is one JSON object with `schema_version: "1.0"`, a non-empty `run_id`, and a timezone-aware ISO-8601 `collected_at` timestamp. When `--max-evidence-age-seconds` is configured, the adapter rejects bundles older than the configured limit (and timestamps more than 30 seconds in the future). This freshness check uses the bundle collection time; it does not prove that upstream source snapshots were fresh when collected. The requested order ID and payment-method ID must be non-empty strings; old/new item IDs must be non-empty lists of non-empty strings. Every event must carry a non-empty `source_event_id`, and event IDs must be unique within the observation. Each event also requires a positive integer `collector_sequence`, strictly increasing in the array order, plus a timezone-aware ISO-8601 `occurred_at` timestamp. The collector sequence preserves the collector’s observed ordering; it is not proof of source authenticity. The confirmation evidence and its event must carry the same non-empty confirmation ID.

| Field | Required shape | Source-of-truth expectation |
|---|---|---|
| `requested_exchange` | `order_id`, `old_item_ids[]`, `new_item_ids[]`, `payment_method_id`, optional `requested_options` map | The requested write plus the customer's explicit confirmed intent; when a non-empty options map is supplied, it must cover every requested new item and contain no unrelated item IDs |
| `identity_evidence` | `verified_user_id` | Authentication/identity service result, not an LLM claim |
| `confirmation_evidence` | `confirmed: true`, order ID, old/new item IDs, payment ID, confirmation ID | An explicit confirmation event before the write |
| `order_before` | Order object with the exact supported fields shown in the fixture | Independent read before mutation |
| `order_after` | Same field set as `order_before` | Independent read after mutation; do not substitute the write tool's return value when independent verification is available |
| `catalog_products` | Product ID map containing variants, item IDs, availability, prices, options | Catalog/inventory source captured for the evaluation |
| `events[]` | Ordered event objects with unique `source_event_id`, positive increasing `collector_sequence`, and timezone-aware `occurred_at` | Collector-preserved event order; timestamps are retained for audit, but source clock integrity is not verified |
| `new_order_ids_before/after` | Arrays of order IDs | Order index snapshots to detect unintended order creation |
| `notification_evidence` | Optional `assistant_claimed_sent` and `provider_delivery_status` | Provider receipt/status if the assistant claims a notification was sent |

### Event types

- `identity_verified`: `order_id`, `user_id`, and a non-empty `source_event_id`; the event ID must exactly match `identity_evidence.source_event_id` and must precede the order read.
- `order_read`: `order_id`; must precede the exchange write.
- `customer_confirmed`: `order_id`, `confirmation_id`; must precede the exchange write and match the confirmation evidence.
- `write`: `operation`, `order_id`, `succeeded`. The expected successful write is `exchange_order_items`; any extra write is rejected.
- `escalation`: treated as an escalation-policy event by this initial contract.

The adapter rejects non-increasing collector sequence values instead of silently sorting events. A production source adapter should preserve native source sequence/version data where available, retain source timestamps, and document how cross-system ordering is reconciled. The normalized collector sequence is useful for detecting accidental reordering but can be forged by an untrusted collector. Do not infer event ordering from assistant narrative text. Configure `--max-evidence-age-seconds` for deployments that require a freshness bound; without that flag, metadata reports freshness as `not_configured`.

**Trust boundary:** these checks validate the internal consistency of the supplied bundle; they do not cryptographically prove who produced it or whether the source system was truthful. A production integration should authenticate the collector, authorize each source, preserve immutable source event IDs and sequence/timestamp metadata, and verify signed receipts or source attestations where available. A self-reported `source_system` label or a hash alone is not proof of authenticity.

## Missing evidence versus a failed workflow output

For the general `PASS` / `FAIL` / `NOT_EVALUABLE` semantics, see the [observation and adapter contract](OBSERVATION_ADAPTER_CONTRACT.md). In this retail contract, a required event or final-state field omitted by the workflow is a failed criterion when that omission is the behavior being checked. Do not label it unobserved just because the field is absent from `order_after` or the event trace.

Use `unobserved_checks` only when the evidence collection process genuinely did not observe the criterion (for example, a source outage prevented a read and the absence is not itself a workflow violation). The generic evaluator cannot independently establish whether that declaration is truthful, so adapter-specific tests must cover both omitted required workflow outputs and actual source-collection gaps. A known mismatch in the supplied before/after state must remain a failure, not be downgraded to unobserved.

## Decisions derived by the adapter

The adapter derives the same 16 fields used by the current retail acceptance specification: identity, status verification, explicit confirmation, eligibility, product/variant/request match, payment policy, item scope, final state, unrelated-state preservation, price reconciliation, notification claim consistency, no new order, escalation policy, one expected write, final order status, and policy-violation count.

Money is parsed with decimal arithmetic and rounded to cents. Unknown/missing evidence fails the relevant check rather than being treated as a pass. The release spec blocks on critical and high failures.

## Threat model

See [the retail exchange adapter threat model](THREAT_MODEL_RETAIL_EXCHANGE.md) for assets, trust boundaries, current mitigations, residual risks, and production prerequisites.

## Trust boundary and limitations

1. **Evidence quality is the main risk.** AWA can only check what the source adapter supplies. If the adapter invents or mislabels events, this report cannot detect that on its own.
2. **Read-after-write matters.** For production use, collect `order_after` through an independent database/API read. The tool's return payload is not independent corroboration.
3. **Snapshot scope matters.** The first version checks unchanged fields on the target order and compares order-ID lists. It does not independently diff every customer, payment, inventory, or product record. Extend the contract with full state snapshots before using it as a production control.
4. **Authorization must happen outside AWA.** The adapter verifies consistency between the identity event and order owner; it does not perform authentication or authorization.
5. **No email delivery inference.** If a workflow claims it sent a notification, a provider delivery status of `delivered` is required. This still relies on the provider evidence being authentic.
6. **Retail-specific by design.** This is a reference contract for one workflow, not a universal event schema or a guarantee of production safety.

## Validation

The test suite covers a passing fixture and negative controls for unavailable variants, price mismatch, payment mismatch, unrelated state mutation, late confirmation, extra or unsupported write operations, mismatched identity-event linkage, unsupported notification claims, unintended order creation, unknown contract versions, malformed evidence, and malformed/out-of-scope requested options.

```bash
python -m pytest tests/test_retail_exchange_observation_adapter.py
ruff check scripts/adapt_retail_exchange_observation.py tests/test_retail_exchange_observation_adapter.py
```


## Freshness and ordering checks

The adapter requires a timezone-aware `collected_at` bundle timestamp and strictly increasing positive `collector_sequence` values for the event array. When a freshness limit is supplied, it compares `collected_at` with the evaluator current UTC time and fails closed if the bundle is too old. Library callers may inject an aware `evaluation_time` to make freshness tests deterministic. The CLI option is:

```bash
python scripts/adapt_retail_exchange_observation.py \
  --observation path/to/observation.json \
  --spec examples/tau2_retail_workflow.json \
  --output-dir artifacts/evaluation \
  --max-evidence-age-seconds 300
```

A production deployment should set a limit appropriate to its workflow and separately enforce freshness of each upstream snapshot. The current bundle timestamp is caller-supplied, so this check is a consistency guard—not an authenticated clock or a source-freshness guarantee.
