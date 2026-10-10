# Quick demo: catch a workflow regression

This demo uses **synthetic invoice-matching observations**. It makes no model/API calls.

## 1. Install and validate

```bash
python -m pip install -e ".[dev]"
ai-workflow-assurance validate-spec --spec examples/invoice_matching/workflow.json
```

The workflow specification defines what must be true: the decision and human-review flag must match the reviewed expected values, the amount variance must be within tolerance, and a rationale must exist.

## 2. Evaluate a candidate that passes

```bash
ai-workflow-assurance release \
  --spec examples/invoice_matching/workflow.json \
  --cases examples/invoice_matching/cases_candidate.json \
  --fail-on-non-go
```

Expected result: `"decision": "GO"` and exit code `0`. The CLI emits a JSON report.

## 3. Evaluate the baseline that contains a regression

```bash
ai-workflow-assurance release \
  --spec examples/invoice_matching/workflow.json \
  --cases examples/invoice_matching/cases_baseline.json \
  --fail-on-non-go
```

The baseline intentionally contains a mismatch: a quantity-mismatch invoice is approved even though the expected outcome is human review. The release decision should be non-`GO`, and `--fail-on-non-go` should return exit code `1` after emitting the report.

This is the key distinction: a report can explain a failed evaluation, while the exit code lets CI treat a non-`GO` decision as a failed gate.

## What this proves—and what it does not

- It proves the checker can distinguish these two **bundled, synthetic input sets** under the included rules.
- It does not prove that the observations faithfully represent a real agent run. An adapter must collect and normalize those observations correctly.
- It is not a production safety certification, a broad reliability estimate, or evidence that arbitrary agents are sandboxed.

For a full pre-release checklist, see [Release acceptance](RELEASE_ACCEPTANCE.md).
