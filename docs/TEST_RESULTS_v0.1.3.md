# Local verification — v0.1.3

Date: 2026-10-10

Executed in this environment (Linux x86_64):

- Python 3.10.22, mcp 2.3.0, pytest 9.1.1, ruff 0.17.0
- `python -m pytest -ra` — 38 passed
- `ruff check src tests scripts` — clean
- `PYTHONPATH=src python scripts/demo.py` — passed (`IMPROVED_WITH_TRADEOFF`)
- CLI `validate-spec`, `evaluate`, `compare`, `explain`, `release` — exit 0
- MCP stdio initialize, `list_tools`, and calls to all five tools — passed; server version `0.1.3`
- Python 3.11.2: `unittest` on `tests.test_core` and `tests.test_cli` — 35 passed
- Python 3.12 and 3.13 were not installed here and were not executed

The input ZIP SHA-256 was `8e8c3f31461857557bf4ea794e0266d00bd36c85056f8ca6e86b638a0b49567a`.
