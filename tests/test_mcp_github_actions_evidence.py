from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from ai_workflow_assurance_mcp import server
from ai_workflow_assurance_mcp.github_actions_evidence import GitHubActionsEvidenceError


def _envelope():
    return SimpleNamespace(
        source_name="github-actions-workflow-run",
        source_version="a" * 40,
        assurance_scope="github_actions_run_metadata_only",
        source_authenticity="not_verified",
        release_eligible=False,
        collected_at=datetime(2026, 10, 11, tzinfo=timezone.utc),
        evidence={"repository": "owner/repo", "run_id": 123, "conclusion": "success"},
    )


def test_mcp_tool_returns_explicit_non_release_boundary(monkeypatch):
    class FakeSource:
        def __init__(self, **kwargs):
            assert kwargs == {
                "repository": "owner/repo",
                "run_id": 123,
                "expected_head_sha": "a" * 40,
                "max_age_seconds": 3600,
            }

        def read_evidence(self):
            return _envelope()

    monkeypatch.setattr(server, "GitHubActionsRunSource", FakeSource)
    result = server.inspect_github_actions_run("owner/repo", 123, "a" * 40)

    assert result["source_name"] == "github-actions-workflow-run"
    assert result["source_authenticity"] == "not_verified"
    assert result["release_eligible"] is False
    assert result["evidence"]["conclusion"] == "success"


def test_mcp_tool_maps_missing_token_to_safe_tool_error(monkeypatch):
    class FakeSource:
        def __init__(self, **kwargs):
            pass

        def read_evidence(self):
            raise GitHubActionsEvidenceError("Set GH_TOKEN or GITHUB_TOKEN with read-only Actions access.")

    monkeypatch.setattr(server, "GitHubActionsRunSource", FakeSource)
    with pytest.raises(ToolError, match="Set GH_TOKEN"):
        server.inspect_github_actions_run("owner/repo", 123, "a" * 40)


def test_mcp_tool_rejects_invalid_run_inputs():
    with pytest.raises(ToolError, match="positive integer"):
        server.inspect_github_actions_run("owner/repo", True, "a" * 40)
