# AWA Independent Trace-Evidence Mutation Result — Retail Task 0 — 2026-10-10

> **Historical result; superseded by the v0.1.7 pre-write review.** This document records the six-fault post-run protocol that was executed on 2026-10-10. It is retained as an audit record and must not be read as the current policy result for the committed raw task-0 trace: the current adapter correctly returns `NO_GO` because required pre-write disclosure is absent. The current deterministic workflow uses a separate synthetic valid control and seven independent mutations. See the current PR/CI run for the authoritative result.


## Purpose

Verify that AWA rejects specific defects visible in recorded retail tool evidence without using tau2's `reward`, `db_match`, or expected action-check fields to make its release decision.

## Baseline

The saved task-0 trace was passed through the adapter and AWA evaluator:

| Measure | Baseline |
|---|---:|
| AWA decision | `GO` |
| AWA acceptance criteria | 16/16 passed |
| Critical failures | 0 |
| High-severity failures | 0 |
| Recalculated exchange price difference | -$16.63 |
| Saved tau2 reward, used as metadata only | 1.0 |
| Saved tau2 `db_match`, used as metadata only | true |
| Saved tau2 action checks, used as metadata only | 5/5 matched |

The recalculated price difference matches the exchange tool's returned order object.

## Six injected faults

Each fault was applied to a copy of the stored raw trace or a tool response. The workflow required the specific target criterion to fail and the release decision to become `NO_GO`. The saved tau2 reward, database-match flag and action-check results were held constant for all six mutations.

| Controlled mutation | Target criterion | Result | Critical failures | High failures |
|---|---|---|---:|---:|
| Remove the user's explicit confirmation | `confirmation_policy_respected` | `NO_GO` | 2 | 0 |
| Mark the selected keyboard variant unavailable | `selected_variants_match_product_and_request` | `NO_GO` | 2 | 0 |
| Change city in the exchange tool's returned order object | `no_unrelated_state_mutation` | `NO_GO` | 2 | 0 |
| Change the returned price difference to -$15.00 | `price_difference_reconciles` | `NO_GO` | 1 | 1 |
| Change exchange payment method to an unobserved ID | `payment_policy_respected` | `NO_GO` | 3 | 1 |
| Break the thermostat catalog response's product-family ID | `selected_variants_match_product_and_request` | `NO_GO` | 2 | 1 |

**Suite outcome: 6/6 mutations produced `NO_GO`; in every case the saved tau2 oracle metadata was unchanged.** The workflow also wrote a baseline report, an evaluation and release report for each mutation, adapter metadata and a mutation summary.

## What this demonstrates

The trace-to-adapter-to-AWA pipeline can independently check several deterministic business invariants from the observed order and product tool payloads: prior order status, explicit confirmation evidence, item/product mapping, availability and requested options, payment-method consistency with the original order transaction, returned-state consistency, unrelated-field stability and price arithmetic. These checks do not simply trust tau2's reward or its own action/db oracle fields.

## What it does not demonstrate

- This is a controlled post-run evidence mutation, not six new environment executions and not evidence that a real agent actually performed an unsafe action.
- The post-state is the exchange tool's returned object compared with the original order read; the simulator database was not independently re-queried after the action.
- The payment check does not query the user's live payment profile.
- The notification check validates the assistant's wording, not email-provider delivery.
- The evidence is one public simulated retail task, not real customer data, a statistical reliability study, production certification or proof that all defects in all workflows will be caught.

## Reproducibility

- Successful no-model replay: https://github.com/MMIR-DS/AI-Workflow-Assurance-MCP/actions/runs/38059062409
- CI across Python 3.10–3.13: https://github.com/MMIR-DS/AI-Workflow-Assurance-MCP/actions/runs/38059062398
- Saved model run (used as evidence, not re-run): https://github.com/MMIR-DS/AI-Workflow-Assurance-MCP/actions/runs/38047957343
- Workflow: [`.github/workflows/awa-replay-existing-tau2.yml`](../.github/workflows/awa-replay-existing-tau2.yml)
