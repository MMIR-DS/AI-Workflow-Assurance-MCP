# Generic wheel and Tau2 source boundary

## Generic distribution

The `ai-workflow-assurance-mcp` wheel is the general-purpose evaluation package. Its public CLI and MCP server evaluate supplied workflow observations and expose the documented reference preflight. The wheel intentionally excludes these simulator-only implementation modules:

- `ai_workflow_assurance_mcp.tau2_constants`
- `ai_workflow_assurance_mcp.tau2_prewrite`
- `ai_workflow_assurance_mcp.tau2_postwrite`

These modules are used by the repository's pinned Tau2 simulator integration, patch installer, post-write audit and associated tests. They are not required by the generic wheel's entry points.

## Source-checkout integration

The Tau2 showcase remains a repository-checkout integration, not a general production control plane. The manual workflow checks out the pinned upstream simulator, adds this repository's `src` directory to `PYTHONPATH`, and runs the guard installer and deterministic smoke tests against the checkout sources. The integration is not automatically installed into the upstream Tau2 package or a user's installed AWA wheel.

This change creates a wheel boundary; it does **not** create a separately installable `awa-tau2` distribution, and it does not imply that all Tau2-related manifest inspection has been removed from the generic package. That broader extraction would require an explicit extension/distribution design and its own compatibility plan.

## Verification

The clean-wheel-origin check imports AWA from the installed environment and fails if any of the three simulator-only modules are importable. CI runs the check on Linux and Windows. Source-tree tests continue to exercise these implementation modules directly.

To inspect a locally built wheel:

```bash
python -m pip wheel . --no-deps --wheel-dir dist
python - <<'PY'
from zipfile import ZipFile
from pathlib import Path

wheel = next(Path("dist").glob("*.whl"))
with ZipFile(wheel) as archive:
    names = set(archive.namelist())
for module in ("tau2_constants.py", "tau2_prewrite.py", "tau2_postwrite.py"):
    assert not any(name.endswith("/" + module) for name in names), module
print("Generic wheel excludes Tau2 simulator implementation modules.")
PY
```
