# Generic wheel and Tau2 source boundary

## Generic distribution

The `ai-workflow-assurance-mcp` wheel is the general-purpose evaluation package. Its public CLI and MCP server evaluate supplied workflow observations and expose the documented reference preflight. The wheel intentionally excludes all modules matching `ai_workflow_assurance_mcp.tau2_*.py`, including:

- `ai_workflow_assurance_mcp.tau2_constants`
- `ai_workflow_assurance_mcp.tau2_prewrite`
- `ai_workflow_assurance_mcp.tau2_postwrite`
- `ai_workflow_assurance_mcp.tau2_prewrite_common` and the operation-specific `tau2_prewrite_*` modules
- `ai_workflow_assurance_mcp.tau2_postwrite_catalog`, `tau2_postwrite_trace`, `tau2_postwrite_benchmark`, and `tau2_postwrite_pending_item`

These modules are used by the repository's pinned Tau2 simulator integration, patch installer, post-write audit and associated tests. They are not required by the generic wheel's entry points.

## Source-checkout integration

The Tau2 showcase remains a repository-checkout integration, not a general production control plane. The manual workflow checks out the pinned upstream simulator, adds this repository's `src` directory to `PYTHONPATH`, and runs the guard installer and deterministic smoke tests against the checkout sources. The integration is not automatically installed into the upstream Tau2 package or a user's installed AWA wheel.

This change creates a wheel boundary; it does **not** create a separately installable `awa-tau2` distribution, and it does not imply that all Tau2-related manifest inspection has been removed from the generic package. That broader extraction would require an explicit extension/distribution design and its own compatibility plan.

## Verification

The clean-wheel-origin check imports AWA from the installed environment and fails if any package submodule whose name starts with `tau2_` is importable. This automatically covers the split policy modules as the source layout evolves. CI runs the check on Linux and Windows. Source-tree tests continue to exercise these implementation modules directly.

To inspect a locally built wheel:

```bash
python -m pip wheel . --no-deps --wheel-dir dist
python - <<'PY'
from zipfile import ZipFile
from pathlib import Path

wheel = next(Path("dist").glob("*.whl"))
with ZipFile(wheel) as archive:
    names = set(archive.namelist())
for name in names:
    if "/ai_workflow_assurance_mcp/tau2_" in name and name.endswith(".py"):
        raise AssertionError(f"Tau2-only module leaked into generic wheel: {name}")
print("Generic wheel excludes Tau2 simulator implementation modules.")
PY
```
