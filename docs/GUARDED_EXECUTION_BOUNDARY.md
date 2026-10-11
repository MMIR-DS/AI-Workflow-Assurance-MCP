# Guarded execution boundary

## Purpose

The preflight evaluator in `prewrite_guard.py` returns a deterministic `GO` or `NO_GO`. That alone cannot stop an application from proceeding. `guarded_executor.py` adds a callback boundary: it invokes the supplied write operation only after the preflight returns `GO`.

## Host integration contract

The host application should replace direct sensitive-write calls with this pattern:

```python
from ai_workflow_assurance_mcp.guarded_executor import execute_if_prewrite_allowed

outcome = execute_if_prewrite_allowed(action, trusted_evidence, write_exchange)
if not outcome["executed"]:
    # Return a safe denial to the caller; do not call the write tool elsewhere.
    return outcome
return outcome
```

The `write_exchange` callback must be the actual operation that mutates state. Every sensitive write path must go through the guarded executor; a parallel direct-call path makes the control optional and therefore insufficient.

## What is now tested

- A missing exact payment-method disclosure returns `NO_GO` and the write callback call count stays zero.
- A valid matching confirmation invokes the callback exactly once.
- Invalid action shape and a missing callback fail closed.
- The action passed to the callback is a copy, so the executor does not hand out the caller's original action object.
- A write exception propagates rather than being reported as success.

## Important limits

This is an application-side enforcement seam, **not yet wired into Tau2's real `exchange_delivered_order_items` path**. The MCP tool can evaluate caller-supplied JSON, but the host must call this executor around its actual mutation function. A future Tau2 integration must be made in the Tau2 repository or a maintained fork, pin the upstream commit, and add a test proving the real database write function is not called on `NO_GO`.

The evidence passed to the guard must come from trusted, independently obtained sources. The guard cannot authenticate caller-controlled JSON. In production, use verified identity/session context, server-side order and payment records, an auditable customer-confirmation event, and enforce the guard and write in one trusted service boundary. Protect against time-of-check/time-of-use changes by re-reading or version-checking the order immediately before mutation and using a transaction or conditional write.

Do not represent this code as production security or as proof that Tau2 writes are currently blocked.
