# Architecture notes

## Design boundary

The project separates a deterministic evaluation core from the MCP protocol adapter and file-based CLI. The same acceptance logic can therefore be unit-tested, invoked from local automation, or exposed to an MCP-compatible host without duplicating calculations.

## Request path

1. An MCP host invokes a tool with JSON text, or the CLI reads local JSON files.
2. The shared JSON parser enforces input-size bounds and rejects unsupported numeric values.
3. Core validators reject unsupported schema/operator/path patterns.
4. Deterministic checks compare supplied actual values with reviewed expected values.
5. The MCP server returns structured report data without writing files; the CLI writes files only when an output path is explicitly supplied.

Comparison, failure-explanation, and release-report tools accept the source case data and recompute metrics server-side. They do not accept caller-supplied summary values as release evidence. The expected labels and case representativeness remain caller responsibilities.

## Why JSON text for the initial API

The MCP tool schema stays simple and the payloads can be used from several clients without depending on deeply nested generated schemas. The trade-off is less ergonomic input: a client must serialize the objects as JSON strings. This is acceptable for an alpha. A future version may use typed Pydantic models if validated against the target MCP hosts.

## What is—and is not—assured

Assured by code in the current scope:
- Input size and structure checks.
- Safe dotted-path lookup without arbitrary expression execution.
- Deterministic criterion results for supported operators.
- Explicit missing-data behavior for configured release thresholds.
- Bounded evaluation and failure-report sizes, including truncated previews for large values.
- Release reports are computed from case data in the same tool call, rather than trusting a passed-in summary.

Not assured by this project:
- That expected labels are correct or representative.
- The correctness of an external agent's logs.
- Security of an external agent's tools or environment.
- Statistical confidence from small or biased test sets.
- Production safety or regulatory compliance.

## Next technical step after validation

Pick one execution framework and define an adapter contract that supplies immutable input/output traces plus tool/action events. Avoid a generic adapter framework before a real customer requires it.


## v0.1.2 integrity notes

- JSON structures are limited to 64 nested container levels, including when the pure-Python API is called directly.
- Integral float values are normalized for audit fingerprints so fingerprint comparisons agree with numeric equality (`2` and `2.0`).
- High-severity checks can be independently capped with `thresholds.max_high_failures`; if omitted, the report warns that the pass-rate gate is the only high-failure control.
- MCP response detail is bounded by default; the caller can explicitly request detailed case-level output.

## v0.1.1 integrity notes

- The evaluator records SHA-256 fingerprints of the workflow spec, acceptance criteria, release thresholds, input cases, and each case's expected label. These fingerprints help detect accidental changes across runs; they are not signatures and do not authenticate the source of the data.
- Report validation recalculates summary metrics from per-case check evidence before making a release decision. Callers should still pass reports produced by the current evaluator and must not treat a digest as proof of provenance.
- `human_review_observed` is an explicit top-level observation of review handling. It is not inferred from the AI workflow's predicted `actual.requires_human_review` field. The legacy `human_review_required` field remains an alias.
- `run_eval_suite` defaults to `summary_only=true`; detailed cases are opt-in. MCP comparisons default to bounded previews, and the CLI reads local JSON files for larger datasets.
