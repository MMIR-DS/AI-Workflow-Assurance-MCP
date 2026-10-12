# Tau2 pre-write enforcement integration

## Status

The manual retail smoke workflow applies a narrow patch to the pinned Tau2 orchestrator. Six reviewed write paths consult AWA before calling the environment: exchange, cancellation, order-address changes, payment-method changes, user default-address changes, and delivered-item returns. Pending-item modification is currently default-denied because public reports describe possible multi-item price/options corruption in Tau2's implementation ([#317](https://github.com/sierra-research/tau2-bench/issues/317), [#318](https://github.com/sierra-research/tau2-bench/issues/318)); the pinned executor has not yet passed an independent per-item post-state check. The known `create_order` write is also default-denied because it has no reviewed policy adapter. The workflow is manual-only and model calls can incur charges. A no-model runtime smoke test runs first.

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

The pure `evaluate_tau2_pending_items_prewrite` adapter reuses the exchange evidence checks but requires `pending` state and enforces Tau2's one-time-only rule. However, the dispatcher currently default-denies `modify_pending_order_items` before environment execution. Public reports [#317](https://github.com/sierra-research/tau2-bench/issues/317) and [#318](https://github.com/sierra-research/tau2-bench/issues/318) describe a possible upstream defect where multiple modified items inherit the final replacement variant's price/options; Tau2's replay-based DB oracle may not expose that corruption. We will re-enable this operation only after the pinned executor passes independent per-item post-state validation or the implementation is fixed and covered by regression tests.

## User default-address changes

The `evaluate_tau2_user_address_prewrite` policy binds the target to a fresh `get_user_details` result and the identity lookup, requires a complete address that differs from the stored default address, and requires the assistant to identify the customer and disclose the exact new address before confirmation. An explicitly conflicting postal code, stale user snapshot, or confirmation replay after a blocked attempt returns `NO_GO`.

## Delivered-item return requests

The `evaluate_tau2_return_prewrite` policy requires a fresh delivered-order snapshot, matching owner identity, item IDs and quantities present in the order, and a payment method that is either the original order payment method or a verified gift card belonging to the user. Before confirmation, the assistant must disclose the exact order/items/payment method and explain that this creates a return request followed by a return-instructions email. The adapter does not claim that a refund has already occurred.

## Fail-closed patching

`scripts/install_tau2_prewrite_guard.py` verifies the checked-out Tau2 commit before patching. It replaces exactly one known dispatch-loop snippet and refuses to modify unknown or ambiguous source layouts. This avoids silently applying a brittle patch to a different upstream version.

The manual workflow then runs:

```bash
PYTHONPATH="../src${PYTHONPATH:+:$PYTHONPATH}" uv run python ../scripts/smoke_test_tau2_prewrite_guard.py
```

The runtime smoke test uses Tau2's actual patched `BaseOrchestrator._execute_tool_calls` method with a counting fake environment, not a model and not a real database. It proves:
- the saved baseline, whose final confirmation omits the order ID and old item IDs, returns `NO_GO` and makes zero environment calls;
- an unreviewed `create_order` request is denied by the dispatcher and makes zero environment calls;
- a synthetic complete disclosure followed by an affirmative reply returns `GO` and makes exactly one fake environment call;
- a second exchange for the same order in one batch is blocked, so only the first approved exchange reaches the fake environment callback;
- a valid pending-order cancellation reaches the fake callback only after exact refund disclosure, while missing disclosure is blocked before callback;
- a valid pending-order address change reaches the fake callback only after exact address disclosure, while a missing field is blocked before callback;
- a valid pending-order payment-method change reaches the fake callback only after the proposed method is verified and disclosed, while missing disclosure is blocked before callback;
- a plausible pending-order item modification is deliberately denied before the fake callback because the pinned executor has not passed independent per-item post-state verification;
- a valid user default-address change reaches the fake callback only after the identity and exact address are verified, while missing disclosure is blocked before callback;
- a valid delivered-item return reaches the fake callback only after item/payment authorization and follow-up-process disclosure, while missing disclosure is blocked before callback.

The full AWA test suite separately tests the evidence adapter and patcher's idempotency/source-layout checks.

## Scope and limitations

This is a **simulator-specific enforcement experiment**, not a production authorization system.

- Six retail write paths are currently enabled through simulator-specific reviewed adapters: `exchange_delivered_order_items`, `cancel_pending_order`, `modify_pending_order_address`, `modify_pending_order_payment`, `modify_user_address`, and `return_delivered_order_items`. `modify_pending_order_items` has a pure preflight policy but is disabled at dispatch until its multi-item post-state semantics are independently verified. `create_order` is blocked because it has no reviewed adapter. Read-only and generic non-write tools continue through the normal dispatch path.
- Tau2's simulated identity lookup and in-memory database are benchmark evidence, not production authentication or trusted payment authorization.
- The normalized trajectory is not cryptographically authenticated; the adapter must not be used as proof of real customer identity.
- This source patch is applied in the workflow checkout and is not automatically installed into the upstream Tau2 repository or a user's local environment.
- A real application must enforce the same control in the trusted service that owns the write, use server-side identity/session context, verify current order/payment state, and prevent time-of-check/time-of-use changes with a transaction or version check.
- The workflow is manual-only; its model-backed task may incur provider charges. The no-model dispatch smoke test runs before the model task.

Do not infer production readiness from a passing Tau2 run or a passing AWA report.
