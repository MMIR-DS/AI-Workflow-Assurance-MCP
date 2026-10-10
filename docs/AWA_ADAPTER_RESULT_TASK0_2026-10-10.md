# AWA Adapter Result — Retail Task 0 — 2026-10-10

## Outcome

The saved tau2 result was passed through `scripts/adapt_tau2_results.py` and the repository's AWA evaluator.

- AWA release decision: **GO**
- Acceptance criteria passed: **14/14** (pass rate 1.0)
- Critical failures: **0**
- High failures: **0**
- tau2 reward: **1.0**
- tau2 final-state oracle: matched
- tau2 expected action checks: **5/5 matched**
- End-to-end simulation duration: approximately **17.79 seconds**
- Sum of per-message provider usage cost metadata: approximately **$0.01660 USD**

The last cost is a sum of per-call usage metadata in the saved trace, not an invoice. tau2's aggregate cost field reported zero because LiteLLM did not have pricing metadata mapped for this OpenRouter model. Reconcile with OpenRouter's activity/billing view for the final billed amount.

## What is genuinely checked by the adapter

The adapter derives authentication order, order-status read-before-write, user confirmation, the exchange action arguments, notification text, absence of a new-order/transfer tool call, and elapsed time from the recorded trace. It fingerprints and evaluates the normalized expected/actual pair with AWA.

## Important limitation

This first GO result is **not independent proof of all business rules**. The adapter uses tau2's `db_match` oracle for final-state/unrelated-mutation checks, and tau2's expected action checks plus task-0 expected action for variant/payment matching. A full independent database diff was not present in the exported trace. The expected values are specific to task 0 and must not be reused unchanged for other tasks.

This is evidence that the integration path runs end-to-end on one known-good case. The next validation must include deliberately mutated/negative cases to prove AWA reliably returns `NO_GO` when a critical policy violation is introduced, without relying solely on tau2's reward.
