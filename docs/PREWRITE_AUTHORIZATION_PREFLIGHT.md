# Pre-write authorization preflight (reference control)

## Why this exists

The 2026-10-11 Tau2 retail run reached the expected exchange state but AWA correctly returned `NO_GO`: the assistant had not disclosed the exact stored payment-method identifier in its customer-facing confirmation before the write. A post-run evaluator can detect that policy failure, but detection after a mutation is not prevention.

This module introduces a deterministic preflight contract for a calling application to check before a sensitive write.

## Contract

Call `evaluate_prewrite(action, evidence)` with normalized objects. The preflight returns `GO` only if all checks pass:

- action contains a non-empty order ID, unique non-empty old/new item ID lists, and a non-empty payment-method ID;
- the identity evidence explicitly says verified, and the verified user matches the order owner and target order;
- the order status is `delivered`;
- explicit confirmation exactly matches the proposed order, old/new items, payment method, and a confirmation ID;
- the customer-facing confirmation contains the same action details and explicitly records that the exact payment method was disclosed;
- the confirmation event sequence is a positive integer earlier than the proposed write sequence.

Missing, malformed, mismatched, or incorrectly ordered evidence returns `NO_GO`. Python booleans are not accepted as integer event sequences.

## Current implementation boundary

**This is a reference preflight, not a write interceptor.** It does not execute a write, connect to Tau2, verify identity-provider signatures, or independently authenticate the evidence. A caller must enforce the rule `if decision != "GO": do not invoke the write tool`. The caller must also derive the evidence from trusted sources; passing caller-controlled JSON to this function does not make that evidence trustworthy.

The function is not yet wired into Tau2's actual `exchange_delivered_order_items` execution path. Therefore this addition demonstrates and tests the policy contract, but must not be described as blocking real environment writes until an executor integration is implemented and tested.

## Test

```bash
pytest tests/test_prewrite_guard.py
ruff check src/ai_workflow_assurance_mcp/prewrite_guard.py tests/test_prewrite_guard.py
```

Tests cover the positive case, missing payment disclosure, payment mismatch, confirmation after the proposed write, identity/order-state mismatch, malformed duplicate item IDs, strict boolean handling, missing evidence, and input immutability.
