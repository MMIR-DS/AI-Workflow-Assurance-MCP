# Release acceptance checklist

Use this checklist before tagging a release or presenting AWA as a reusable tool. It is an engineering checklist, not a safety certification.

## 1. Start from a clean checkout

```bash
git clone https://github.com/MMIR-DS/AI-Workflow-Assurance-MCP.git
cd AI-Workflow-Assurance-MCP
python -m venv .venv
```

Activate the virtual environment, then install the development extra:
- macOS/Linux: `. .venv/bin/activate`
- Windows PowerShell: `.venv\\Scripts\\Activate.ps1`

```bash
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## 2. Run the deterministic checks

```bash
python -m pytest
ruff check src tests scripts
python scripts/run_assurance_mutation_harness.py
python -m unittest tests.test_mutation_harness
python scripts/run_source_mutation_smoke.py
```

The source mutation smoke test must report all selected mutants killed. Its score applies only to the documented, hand-selected mutants; it is not a comprehensive mutation score.

## 3. Exercise the public CLI against the bundled example

```bash
ai-workflow-assurance validate-spec --spec examples/invoice_matching/workflow.json
ai-workflow-assurance evaluate --spec examples/invoice_matching/workflow.json --cases examples/invoice_matching/cases_candidate.json --summary-only
ai-workflow-assurance compare --spec examples/invoice_matching/workflow.json --baseline examples/invoice_matching/cases_baseline.json --candidate examples/invoice_matching/cases_candidate.json
ai-workflow-assurance explain --spec examples/invoice_matching/workflow.json --cases examples/invoice_matching/cases_baseline.json --max-items 10
ai-workflow-assurance release --spec examples/invoice_matching/workflow.json --cases examples/invoice_matching/cases_candidate.json
```

Review the JSON outputs rather than relying only on process exit codes. In particular, inspect the release decision, configured thresholds, warnings, and the assurance-scope note.

## 4. Verify the MCP boundary

The automated suite includes a stdio handshake and calls each exposed tool. For manual integration, launch:

```bash
ai-workflow-assurance-mcp
```

Use a local MCP client configured for stdio. Do not expose the process as a network service without a separate threat model and deployment review.

## 5. Verify the built artifact and CI

The CI workflow builds a wheel, installs it outside the source tree, checks the installed CLI entry point, runs the test suite and lint, and executes the source mutation smoke test on Python 3.10–3.13.

Before tagging, confirm the latest workflow run for the exact commit is green. Do not infer success from an earlier commit's run.

## 6. Review scope and release notes

- State clearly that AWA evaluates supplied observations and does not execute or sandbox arbitrary agents.
- Disclose that synthetic examples and simulated benchmarks are not evidence of broad production reliability.
- Treat SHA-256 digests as change-detection fingerprints, not digital signatures or provenance proof.
- List known limitations, compatibility changes, and any remaining test gaps.
- Do not claim certification, comprehensive safety assurance, or production readiness from passing tests alone.
