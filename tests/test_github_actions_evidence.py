from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.error import HTTPError

import pytest

from ai_workflow_assurance_mcp.github_actions_evidence import (
    GitHubActionsEvidenceError,
    GitHubActionsRunSource,
)

NOW = datetime(2026, 10, 11, 7, 0, tzinfo=timezone.utc)
SHA = "a" * 40


def payload(**overrides):
    result = {
        "id": 12345,
        "name": "CI",
        "workflow_id": 77,
        "repository": {"full_name": "MMIR-DS/AI-Workflow-Assurance-MCP"},
        "head_sha": SHA,
        "status": "completed",
        "conclusion": "success",
        "run_attempt": 1,
        "created_at": (NOW - timedelta(minutes=10)).isoformat(),
        "updated_at": (NOW - timedelta(minutes=2)).isoformat(),
        "html_url": "https://github.com/MMIR-DS/AI-Workflow-Assurance-MCP/actions/runs/12345",
        "private_trace": "must not propagate",
    }
    result.update(overrides)
    return result


class Response:
    def __init__(self, body):
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit=-1):
        return self.body[:limit]


def source(**kwargs):
    return GitHubActionsRunSource(
        "MMIR-DS/AI-Workflow-Assurance-MCP",
        12345,
        SHA,
        token="test-token",
        now=NOW,
        **kwargs,
    )


def test_success_returns_allowlisted_non_release_envelope():
    with patch(
        "ai_workflow_assurance_mcp.github_actions_evidence.urlopen",
        return_value=Response(payload()),
    ) as open_url:
        envelope = source().read_evidence()

    assert envelope.source_name == "github-actions-workflow-run"
    assert envelope.source_version == SHA
    assert envelope.assurance_scope == "github_actions_run_metadata_only"
    assert envelope.source_authenticity == "not_verified"
    assert envelope.release_eligible is False
    assert envelope.collected_at == NOW
    assert envelope.evidence["conclusion"] == "success"
    assert "private_trace" not in envelope.evidence
    request = open_url.call_args.args[0]
    assert request.get_method() == "GET"
    assert request.get_header("Authorization") == "Bearer test-token"


def test_missing_token_fails_closed():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(GitHubActionsEvidenceError, match="Set GH_TOKEN"):
            GitHubActionsRunSource(
                "owner/repo", 12345, SHA, now=NOW
            ).read_evidence()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"id": 99}, "different workflow run ID"),
        ({"repository": {"full_name": "other/repo"}}, "repository does not match"),
        ({"head_sha": "b" * 40}, "head SHA does not match"),
        ({"status": "in_progress", "conclusion": None}, "completed successfully"),
        ({"status": "completed", "conclusion": "failure"}, "completed successfully"),
        ({"updated_at": (NOW - timedelta(hours=2)).isoformat()}, "stale"),
        ({"updated_at": (NOW + timedelta(hours=1)).isoformat()}, "future"),
        ({"workflow_id": True}, "workflow_id"),
        ({"run_attempt": 0}, "run attempt"),
    ],
)
def test_invalid_run_metadata_fails_closed(overrides, message):
    with patch(
        "ai_workflow_assurance_mcp.github_actions_evidence.urlopen",
        return_value=Response(payload(**overrides)),
    ):
        with pytest.raises(GitHubActionsEvidenceError, match=message):
            source().read_evidence()


def test_http_errors_are_sanitized():
    error = HTTPError("https://api.github.com", 403, "forbidden", {}, None)
    with patch(
        "ai_workflow_assurance_mcp.github_actions_evidence.urlopen",
        side_effect=error,
    ):
        with pytest.raises(GitHubActionsEvidenceError, match="read permissions") as caught:
            source().read_evidence()
    assert "test-token" not in str(caught.value)


def test_constructor_rejects_invalid_repository_run_and_sha():
    with pytest.raises(GitHubActionsEvidenceError, match="owner/name"):
        GitHubActionsRunSource("../owner/repo", 12345, SHA, token="x", now=NOW)
    with pytest.raises(GitHubActionsEvidenceError, match="positive integer"):
        GitHubActionsRunSource("owner/repo", True, SHA, token="x", now=NOW)
    with pytest.raises(GitHubActionsEvidenceError, match="40-character"):
        GitHubActionsRunSource("owner/repo", 12345, "ABC", token="x", now=NOW)
