# AI Workflow Assurance MCP

Deterministic acceptance checks for AI workflow runs, exposed as an MCP server and a local CLI.

**Version:** 0.1.3

This repository contains the source for **AI Workflow Assurance MCP v0.1.3**: core evaluation logic, MCP stdio adapter, CLI, tests, examples, and CI.

## What it does

Given a workflow specification (criteria + thresholds) and normalized expected/actual observations, AWA:

- validates the specification
- evaluates cases deterministically
- groups failures by criterion/severity
- compares baseline vs candidate runs
- produces a threshold-based release decision (`GO` / `HOLD` / `NO_GO`)

It does **not** run agents, call model APIs, or manage environments. An adapter must convert traces and final state into the observation contract.

## Install

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
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
```

## MCP server

```bash
ai-workflow-assurance-mcp
# or
python -m ai_workflow_assurance_mcp.server
```

Tools: `validate_workflow_spec`, `run_eval_suite`, `compare_eval_runs`, `explain_failures`, `generate_release_report`.

## Tests

```bash
pytest
ruff check src tests scripts
```

## Public retail workflow pack

A separate public pack abstracts the simulated **τ³-bench / tau2-bench** retail multi-item exchange policy into an AWA workflow spec and scenario matrix. That pack does not ship agent trajectories; normalize real traces before evaluation.

Pinned pack checksum (when using the published ZIP):

`34e08942fba2da825b42b5a91394425a1fc5dbd348093bf40374478677de4af8`

## Optional: tau2 + AWA prototype benchmark

`.github/workflows/tau2-retail-smoke.yml` is a **manual-only** OpenRouter-backed run against public `sierra-research/tau2-bench` retail task 0. It makes a model call only when manually started and requires repository secret `OPENROUTER_API_KEY`. Output is capped at 2,048 tokens per model request. Model calls may incur charges.

The trace adapter `scripts/adapt_tau2_results.py` evaluates recorded order/product payloads and does **not** use tau2's reward, `db_match`, or action-check fields to make the release decision. The task-0 workflow pack has 16 checks, including pre/post order-field comparison, variant availability/options, original-payment consistency, and price-difference reconciliation.

A separate no-model [workflow](.github/workflows/awa-independent-db-check.yml) runs `scripts/verify_tau2_independent_db.py` and adds an independent **replay-time** state read. It checks out the tau2-bench commit recorded in the trace, loads a clean RetailDB, verifies that its initial order matches the recorded pre-write read, replays only the saved exchange write, discards the write method's return value, and reads the resulting order directly from `RetailDB.orders`. It compares that state with the recorded exchange response, checks the selected method against the loaded user payment profile and original transaction, recalculates the price delta, verifies that no other orders/users/products changed, and includes a tampered-response negative control. This is independent corroboration from a separate deterministic replay—not a forensic snapshot of the original model run's live in-memory database. The notification criterion still checks assistant wording, not actual email-provider delivery.

On the saved 2026-10-10 task-0 run, AWA returned `GO` with **16/16 checks passing**. A no-model replay then applied six independent mutations to copies of the recorded trace/tool payloads. All six were rejected with `NO_GO` while the recorded tau2 reward, database-match flag and expected-action checks stayed unchanged. The mutations cover missing confirmation, unavailable selected variant, unrelated order-state change, price-difference mismatch, payment-method mismatch, and product-family mismatch. This is controlled evidence mutation on one public simulated task—not six new environment runs or a broad reliability study.

See the [original tau2 run](https://github.com/MMIR-DS/AI-Workflow-Assurance-MCP/actions/runs/38047957343), [successful six-mutation replay](https://github.com/MMIR-DS/AI-Workflow-Assurance-MCP/actions/runs/38059062409), [CI for Python 3.10–3.13](https://github.com/MMIR-DS/AI-Workflow-Assurance-MCP/actions/runs/38059062398), [adapter report](docs/AWA_ADAPTER_RESULT_TASK0_2026-10-10.md), and [mutation-test report](docs/AWA_MUTATION_TEST_RESULT_2026-10-10.md). Per-call usage metadata from the original trace totals approximately $0.01660; verify the final charge in OpenRouter's billing/activity view. The replay workflow is manual-only, reuses a saved result or committed fixture, makes no fresh model calls, and is currently left manual-only after the verified run.

## License

MIT — see [LICENSE](LICENSE).

## Security

See [SECURITY.md](SECURITY.md). Local/tool-boundary use only; do not treat v0.1.x as multi-tenant SaaS hardening.
