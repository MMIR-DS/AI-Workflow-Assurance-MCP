# AWA Adapter Result — Retail Task 0 — 2026-10-10

## Revised evaluation method

The adapter now derives its release decision from recorded tool payloads. The tau2 `reward`, `db_check.db_match`, and `action_checks` values are retained only as comparison metadata and do not determine AWA acceptance.

- The initial order state is parsed from the pre-mutation `get_order_details` tool response.
- Product IDs, selected variant options, availability, and current catalog prices are parsed from the `get_product_details` tool responses.
- The selected old/new item pairs are checked against the original order and the corresponding product variants.
- The selected payment method is compared with the original order's payment transaction and the exchange tool's returned state.
- The exchange result is compared field-by-field with the initial order response. Only the documented exchange fields are allowed to change; address, item history, fulfillments, payment history and unrelated fields must remain equal.
- The price difference is independently recalculated as selected new catalog prices minus historical prices of the replaced order items, rounded to cents.

The tool payloads yield **-$16.63**; the exchange response records **-$16.63**, so the price reconciliation passes.

## Result on the saved task-0 trace

- AWA release decision: **GO**
- AWA criteria passed: **16/16**
- Critical failures: **0**
- High-severity failures: **0**
- Saved tau2 reward (metadata only): **1.0**
- Saved tau2 `db_match` (metadata only): `true`
- Saved tau2 action checks (metadata only): **5/5**
- Model run duration: approximately **17.79 seconds**
- Estimated provider usage metadata from the original trace: approximately **$0.01660 USD**; verify against OpenRouter billing if the exact charge matters.

A unit test also forces tau2's reward, `db_match` and action checks to false while keeping the observed tool payloads unchanged. AWA still returns GO, demonstrating that the release decision is not derived from those tau2 oracle fields.

## Six no-model-call mutation checks

The GitHub Actions replay loaded the archived task-0 result and created six altered copies of the recorded trace/tool responses. Each mutation was required to produce `NO_GO` while the saved tau2 reward, database-match and action-check metadata remained unchanged:

1. Remove explicit customer confirmation.
2. Mark the selected keyboard variant unavailable.
3. Alter the city in the exchange tool's returned order object.
4. Change the recorded exchange price difference from -$16.63 to -$15.00.
5. Change the exchange call's payment method to an unobserved ID.
6. Break the selected thermostat product's product-family mapping.

All six checks passed. The replay did not invoke the model again and therefore made no additional OpenRouter model calls.

## Independent database-state replay added after the trace review

A companion verifier now exists at `scripts/verify_tau2_independent_db.py`, with a no-model workflow at `.github/workflows/awa-independent-db-check.yml`. It checks out the benchmark commit recorded in the trace, loads a fresh RetailDB, verifies the initial database order against the recorded `get_order_details` response, and replays only the recorded exchange write. The write method's return value is discarded; the verifier reads the order directly from `RetailDB.orders`, compares the entire state to the saved exchange response, checks the selected payment method against the loaded user's payment profile and original transaction, recomputes the price difference, and hashes full-database snapshots to verify no other orders, users, or products changed. A negative control corrupts a copy of the recorded post-state and requires the comparison to detect it.

The companion workflow does not call an agent or user LLM. Its result should be treated as a deterministic replay against the pinned benchmark data, not as a snapshot taken from the exact process that performed the original model run. The implementation is in the repository; do not describe the replay as passed unless the corresponding GitHub Actions run completes successfully.

## Evidence boundaries

This is meaningfully more independent of tau2's *scoring oracle*, but it is not a fully external audit of the simulator:

- In the original trace alone, the “after” state is the object returned by the exchange tool; there is no independent database snapshot. The companion replay checks the database state in a separate clean run, not the already-mutated in-memory database from the original model run.
- The companion replay checks the selected payment method against the profile loaded in that replay's RetailDB. It cannot prove the original run used a live profile that differed from the pinned simulator data.
- The notification criterion checks the assistant's message wording, not whether an email provider actually delivered an email.
- The option checks and manually defined expected outcomes are specific to this one public retail task. Six controlled mutations on one task are not a statistical reliability study or proof of general coverage.

## Reproducibility

- Saved tau2 model run: https://github.com/MMIR-DS/AI-Workflow-Assurance-MCP/actions/runs/38047957343
- Successful no-model six-mutation replay: https://github.com/MMIR-DS/AI-Workflow-Assurance-MCP/actions/runs/38059062409
- CI across Python 3.10–3.13: https://github.com/MMIR-DS/AI-Workflow-Assurance-MCP/actions/runs/38059062398
- Mutation replay workflow: [`.github/workflows/awa-replay-existing-tau2.yml`](../.github/workflows/awa-replay-existing-tau2.yml)
