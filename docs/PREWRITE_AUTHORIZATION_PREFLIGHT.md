# Exchange-specific pre-write authorization preflight (reference control)

## Why this exists

The saved 2026-10-11 Tau2 retail trace shows that the exchange write ran even though its customer-facing pre-write confirmation omitted required details. The post-run adapter now evaluates that trace as `NO_GO`; a historical post-run result alone cannot prevent a write. The current repository also includes a distinct V6 integration that patches the actual dispatch loop in the pinned Tau2 simulator workflow and verifies that `NO_GO` blocks the environment callback before execution (see `TAU2_PREWRITE_ENFORCEMENT.md`). This simulator-only check is not a production commerce control.

This module introduces a deterministic, **exchange-specific** preflight contract for a calling application to check before a retail item-exchange write.

**Scope warning:** despite the broad name of the MCP tool (`preflight_sensitive_write`), this implementation is not a general policy for every sensitive operation. Its action schema requires old/new item IDs and a payment-method ID for an exchange on a delivered order. Do not use its `GO` result to authorize a cancellation, address change, payment-method change, or any other operation type. A different operation needs its own schema, evidence requirements, evaluator, and negative tests. The public tool name is retained for compatibility; its description explicitly limits the supported operation.

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

This generic evaluator remains a policy function, not an interceptor by itself. The separate Tau2-specific pre-write adapter is patched into the pinned simulator's `BaseOrchestrator._execute_tool_calls` path by the workflow installer, with a smoke test for callback suppression on `NO_GO`. Do not conflate that simulator integration with an application production deployment.

## Test

```bash
pytest tests/test_prewrite_guard.py
ruff check src/ai_workflow_assurance_mcp/prewrite_guard.py tests/test_prewrite_guard.py
```

Tests cover the positive case, missing payment disclosure, payment mismatch, confirmation after the proposed write, identity/order-state mismatch, malformed duplicate item IDs, strict boolean handling, missing evidence, and input immutability.
