# Guarded execution boundary

## Purpose

The preflight evaluator in `prewrite_guard.py` returns a deterministic `GO` or `NO_GO` for **retail item exchange on a delivered order only**. That alone cannot stop an application from proceeding. `guarded_executor.py` adds a generic callback boundary: it invokes the supplied callback only after this exchange-specific preflight returns `GO`.

The callback wrapper is generic plumbing; the policy inside it is not. Do not pair this preflight with a cancellation, address change, payment-method change, or another write type. Define and test an operation-specific evaluator before using the wrapper for a different action.

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

The generic `guarded_executor.py` callback is still an application-side seam, not a production commerce control. Separately, this repository now includes a **pinned Tau2 retail-simulator integration**: `scripts/install_tau2_prewrite_guard.py` applies a V6 patch to the actual dispatch loop for the pinned upstream Tau2 commit, and `scripts/smoke_test_tau2_prewrite_guard.py` verifies that a `NO_GO` does not invoke the dispatch write callback. The integration is applied only in the workflow checkout; it does not modify the upstream repository, a user's local Tau2 install, or any production commerce system. A production deployment still requires a maintained integration in the real application and tests against its actual database-write boundary.

The evidence passed to the guard must come from trusted, independently obtained sources. The guard cannot authenticate caller-controlled JSON. In production, use verified identity/session context, server-side order and payment records, an auditable customer-confirmation event, and enforce the guard and write in one trusted service boundary. Protect against time-of-check/time-of-use changes by re-reading or version-checking the order immediately before mutation and using a transaction or conditional write.

Do not represent the simulator smoke as production security or as proof that writes in a live commerce system are blocked. The pinned Tau2 workflow proves only that the patched simulator dispatcher blocks the tested `NO_GO` case before its environment callback.
