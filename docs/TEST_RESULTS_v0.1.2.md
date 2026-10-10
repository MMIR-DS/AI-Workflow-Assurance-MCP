# Local verification — v0.1.2

Date: 2026-10-10

## Executed in the current environment

- `python -m compileall -q src scripts tests` — passed.
- `python -m pytest -ra` — **37 passed, 1 skipped**. The skipped test is the MCP stdio integration test because the MCP SDK is not installed in this environment.
- Python 3.10 grammar compatibility check via `ast.parse(..., feature_version=(3, 10))` — passed for all 8 Python files.
- `PYTHONPATH=src python scripts/demo.py` — passed; sample trend was `IMPROVED_WITH_TRADEOFF`.

## Not verified here

- Installing the project and development extras from PyPI.
- Runtime MCP handshake, tool discovery and invocation against the installed MCP SDK.
- Ruff lint; Ruff is not installed and the package registry is unreachable from this environment.
- Full CI matrix on Python 3.10–3.13.

The repository includes a stdio integration test for CI. A successful local core/CLI test run is not a substitute for running that integration test in an environment with the declared MCP development dependencies installed.
