# Observation and adapter contract

## Purpose

AWA evaluates the observations supplied to it; it does not know whether a missing field means that the workflow failed to produce a required output or that an adapter could not collect trustworthy evidence. The adapter must preserve that distinction explicitly.

## Status semantics

- **PASS** — the supplied, observed values satisfy the criterion.
- **FAIL** — the criterion was observed to be violated, or a required path is absent from the supplied observation and the criterion was not explicitly marked unobserved. This is the default, fail-closed behavior.
- **NOT_EVALUABLE** — the case's `unobserved_checks` explicitly identifies the criterion as not evaluable from the evidence actually collected.

A missing path does **not** automatically mean `NOT_EVALUABLE`. AWA intentionally does not guess why it is missing. For example, if a workflow is required to return `actual.decision` and it omits that output, that is ordinarily a failed observation of the workflow contract. Do not mark it unobserved merely because the expected output is absent.

By contrast, if an upstream evidence collector or integration genuinely could not observe the decision (for example, the source was unavailable or the trace did not capture that event), the adapter may list the criterion ID in `unobserved_checks`. That explicit declaration produces `NOT_EVALUABLE`, which prevents an unsupported factual claim of failure and causes an otherwise unknown-only release gate to return `HOLD`.

## Case-authoring rules

1. **Preserve observed values faithfully.** Do not omit or rewrite a value to make a check easier to pass. A present JSON `null` is still a present, observed value; it is not automatically treated as unavailable evidence.
2. **Use `unobserved_checks` only for genuine observation gaps.** Its value must be a list of unique criterion IDs that exist in the workflow specification. Do not use it to downgrade a known violation or a missing workflow output that is itself the behavior being tested.
3. **Reject bad test setup separately.** If the expected/ground-truth data or the evaluation specification is incomplete, repair or reject the test case upstream. Do not relabel incorrect expected data as a source-observation gap.
4. **Retain mixed outcomes.** If one criterion is genuinely unobserved but another is a known violation, keep both statuses. The known failure remains a failure and can produce `NO_GO`.
5. **Record the reason in adapter-side diagnostics.** The case contract uses criterion IDs to represent what was not observed; adapters should retain their own bounded diagnostics explaining the source gap without placing secrets or unnecessary personal data in the evaluation report.

## Example

Suppose the specification has a critical criterion named `decision_matches` comparing the expected value at `decision` with the actual value at `decision`.

**The workflow failed to produce a required output:** leave `decision_matches` out of `unobserved_checks`. If the actual path is absent, AWA reports `FAIL`; the release decision must reflect the known contract violation.

**The collector could not observe the output:** the adapter supplies the available observations and explicitly lists the criterion:

```json
{
  "case_id": "trace-with-observation-gap",
  "expected": {"decision": "approve"},
  "actual": {},
  "unobserved_checks": ["decision_matches"]
}
```

This criterion is reported as `NOT_EVALUABLE`. If no other criterion failed, the corresponding release decision is `HOLD`, not `GO`.

If the collector did observe `decision: "deny"` while the expected value is `"approve"`, the adapter must not mark this criterion unobserved: it is a real mismatch and should remain `FAIL`.

## Security and release boundary

The evaluator cannot independently verify that an adapter's `unobserved_checks` declaration is truthful. A bad adapter can misclassify an observed violation as unobserved. Treat the adapter as part of the assurance boundary: review its evidence mapping, test observed-mismatch and missing-output negative controls, and document how it decides between source collection failure and workflow failure. A `HOLD` only says the available evidence is insufficient under the supplied case contract; it is not proof that the workflow itself behaved correctly.

## Related implementation and tests

- Core status assignment: `src/ai_workflow_assurance_mcp/core.py`
- Regression tests: `tests/test_core.py`
- Retail-specific example contract: `docs/RETAIL_EXCHANGE_ADAPTER_CONTRACT.md`

