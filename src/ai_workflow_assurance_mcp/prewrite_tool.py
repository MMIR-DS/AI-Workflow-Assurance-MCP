"""MCP registration for the reference pre-write authorization preflight."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver.exceptions import ToolError

from ai_workflow_assurance_mcp.core import AssuranceInputError, parse_json_text
from ai_workflow_assurance_mcp.prewrite_guard import evaluate_prewrite


def register_prewrite_tool(mcp: Any) -> None:
    """Register a read-only preflight tool on the configured MCP server."""

    @mcp.tool()
    def preflight_delivered_item_exchange(action_json: str, evidence_json: str) -> dict[str, Any]:
        """Check the supplied evidence for a delivered-order item exchange only.

        This reference tool evaluates caller-supplied JSON; it does not authenticate that evidence,
        independently verify customer identity, or execute/intercept the write. The host application
        must block the actual write unless the result is GO and must obtain evidence from trusted
        sources immediately before mutation.
        """
        try:
            action = parse_json_text(action_json, "action_json")
            evidence = parse_json_text(evidence_json, "evidence_json")
            return evaluate_prewrite(action, evidence)
        except AssuranceInputError as exc:
            raise ToolError(str(exc)) from exc
