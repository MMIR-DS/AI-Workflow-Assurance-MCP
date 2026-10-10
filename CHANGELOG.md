# Changelog

## 0.1.3

- Enforce the documented JSON nesting cap of 64 containers (the previous check allowed one extra level).
- Turn non-finite fingerprint inputs into `AssuranceInputError` instead of an uncaught `ValueError`.
- Advertise the package version on the MCP initialize handshake.
- Fix Ruff import order so `ruff check src tests scripts` is clean.

## 0.1.2

- Escape lone Unicode surrogate code points in audit fingerprints so malformed text cannot crash digest generation.
- Limit JSON nesting depth and return controlled validation errors for deeply nested payloads.
- Canonicalize integral floats in fingerprints so values that compare numerically equal (for example `0` and `0.0`) do not cause false label-change errors.
- Align package `__version__` with project metadata.
- Use `zip(..., strict=True)` for explicit collection-length safety in recursive equality.
- Bound threshold previews by returning only known scalar threshold fields; never echo arbitrary unknown threshold payloads into an LLM context.
- Default MCP evaluation output to summary-only and make per-case comparison details opt-in.
- Add an optional independent release cap for high-severity failures and warn when it is absent.
- Cap case-ID previews in grouped failures and comparisons to keep responses bounded.
- Add regression tests for surrogate strings, nesting depth, fingerprint normalization, threshold/metadata preview bounds, and version consistency.
- Bump the report schema to `0.3` to mark the new `high_failures` summary field.

## 0.1.1

- Convert predictable MCP input validation errors into model-readable `ToolError` results.
- Make nested equality and list `contains` type-aware (`true` no longer equals `1`).
- Normalize oversized numeric/parser failures into controlled input errors.
- Add criteria and input-data fingerprints; refuse comparisons when expected labels or criteria differ.
- Report per-case and critical regressions explicitly.
- Recompute summary metrics from case-level evidence before release-gate evaluation.
- Preserve full precision for gate calculations and support maximum per-case cost/latency thresholds.
- Separate observed human review from the workflow's predicted review flag.
- Add a file-based CLI, summary-only outputs, and optional MCP stdio integration tests.
- Bound validation error output and warn on small test suites or missing critical criteria.
