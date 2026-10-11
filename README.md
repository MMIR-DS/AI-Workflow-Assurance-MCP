# AI Workflow Assurance MCP

[![CI](https://github.com/MMIR-DS/AI-Workflow-Assurance-MCP/actions/workflows/ci.yml/badge.svg)](https://github.com/MMIR-DS/AI-Workflow-Assurance-MCP/actions/workflows/ci.yml)

Deterministic evaluation logic for AI workflow observations, exposed as an MCP server and a local CLI. Reports include run-specific metadata.

**Version:** 0.1.7

This repository contains the source for **AI Workflow Assurance MCP v0.1.7**: core evaluation logic, MCP stdio adapter, CLI, tests, examples, and CI.

## What it does

Given a workflow specification (criteria + thresholds) and normalized expected/actual observations, AWA:

- validates the specification
- evaluates cases deterministically with explicit `PASS`, `FAIL`, and `NOT_EVALUABLE` outcomes
- keeps unknown evidence distinct from a proven failure; unknown-only release gates return `HOLD`, while observed failures remain `NO_GO`
- groups definite failures and not-evaluable checks separately, with criterion and case IDs for triage
- compares baseline vs candidate runs
- produces a threshold-based release decision (`GO` / `HOLD` / `NO_GO`)

Determinism applies to evaluation results and decision logic for identical inputs; `run_id` and `executed_at` intentionally vary between reports. It does **not** run agents, call model APIs, or manage environments. An adapter must convert traces and final state into the observation contract.

## Quick demo

Try the [reproducible invoice-matching demo](docs/QUICK_DEMO.md). It compares a passing synthetic candidate with a deliberately failing baseline and demonstrates how `--fail-on-non-go` can block a CI release gate without making model calls. For a business-workflow example, see the [retail exchange evidence contract and adapter](docs/RETAIL_EXCHANGE_ADAPTER_CONTRACT.md); its bundled observation is synthetic and the contract requires a trusted source adapter for live use. Review the [retail adapter threat model](docs/THREAT_MODEL_RETAIL_EXCHANGE.md) before designing a live integration.

## Install

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e ".[dev]"
```

Requires Python 3.10+.

## CLI

```bash
ai-workflow-assurance validate-spec --spec path/to/workflow.json
ai-workflow-assurance evaluate --spec path/to/workflow.json --cases path/to/cases.json
ai-workflow-assurance explain --spec path/to/workflow.json --cases path/to/cases.json
ai-workflow-assurance compare --spec path/to/workflow.json --baseline base.json --candidate cand.json
ai-workflow-assurance release --spec path/to/workflow.json --cases path/to/cases.json
# Optional: return exit code 1 when the decision is HOLD or NO_GO
ai-workflow-assurance release --spec path/to/workflow.json --cases path/to/cases.json --fail-on-non-go
# Validate and normalize a saved tau2 simulator evidence manifest (not production evidence)
ai-workflow-assurance inspect-evidence --manifest artifacts/awa-source-evidence-manifest.json
```

## MCP server

```bash
ai-workflow-assurance-mcp
# or
python -m ai_workflow_assurance_mcp.server
```

Tools: `validate_workflow_spec`, `run_eval_suite`, `compare_eval_runs`, `explain_failures`, `generate_release_report`, `inspect_tau2_evidence_manifest`, and `inspect_github_actions_run`.

The evidence inspection tools are read-only and return bounded, allowlisted evidence envelopes. `inspect_tau2_evidence_manifest` accepts manifest JSON text and validates the simulator evidence contract. `inspect_github_actions_run` reads metadata for one explicitly selected GitHub Actions run; set `GH_TOKEN` (preferred) or `GITHUB_TOKEN` in the MCP server process with read-only Actions access. It requires a repository (`owner/name`), run ID, expected 40-character head SHA, and optional freshness window in seconds.

Example MCP arguments for `inspect_github_actions_run`:

```json
{
  "repository": "owner/repository",
  "run_id": 123456789,
  "expected_head_sha": "0123456789abcdef0123456789abcdef01234567",
  "max_age_seconds": 3600
}
```

A successful GitHub Actions run is not proof that a production workflow or underlying business operation was correct. Both evidence tools always preserve `source_authenticity=not_verified`; neither makes evidence release-eligible. Review [the GitHub Actions evidence source trust boundary](docs/GITHUB_ACTIONS_EVIDENCE_SOURCE.md) before using this adapter.

## Tests

```bash
pytest
ruff check src tests scripts
```

## Deterministic assurance mutation harness

Run the local, no-model harness and its focused regression tests:

```bash
python scripts/run_assurance_mutation_harness.py
python -m unittest tests.test_mutation_harness
```

Run the focused source-code mutation smoke test (eight hand-selected mutants; not comprehensive mutation testing):

```bash
python scripts/run_source_mutation_smoke.py
# Optional: save a JSON report
python scripts/run_source_mutation_smoke.py --output artifacts/mutation-report.json
```

The harness checks one valid control and five seeded observation faults, including a missing required path and boolean/numeric type confusion. It reports fault detection, control false rejections, and repeatability. This is **input-fault detection**, not source-code mutation testing or a production reliability estimate; see [scope and interpretation](docs/AWA_MUTATION_HARNESS.md).

## Public retail workflow pack

A separate public pack abstracts the simulated **τ³-bench / tau2-bench** retail multi-item exchange policy into an AWA workflow spec and scenario matrix. That pack does not ship agent trajectories; normalize real traces before evaluation.

Pinned pack checksum (when using the published ZIP):

`34e08942fba2da825b42b5a91394425a1fc5dbd348093bf40374478677de4af8`

## Optional: tau2 + AWA prototype benchmark

`.github/workflows/tau2-retail-smoke.yml` is a **manual-only** OpenRouter-backed run against public `sierra-research/tau2-bench` retail task 0. It makes a model call only when manually started and requires repository secret `OPENROUTER_API_KEY`. Output is capped at 2,048 tokens per model request. Model calls may incur charges.

The trace adapter `scripts/adapt_tau2_results.py` evaluates recorded order/product payloads and does **not** use tau2's reward, `db_match`, or action-check fields to make the release decision. The task-0 workflow pack has 16 checks, including pre/post order-field comparison, variant availability/options, original-payment consistency, and price-difference reconciliation.

A read-only [evidence-manifest adapter](docs/TAU2_SOURCE_EVIDENCE_MANIFEST.md) packages the independent replay report without making model calls or database writes. The [read-only evidence source contract](docs/READ_ONLY_EVIDENCE_SOURCE_CONTRACT.md) defines a normalized provenance envelope and a reference file adapter for the simulator manifest; the `inspect-evidence` CLI command validates and prints that normalized envelope with a 1 MiB input limit. The optional [GitHub Actions read-only evidence adapter](docs/GITHUB_ACTIONS_EVIDENCE_SOURCE.md) reads metadata for one explicitly selected run, checks repository/commit/status/freshness, and returns only allowlisted fields. The MCP tool `inspect_github_actions_run` exposes this adapter without accepting arbitrary URLs or filesystem paths; it uses `GH_TOKEN`/`GITHUB_TOKEN` from the server environment. It requires a read-only token and always sets `source_authenticity=not_verified` and `release_eligible=false`; CI success alone is not production proof. It is an interface contract, not a live commerce connector or a production trust boundary. A separate no-model [workflow](.github/workflows/awa-independent-db-check.yml) runs `scripts/verify_tau2_independent_db.py` and adds an independent **replay-time** state read. It checks out the expected tau2-bench commit pinned to match the trace's recorded `git_commit` and fails closed on a mismatch, loads a clean RetailDB, and verifies that its initial order matches the recorded pre-write read, replays only the saved exchange write, discards the write method's return value, and reads the resulting order directly from `RetailDB.orders`. It compares that state with the recorded exchange response, checks the selected method against the loaded user payment profile and original transaction, recalculates the price delta, verifies that no other orders/users/products changed, and includes a tampered-response negative control. This is independent corroboration from a separate deterministic replay—not a forensic snapshot of the original model run's live in-memory database. The notification criterion still checks assistant wording, not actual email-provider delivery.

On the saved 2026-10-10 task-0 run, AWA returned `GO` with **16/16 checks passing**. A no-model replay then applied six independent mutations to copies of the recorded trace/tool payloads. All six were rejected with `NO_GO` while the recorded tau2 reward, database-match flag and expected-action checks stayed unchanged. The mutations cover missing confirmation, unavailable selected variant, unrelated order-state change, price-difference mismatch, payment-method mismatch, and product-family mismatch. This is controlled evidence mutation on one public simulated task—not six new environment runs or a broad reliability study.

See the [original tau2 run](https://github.com/MMIR-DS/AI-Workflow-Assurance-MCP/actions/runs/38047957343), [successful six-mutation replay](https://github.com/MMIR-DS/AI-Workflow-Assurance-MCP/actions/runs/38059062409), [CI for Python 3.10–3.13](https://github.com/MMIR-DS/AI-Workflow-Assurance-MCP/actions/runs/38059062398), [adapter report](docs/AWA_ADAPTER_RESULT_TASK0_2026-10-10.md), and [mutation-test report](docs/AWA_MUTATION_TEST_RESULT_2026-10-10.md). Per-call usage metadata from the original trace totals approximately $0.01660; verify the final charge in OpenRouter's billing/activity view. The replay workflow is manual-only, reuses a saved result or committed fixture, makes no fresh model calls, and is currently left manual-only after the verified run.

## Release acceptance

Before tagging a release, follow the [clean-checkout release acceptance checklist](docs/RELEASE_ACCEPTANCE.md).

## License

MIT — see [LICENSE](LICENSE).

## Security

See [SECURITY.md](SECURITY.md). Local/tool-boundary use only; do not treat v0.1.x as multi-tenant SaaS hardening.
