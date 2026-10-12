"""MCP registration for the reference pre-write authorization preflight."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

from ai_workflow_assurance_mcp.core import AssuranceInputError, parse_json_text
from ai_workflow_assurance_mcp.prewrite_guard import evaluate_prewrite


def register_prewrite_tool(mcp: Any) -> None:
    """Register a read-only preflight tool on the configured MCP server."""

    @mcp.tool()
    def preflight_sensitive_write(action_json: str, evidence_json: str) -> dict[str, Any]:
        """Exchange-specific preflight for an item replacement on a delivered retail order.

        This is not a generic policy for arbitrary sensitive writes (for example, cancellation,
        address changes, or payment-method changes). A NO_GO must be enforced by the caller.
        This tool does not execute, authorize, or intercept writes.
        """
        try:
            action = parse_json_text(action_json, "action_json")
            evidence = parse_json_text(evidence_json, "evidence_json")
            return evaluate_prewrite(action, evidence)
        except AssuranceInputError as exc:
            raise ToolError(str(exc)) from exc
