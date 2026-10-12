# Changelog

## 0.1.7 (Unreleased)

- Guard all seven write tools in the pinned Tau2 retail toolkit at the actual orchestrator dispatch boundary, with operation-specific fail-closed policies for exchange, cancellation, order-address changes, payment-method changes, pending-item modifications, user default-address changes, and delivered-item returns.
- Explicitly default-deny Tau2 retail `create_order` because it has no reviewed AWA policy adapter; prove the environment callback is not reached in the no-model dispatcher smoke.
- Validate current order/user snapshots, identity-to-owner binding, item quantity and product matching, replacement availability, payment-method authorization, exact financial/address disclosure, fresh confirmation, and retry/batch protections before simulated writes.
- Add no-model runtime smoke coverage using Tau2's actual patched dispatch method and a counting fake environment, including cross-operation same-order batch blocking.
- Version the dispatcher patch as V4, reject stale V2/V3 or partial patched source, and explicitly deny unreviewed `create_order` dispatch; document the simulator-only trust boundary and production requirements.
- Bump the evaluation-report schema to `0.4` for explicit `PASS` / `FAIL` / `NOT_EVALUABLE` check statuses and separate counts for definite failures versus unobserved checks.
- Keep the release gate fail-closed: unknown-only evidence cannot produce `GO`; observed failing checks continue to block release.
- Extend `explain` output with separate, bounded groups and case-ID previews for checks that could not be evaluated.
- Treat Tau2 terminal traces without the expected exchange write as task non-completion, while avoiding inflated policy-violation counts from unobservable downstream assertions.
- Upgrade GitHub Actions workflows to pinned Node.js 24-compatible revisions and configure the Tau2 `uv` cache after checkout.

## 0.1.6

- Add a retail-exchange observation adapter contract, a threat model, and adversarial tests for event ordering, requested variants, payment consistency, price reconciliation, and notification evidence.
- Add a normalized read-only evidence-source contract and a strict tau2 simulator-manifest adapter; keep simulator evidence explicitly unauthenticated and ineligible for production release.
- Add bounded CLI and MCP manifest inspection, strict nested allowlists, consistency checks, and privacy-minimized public evidence artifacts.
- Add a read-only GitHub Actions run-metadata source and the `inspect_github_actions_run` MCP tool. Require explicit repository/run/commit inputs, successful and fresh run metadata, and read-only credentials; reject malformed IDs and inconsistent timestamps.
- Expand CI coverage for the release-gate demo, clean wheel installation, evidence-adapter smoke tests, and selected source mutations across Python 3.10–3.13.
- Document source trust boundaries and make clear that passing CI or simulator checks is not production authentication, certification, or release authorization.

## 0.1.5

- Clarify deterministic evaluation results versus run-specific report metadata.
- Add an opt-in CLI release gate that exits non-zero for `HOLD` and `NO_GO` decisions.
- Bound dotted-path traversal to 32 components and expose unknown threshold names in `validate-spec` output.
- Expand the focused source-mutation smoke set to eight selected mutations, including the CLI release gate.
- Verify the built wheel in a clean virtual environment with runtime dependencies installed.

## 0.1.4

- Reject release-report generation when the supplied workflow specification differs from the specification fingerprint in the evaluation report.
- Expand source-code mutation smoke coverage to seven selected fault classes, with environment-stamped JSON reports uploaded by CI for Python 3.10–3.13.
- Build and smoke-test the wheel outside the source tree in CI.
- Expand CLI acceptance tests and add a clean-checkout release acceptance checklist.


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
