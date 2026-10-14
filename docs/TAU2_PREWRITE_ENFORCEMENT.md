# Tau2 pre-write enforcement integration

## Status

The manual retail smoke workflow applies a narrow patch to the pinned Tau2 orchestrator. Seven reviewed write paths consult AWA before calling the environment: exchange, cancellation, order-address changes, payment-method changes, user default-address changes, delivered-item returns, and pending-item modification for exactly one old/new item pair. The pending-item path requires a post-write audit against the product catalog and unchanged non-target rows; multi-item modifications remain blocked because public reports describe possible multi-item price/options corruption in Tau2's implementation ([#317](https://github.com/sierra-research/tau2-bench/issues/317), [#318](https://github.com/sierra-research/tau2-bench/issues/318)). The known `create_order` write and any unknown/unreviewed tool name are also default-denied. Only an explicit passthrough allowlist of known read/escalation tools reaches the normal environment path. The workflow is manual-only and model calls can incur charges. A no-model runtime smoke test runs first.

Pinned upstream Tau2 revision: `4ce7c0397c1eb65c9bbe59aeacfe1ca44a1cd699`.

## Runtime behavior

Before the environment executes `exchange_delivered_order_items`, the patched orchestrator calls `evaluate_tau2_prewrite` on the current in-memory trajectory and proposed tool call. The adapter builds a normalized action/evidence bundle and delegates the decision to `evaluate_prewrite`.

The preflight validates simulator evidence against the requested operation rather than relying only on matching confirmation text. It verifies old-item quantity, same-product pairing, current replacement availability, the original order payment method, and the exact calculated price delta. A user confirming an invented item ID, a different product type, an undisclosed financial delta, or a payment method not present in the order history is insufficient for `GO`. The preflight requires:

- the latest matching `get_order_details` response must identify the exact requested order and report status `delivered`;
- requested old-item multiplicities must not exceed the quantity present in the order snapshot; duplicate item IDs are permitted only when the snapshot contains enough units;
- each new item ID must be present in the latest matching `get_product_details` result as an available variant and must match the product type of the old item in the same position;
- the exact total price difference and its direction (additional charge, refund, or zero difference) must be disclosed before the user confirms;
- the proposed payment-method ID must appear in that order's payment history as a payment transaction;
- a prior `find_user_id_by_name_zip` or `find_user_id_by_email` lookup whose result matches the order owner;
- an assistant message that explicitly includes the order ID, every old item ID, every new item ID, and the exact payment-method ID;
- a subsequent affirmative user response, with negative or change requests rejected;
- confirmation sequence before the proposed write sequence;
- a fresh order snapshot: any intervening write attempt against the same order forces a new read before retry;
- at most one exchange write for a given order in a single dispatcher batch, because every call in that batch otherwise observes the same pre-write trajectory snapshot.

The dispatcher reserves the order ID on the first supported write attempt in a batch, including when that attempt is blocked. A second same-order write in that batch returns `NO_GO` and must be retried only after a new turn and fresh order read. A blocked attempt also invalidates the earlier confirmation for that operation: the assistant must disclose the action again and receive a new affirmative user response before another attempt can be approved.

When the decision is `NO_GO`, the patched dispatcher returns an error `ToolMessage` and does **not** call `environment.get_response` for the exchange. The agent can then ask the user to confirm the complete details and retry. On `GO`, the normal Tau2 environment dispatch executes exactly once.

## Pending-order cancellation

The separate `evaluate_tau2_cancel_prewrite` policy permits cancellation only when the latest order snapshot matches the requested order and shows `pending`, the identity lookup matches the order owner, and the cancellation reason is one of Tau2's two supported values. It also requires the order's payment history to contain only supported payment transactions, and requires the assistant to disclose the exact total refund, each payment-method ID, the cancellation reason, and the appropriate refund timing (gift-card refunds immediately; other payment methods take 5–7 business days) before a fresh affirmative user response. A missing or unsupported detail returns `NO_GO` before environment dispatch.

## Pending-order address changes

The separate `evaluate_tau2_address_prewrite` policy requires a matching, fresh order snapshot in `pending` state, identity matching the order owner, a complete new address that differs from the current address, and assistant disclosure of every supplied address field (including the secondary line, or an explicit no-secondary-line statement). It rejects an explicitly conflicting order ID or postal code in the user's reply and requires fresh affirmative confirmation after any prior blocked attempt.

## Pending-order payment-method changes

The separate `evaluate_tau2_payment_prewrite` policy requires a fresh matching pending-order snapshot with exactly one current payment transaction, matching order-owner identity, and a `get_user_details` response for that owner proving the proposed method exists and differs from the current method. Before a new affirmative response, the assistant must disclose the order ID, current and proposed payment-method IDs, and the proposed method's available identifying details (source, brand, and last four digits when supplied). Unknown methods, stale snapshots, and incomplete disclosures return `NO_GO`.

## Pending-order item modifications

The `evaluate_tau2_pending_items_prewrite` policy now authorizes **exactly one old/new item pair** on a matching, fresh `pending` order. The dispatcher rejects empty, malformed, same-ID, or multi-item requests before calling the environment. After a single-item write returns, `audit_tau2_single_pending_item_write_response` requires the replacement row to match the latest catalog's product, variant ID, price, and options, and compares every non-target order row with the pre-write snapshot. Only a `PASS` returns the original successful tool result. `FAIL` or `NOT_EVALUABLE` is returned as `AWA_POSTWRITE_AUDIT_NOT_PASS`, explicitly stating that the write already executed and must not be retried. This post-write audit cannot roll back a write; the narrow one-item restriction avoids the known multi-item bug path, while the audit fails closed on observable corruption. Public reports [#317](https://github.com/sierra-research/tau2-bench/issues/317) and [#318](https://github.com/sierra-research/tau2-bench/issues/318) describe the risk in multi-item updates, which remain disabled.

## Independent post-write catalog audit

The pinned Tau2 implementation at revision `4ce7c0397c1eb65c9bbe59aeacfe1ca44a1cd699` has a confirmed defect in `modify_pending_order_items`: the second update loop reuses the final `variant` variable from the validation loop, so earlier modified items can inherit the final item's price and options. The public reports [#317](https://github.com/sierra-research/tau2-bench/issues/317) and [#318](https://github.com/sierra-research/tau2-bench/issues/318) also explain why the replay-based DB reward can pass despite this state corruption.

`audit_tau2_order_items_against_catalog` in `src/ai_workflow_assurance_mcp/tau2_postwrite.py` independently compares each persisted order row with its product's catalog variant. It checks that the item ID exists under the recorded product ID, the price matches to cents, and the full options mapping matches. A definite mismatch returns `FAIL`; missing or malformed catalog/order evidence returns `NOT_EVALUABLE`, never a false `PASS`.

Run the CLI against a JSON file with an `order_snapshot` object and a `product_snapshots` list:

```bash
PYTHONPATH=src python scripts/audit_tau2_order_postwrite.py --input postwrite-snapshot.json
```

Example full Tau2 benchmark artifact input:

```bash
PYTHONPATH=src python scripts/audit_tau2_order_postwrite.py --input tau2-result.json
PYTHONPATH=src python scripts/audit_tau2_order_postwrite.py --input tau2-result.json --simulation-index 3
```

When the JSON has a top-level `simulations` list, the CLI audits each unique target order touched by the selected write tool in every selected simulation. The aggregate is `FAIL` if any order has a definite mismatch, `NOT_EVALUABLE` if one or more simulations lack usable post-write/catalog evidence, and `PASS` only when all selected order audits pass. Tau2 reward fields are retained only in the input and are not used as an integrity oracle.

Example raw-trace input shape:

```json
{
  "order_id": "#W9348897",
  "write_tool_name": "modify_pending_order_items",
  "trajectory": []
}
```

Use the complete Tau2 `messages` array in `trajectory`; the empty array above is only a schema illustration.

The CLI emits a structured JSON report and uses exit code `0` for `PASS`, `1` for `FAIL`, and `2` for `NOT_EVALUABLE`. You may supply explicit snapshots, a raw Tau2 message trace using a top-level `trajectory` array plus `order_id`, or a full benchmark artifact with a top-level `simulations` list. The `--write-tool-name` flag selects the write path; `--simulation-index` limits a full-artifact audit to one zero-based simulation. In trace mode, the adapter correlates tool calls to their results by call ID, uses the successful write result as the post-write state unless a later matching `get_order_details` read exists, and selects the latest catalog result per product. A blocked/missing write result, failed latest read, or missing product snapshot returns `NOT_EVALUABLE`.

The CLI trace audit remains a pure/offline check and cannot roll back a write. Separately, the pinned dispatcher enables only the single-item pending mutation path, with a runtime post-write audit of the changed row and all non-target rows. Multi-item item mutations remain blocked before execution.

## User default-address changes

The `evaluate_tau2_user_address_prewrite` policy binds the target to a fresh `get_user_details` result and the identity lookup, requires a complete address that differs from the stored default address, and requires the assistant to identify the customer and disclose the exact new address before confirmation. An explicitly conflicting postal code, stale user snapshot, or confirmation replay after a blocked attempt returns `NO_GO`.

## Delivered-item return requests

The `evaluate_tau2_return_prewrite` policy requires a fresh delivered-order snapshot, matching owner identity, item IDs and quantities present in the order, and a payment method that is either the original order payment method or a verified gift card belonging to the user. Before confirmation, the assistant must disclose the exact order/items/payment method and explain that this creates a return request followed by a return-instructions email. The adapter does not claim that a refund has already occurred.

## Fail-closed patching

`scripts/install_tau2_prewrite_guard.py` verifies the checked-out Tau2 commit before patching. It replaces exactly one known dispatch-loop snippet and refuses to modify unknown or ambiguous source layouts. Patch marker V6 also makes the dispatcher default-deny unknown/unreviewed tool names; only explicit passthrough tools (known read operations and the named escalation tool) reach the normal environment path. This avoids silently applying a brittle patch to a different upstream version or automatically trusting newly added tool names.

The manual workflow then runs:

```bash
PYTHONPATH="../src${PYTHONPATH:+:$PYTHONPATH}" uv run python ../scripts/smoke_test_tau2_prewrite_guard.py
```

The runtime smoke test uses Tau2's actual patched `BaseOrchestrator._execute_tool_calls` method with a counting fake environment, not a model and not a real database. It proves:
- the saved baseline, whose final confirmation omits the order ID and old item IDs, returns `NO_GO` and makes zero environment calls;
- an unreviewed `create_order` request is denied by the dispatcher and makes zero environment calls;
- a synthetic complete disclosure followed by an affirmative reply returns `GO` and makes exactly one fake environment call;
- replaying the old disclosure and confirmation after `AWA_PREWRITE_NO_GO` is blocked with zero environment calls;
- a fresh affirmative reply after an incomplete re-disclosure is still blocked with zero environment calls;
- a complete fresh disclosure and affirmative reply after `AWA_PREWRITE_NO_GO` are re-evaluated against catalog, order, payment, and price evidence before one fake environment call is permitted;
- a second exchange for the same order in one batch is blocked, so only the first approved exchange reaches the fake environment callback;
- a valid pending-order cancellation reaches the fake callback only after exact refund disclosure, while missing disclosure is blocked before callback;
- a valid pending-order address change reaches the fake callback only after exact address disclosure, while a missing field is blocked before callback;
- a valid pending-order payment-method change reaches the fake callback only after the proposed method is verified and disclosed, while missing disclosure is blocked before callback;
- a valid single-item pending-order item modification reaches the fake callback only when preflight passes and the post-write catalog audit passes; multi-item requests are blocked before callback, while corrupted or unauditable post-write results are flagged after the write with an explicit do-not-retry warning;
- an unrecognized/new tool name is denied with zero environment calls, while a known read-only tool (`get_order_details`) is still allowed through the explicit passthrough list;
- a valid user default-address change reaches the fake callback only after the identity and exact address are verified, while missing disclosure is blocked before callback;
- a valid delivered-item return reaches the fake callback only after item/payment authorization and follow-up-process disclosure, while missing disclosure is blocked before callback.

The full AWA test suite separately tests the evidence adapter and patcher's idempotency/source-layout checks.

## Scope and limitations

This is a **simulator-specific enforcement experiment**, not a production authorization system.

- Seven retail write paths have reviewed simulator-specific controls: `exchange_delivered_order_items`, `cancel_pending_order`, `modify_pending_order_address`, `modify_pending_order_payment`, `modify_user_address`, `return_delivered_order_items`, and `modify_pending_order_items` for exactly one old/new item pair with a mandatory runtime post-write catalog audit. Multi-item pending-item modifications remain blocked. `create_order` and every unrecognized/unreviewed tool name are blocked. Only the explicit passthrough allowlist (`find_user_id_by_email`, `find_user_id_by_name_zip`, `get_order_details`, `get_product_details`, `get_user_details`, `list_all_product_types`, `think`, and `transfer_to_human_agents`) reaches the normal dispatch path.
- Tau2's simulated identity lookup and in-memory database are benchmark evidence, not production authentication or trusted payment authorization.
- The normalized trajectory is not cryptographically authenticated; the adapter must not be used as proof of real customer identity.
- This source patch is applied in the workflow checkout and is not automatically installed into the upstream Tau2 repository or a user's local environment.
- A real application must enforce the same control in the trusted service that owns the write, use server-side identity/session context, verify current order/payment state, and prevent time-of-check/time-of-use changes with a transaction or version check.
- The workflow is manual-only; its model-backed task may incur provider charges. The no-model dispatch smoke test runs before the model task.

Do not infer production readiness from a passing Tau2 run or a passing AWA report.
