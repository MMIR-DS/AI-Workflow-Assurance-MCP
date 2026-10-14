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

Review the JSON outputs rather than relying only on process exit codes. In particular, inspect the release decision, configured thresholds, warnings, and the assurance-scope note. CI also runs the documented CLI commands from the built wheel and checks key JSON response contracts; keep the manual review as a separate release-acceptance step.

## 4. Verify the MCP boundary

CI launches the MCP server executable from a wheel installed in a clean virtual environment. The child process receives a temporary startup hook on `PYTHONPATH`, not the checkout's source tree, so package imports still resolve from the installed wheel. The smoke test requires an activation sentinel from that hook before it trusts the counter, preventing a missing hook from looking like zero network attempts. The hook blocks and counts Python socket-level non-loopback IPv4/IPv6 connection attempts; attempts observed through those hooks fail the smoke test. Loopback is allowed because Windows asyncio uses a loopback socket pair for internal event-loop signaling. This is test instrumentation, not an OS-level network sandbox and not a complete defense against native code or direct syscalls. The clean-wheel-origin probe also verifies that the Tau2-specific dispatcher/pre-write/post-write modules are absent from the generic distribution; these simulator integrations remain available from the repository checkout and manual simulator workflow. The stdio smoke test checks the versioned initialize handshake, the exact inventory of eight exposed tools, representative response contracts for all eight tools, and critical evidence-trust and sensitive-write preflight behavior. It uses synthetic local input and makes no model calls.

For manual integration on Windows with VS Code, follow the [MCP client acceptance guide](MCP_CLIENT_ACCEPTANCE_WINDOWS.md). It builds a wheel, installs it in a separate virtual environment, configures VS Code to launch the installed console entry point, and records tool-discovery and invocation results. Do not mark manual VS Code GUI acceptance complete until the record has been filled from an actual client run.

**Fallback when no Windows desktop is available:** the `Windows installed-wheel MCP smoke` CI job builds and installs the wheel on a GitHub-hosted Windows runner and uses an MCP SDK client over stdio to verify the initialization handshake, discovery of the exact eight tools, and representative invocation contracts for all eight tools. Its JSON report is uploaded as the `windows-installed-wheel-mcp-smoke` artifact. This provides automated Windows packaging and protocol evidence without needing the owner's computer. Record the workflow URL, candidate commit SHA, and artifact result; mark the manual VS Code GUI check as **NOT RUN**, not PASS. The fallback does not test VS Code's graphical client, its workspace configuration loader, or its model/tool orchestration. An alpha release may proceed on this documented fallback only if all other release checks pass and the release notes explicitly say that manual VS Code GUI acceptance was not performed. Never claim that VS Code itself was tested. If a release promises verified VS Code integration, actual GUI acceptance remains required.

For other MCP clients, launch the installed server using its `ai-workflow-assurance-mcp` entry point and verify that client's actual initialization, tool discovery, and invocation behavior. The automated smoke is protocol-level coverage; it does not prove compatibility with every MCP client or deployment configuration. Do not expose the process as a network service without a separate threat model and deployment review.

## 5. Verify the built artifact and CI

The CI workflow builds a wheel and installs it outside the source tree. Before calling the MCP protocol smoke, it launches a probe from a temporary working directory with `PYTHONPATH` removed and asserts that the imported module resolves beneath that virtual environment's installed-package directory, that both console entry points belong to the environment, and that distribution/package versions agree. CI also checks the installed CLI entry point, runs the test suite and lint, validates the deterministic assurance harness report (including its `overall_passed` flag), runs the harness unit tests, smoke-tests the installed-wheel MCP stdio boundary, verifies documented CLI JSON contracts, checks release-gate exit behavior, and executes the source mutation smoke test on Python 3.10–3.13.

Before tagging, confirm that the latest workflow run for the exact candidate commit is green on every supported CI matrix version. Do not infer success from an earlier commit's run or from a partial set of checks. Passing CI is evidence about the tested commit and test cases only; it does not replace manual MCP-client integration or review of the example CLI outputs.

## 6. Review scope and release notes

- State clearly that AWA evaluates supplied observations and does not execute or sandbox arbitrary agents.
- Disclose that synthetic examples and simulated benchmarks are not evidence of broad production reliability.
- Treat SHA-256 digests as change-detection fingerprints, not digital signatures or provenance proof.
- List known limitations, compatibility changes, and any remaining test gaps.
- Do not claim certification, comprehensive safety assurance, or production readiness from passing tests alone.
