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

`.github/workflows/tau2-retail-smoke.yml` is a **manual-only** OpenRouter-backed run against public `sierra-research/tau2-bench` retail task 0. After tau2 completes, `scripts/adapt_tau2_results.py` creates normalized cases, an AWA evaluation report, and an AWA release report. The adapter records which checks rely on tau2's own oracle; it does not independently diff the complete initial/final database. The notification criterion is explicitly a check of the assistant's message, not proof of provider-side email delivery.

Requires repository secret `OPENROUTER_API_KEY`. The workflow caps output at 2,048 tokens per model request and is manual-only to avoid surprise runs. Model calls may incur charges.

The bounded smoke run on 2026-10-10 completed retail task 0 with reward 1.0, a matching final database state, and 5/5 matched action checks. The new adapter `scripts/adapt_tau2_results.py` converts the trace into AWA cases and release reports. On this single known-good case, AWA returned `GO` with 14/14 criteria passing. See the [tau2 run](https://github.com/MMIR-DS/AI-Workflow-Assurance-MCP/actions/runs/38047957343), [tau2 result note](docs/TAU2_SMOKE_RESULT_2026-10-10.md), and [AWA adapter result and limitations](docs/AWA_ADAPTER_RESULT_TASK0_2026-10-10.md). Cost from per-call usage metadata sums to about $0.01660; tau2's aggregate cost field was unreliable for this model, so reconcile with OpenRouter billing. A no-model-call replay also mutates the saved raw trace by removing explicit customer confirmation. AWA returns `NO_GO` even though the saved tau2 reward, database-match flag and expected-action checks remain green. See [the mutation-test report](docs/AWA_MUTATION_TEST_RESULT_2026-10-10.md) and [replay workflow](.github/workflows/awa-replay-existing-tau2.yml). This validates one specific invariant on one task-0 fixture, not broad regression-detection effectiveness. The replay workflow is manual-only and reuses an archived result or a committed minimized fixture; it makes no new model calls.

## License

MIT — see [LICENSE](LICENSE).

## Security

See [SECURITY.md](SECURITY.md). Local/tool-boundary use only; do not treat v0.1.x as multi-tenant SaaS hardening.
