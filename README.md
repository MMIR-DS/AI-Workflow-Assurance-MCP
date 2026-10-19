# AI Workflow Assurance MCP

[![CI](https://github.com/MMIR-DS/AI-Workflow-Assurance-MCP/actions/workflows/ci.yml/badge.svg)](https://github.com/MMIR-DS/AI-Workflow-Assurance-MCP/actions/workflows/ci.yml)

Deterministic evaluation logic for AI workflow observations, exposed as an MCP server and a local CLI. Reports include run-specific metadata.

**Development version:** 0.1.7 (unreleased)

This repository contains the current source for development version **AI Workflow Assurance MCP 0.1.7**: core evaluation logic, MCP stdio adapter, CLI, tests, examples, and CI. The release remains pending its acceptance checklist.

**Project ownership and AI assistance:** Human-led by Mohammad Mir, with substantial hands-on engineering-copilot contributions from OpenAI ChatGPT. See [roles, contributions, and verification boundaries](docs/AI_ASSISTED_DEVELOPMENT.md).

## What it does

Given a workflow specification (criteria + thresholds) and normalized expected/actual observations, AWA:

- validates the specification
- evaluates cases deterministically with explicit `PASS`, `FAIL`, and `NOT_EVALUABLE` outcomes
- requires fully evaluable evidence for `GO`; any `NOT_EVALUABLE` criterion blocks `GO` (`HOLD` unless another release-gate check fails, then `NO_GO`)
- distinguishes `NO_GO` (a configured release gate failed), `HOLD` (the evidence is incomplete and no gate failed), and `GO` (all configured gates pass with complete criterion evidence)
- groups definite failures and not-evaluable checks separately, with criterion and case IDs for triage
- compares baseline vs candidate runs
- produces a threshold-based release decision (`GO` / `HOLD` / `NO_GO`)

Determinism applies to evaluation results and decision logic for identical inputs; `run_id` and `executed_at` intentionally vary between reports. The **core evaluation path** consumes supplied observations; it does not run agents, call model APIs, or manage their environments. Separate optional Tau2 simulator tooling and a manually triggered model-backed workflow are documented below and are not production integrations. An adapter must preserve the distinction between an absent required workflow output and a genuine observation gap; see the [observation and adapter contract](docs/OBSERVATION_ADAPTER_CONTRACT.md).

## Quickstart (synthetic data; no model calls)

Create an environment and install the development version:

```bash
python -m venv .venv
source .venv/bin/activate  # macOS/Linux; PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Validate the included invoice workflow and run its passing candidate through the release gate:

```bash
ai-workflow-assurance validate-spec --spec examples/invoice_matching/workflow.json
ai-workflow-assurance release --spec examples/invoice_matching/workflow.json --cases examples/invoice_matching/cases_candidate.json --fail-on-non-go
```

The expected candidate result is `GO` with exit code `0`. To see a deliberately failing baseline, replace `cases_candidate.json` with `cases_baseline.json`; the non-`GO` gate emits its report and exits `1`. Invalid input returns `2`. See the [full quick demo](docs/QUICK_DEMO.md) for interpretation and limitations.

Useful commands are `evaluate`, `explain`, `compare`, and `release`; `inspect-evidence` validates and normalizes a saved Tau2 manifest. **It is an evidence-inspection command, not a release gate:** a syntactically and semantically valid manifest may describe a `HOLD` or `NO_GO` simulator result and still exit `0`. Invalid inputs return `2`.

Requires Python 3.10+.

## MCP server

```bash
ai-workflow-assurance-mcp
# or
python -m ai_workflow_assurance_mcp.server
```

Tools: `validate_workflow_spec`, `run_eval_suite`, `compare_eval_runs`, `explain_failures`, `generate_release_report`, `inspect_tau2_evidence_manifest`, `inspect_github_actions_run`, and `preflight_delivered_item_exchange`.

The `preflight_delivered_item_exchange` MCP tool is an **exchange-specific reference check** for replacing items on a delivered retail order—not a general policy for other writes. The generic MCP tool itself does not intercept a write; its caller must enforce `NO_GO`. A `GO` result evaluates caller-supplied values and does not authenticate their provenance or prove customer identity. Separately, this repo's V6 installer and smoke test patch and verify the actual dispatcher in a pinned Tau2 **simulator workflow checkout**; they do not provide a production commerce integration. See [preflight scope](docs/PREWRITE_AUTHORIZATION_PREFLIGHT.md), [guarded execution boundary](docs/GUARDED_EXECUTION_BOUNDARY.md), and [Tau2 enforcement limits](docs/TAU2_PREWRITE_ENFORCEMENT.md).

Evidence inspection tools return bounded, allowlisted fields and always retain `source_authenticity=not_verified` and `release_eligible=false`. `inspect_github_actions_run` reads metadata for one explicitly selected run and requires a read-only Actions token, repository, run ID, expected commit SHA, optional freshness limit, and `AWA_GITHUB_ALLOWED_REPOSITORIES` (a comma-separated repository allowlist; requests outside it are denied before network access). A successful CI run is not production proof. See [GitHub Actions evidence contract](docs/GITHUB_ACTIONS_EVIDENCE_SOURCE.md) and [simulator manifest contract](docs/READ_ONLY_EVIDENCE_SOURCE_CONTRACT.md).

## Tests

```bash
python -m pytest
ruff check src tests scripts
```

## Deterministic assurance mutation harness

Run the local, no-model harness and its focused regression tests:

```bash
python scripts/run_assurance_mutation_harness.py
python -m unittest tests.test_mutation_harness
```

Run the focused source-code mutation smoke test (ten hand-selected mutants; not comprehensive mutation testing):

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

## Optional Tau2 simulator showcase

This repository also contains Tau2-specific pre-write and post-write tooling. The large simulator dispatcher/pre-write/post-write implementation modules stay in the repository source tree for CI and the manual Tau2 showcase but are excluded from the generic Python wheel. Lightweight Tau2 manifest inspection remains in the generic package; a separately installable `awa-tau2` add-on has **not** been created. The generic evaluator itself only assesses supplied observations. Tau2-specific guards are simulator integrations, not a production control plane. See [packaging boundaries](docs/PACKAGING_BOUNDARIES.md).

The workflow `.github/workflows/tau2-retail-smoke.yml` is **manual-only** and runs one bounded public Tau2 retail task using Google's Gemini Developer API directly through LiteLLM. It requires the repository Actions secret `GEMINI_API_KEY` and uses `gemini/gemini-3.8-flash`, which Google's published pricing lists as free of charge on the Standard Free Tier, subject to rate limits and account/region eligibility. The Free Tier may use submitted content to improve Google products, so this showcase uses synthetic benchmark data only; do not send confidential or real customer data. The workflow can be triggered from the Actions page only when you deliberately want to spend free-tier quota. The adapter evaluates recorded observations and does not use Tau2 reward, `db_match`, or action-check fields as its release oracle.

Evidence is limited to a saved task-0 run and deterministic replay/mutation checks; these are not fresh model runs or a general reliability estimate. **Prompt provenance matters:** the original Tau2 run [#38047957343](https://github.com/MMIR-DS/AI-Workflow-Assurance-MCP/actions/runs/38047957343) is a historical **unpatched-prompt** baseline (its workflow revision predates the prompt patch step). The saved-trace mutation replay [#38059062409](https://github.com/MMIR-DS/AI-Workflow-Assurance-MCP/actions/runs/38059062409) replays that same unpatched trace; it is not another agent run. Do not compare either result as if it used the patched prompt. New manual smoke runs apply `AWA_RETAIL_LOOKUP_GUIDANCE_V1` and their `adapter_metadata.json` records `prompt_provenance.mode=patched`, the exact marker, and a verification status. Historical artifacts without those fields must be treated as provenance-unknown unless their workflow revision independently establishes the prompt mode. See the [pre-write enforcement boundary](docs/TAU2_PREWRITE_ENFORCEMENT.md), [source evidence contract](docs/TAU2_SOURCE_EVIDENCE_MANIFEST.md), [independent replay workflow](.github/workflows/awa-independent-db-check.yml), [recorded adapter result](docs/AWA_ADAPTER_RESULT_TASK0_2026-10-10.md), and [mutation report](docs/AWA_MUTATION_TEST_RESULT_2026-10-10.md).

## Release acceptance

Before tagging a release, follow the [clean-checkout release acceptance checklist](docs/RELEASE_ACCEPTANCE.md). For the real Windows client handshake and tool-invocation check, use the [VS Code MCP client acceptance guide](docs/MCP_CLIENT_ACCEPTANCE_WINDOWS.md). If no Windows desktop is available, CI provides a hosted Windows installed-wheel MCP protocol smoke as a documented fallback; it does not count as a VS Code GUI test, as explained in the release checklist.

## License

MIT — see [LICENSE](LICENSE).

## Security

See [SECURITY.md](SECURITY.md). Local/tool-boundary use only; do not treat v0.1.x as multi-tenant SaaS hardening.
