"""Read-only GitHub Actions run metadata adapter.

This adapter reads one explicitly selected workflow run through GitHub's REST API.
It never downloads logs or artifacts and never grants release eligibility.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ai_workflow_assurance_mcp.evidence_sources import EvidenceEnvelope

_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_ALLOWED_REPOSITORIES_ENV = "AWA_GITHUB_ALLOWED_REPOSITORIES"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_API_ROOT = "https://api.github.com"
_MAX_RESPONSE_BYTES = 256 * 1024


def _valid_repository_name(value: str) -> bool:
    if not isinstance(value, str) or not _REPO_RE.fullmatch(value):
        return False
    owner, name = value.split("/", maxsplit=1)
    return owner not in {".", ".."} and name not in {".", ".."}


def _allowed_repositories_from_env() -> set[str]:
    raw = os.getenv(_ALLOWED_REPOSITORIES_ENV, "")
    if not raw.strip():
        raise GitHubActionsEvidenceError(
            f"Set {_ALLOWED_REPOSITORIES_ENV} to a comma-separated repository allowlist."
        )
    entries = [entry.strip() for entry in raw.split(",") if entry.strip()]
    if not entries or any(not _valid_repository_name(entry) for entry in entries):
        raise GitHubActionsEvidenceError(
            f"{_ALLOWED_REPOSITORIES_ENV} contains an invalid owner/name entry."
        )
    return {entry.casefold() for entry in entries}


class _NoRedirectHandler(HTTPRedirectHandler):
    """Refuse redirects so an Authorization header can never be replayed elsewhere."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _open_without_redirects(request: Request, *, timeout: float):
    return build_opener(_NoRedirectHandler).open(request, timeout=timeout)


class GitHubActionsEvidenceError(ValueError):
    """Safe, user-facing error for unavailable or untrusted workflow evidence."""


class GitHubActionsRunSource:
    """Read metadata for one workflow run; treat all results as non-release evidence.

    A fine-grained token with read-only Actions and repository metadata access is
    sufficient. The token is read from GH_TOKEN or GITHUB_TOKEN and is never returned.
    """

    def __init__(
        self,
        repository: str,
        run_id: int,
        expected_head_sha: str,
        *,
        max_age_seconds: int = 3600,
        token: str | None = None,
        now: datetime | None = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        if not _valid_repository_name(repository):
            raise GitHubActionsEvidenceError("repository must be a valid owner/name pair without dot components.")
        if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0:
            raise GitHubActionsEvidenceError("run_id must be a positive integer.")
        if not isinstance(expected_head_sha, str) or not _SHA_RE.fullmatch(expected_head_sha):
            raise GitHubActionsEvidenceError("expected_head_sha must be a 40-character lowercase SHA.")
        if isinstance(max_age_seconds, bool) or not isinstance(max_age_seconds, int) or not 1 <= max_age_seconds <= 604800:
            raise GitHubActionsEvidenceError("max_age_seconds must be between 1 and 604800.")
        if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool) or not 0 < timeout_seconds <= 30:
            raise GitHubActionsEvidenceError("timeout_seconds must be greater than 0 and at most 30.")
        self.repository = repository
        self.run_id = run_id
        self.expected_head_sha = expected_head_sha
        self.max_age_seconds = max_age_seconds
        self.token = token if token is not None else (os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN"))
        self.now = now or datetime.now(timezone.utc)
        self.timeout_seconds = float(timeout_seconds)
        if self.now.tzinfo is None or self.now.utcoffset() is None:
            raise GitHubActionsEvidenceError("now must be timezone-aware.")

    @staticmethod
    def _timestamp(value: Any, field: str) -> datetime:
        if not isinstance(value, str):
            raise GitHubActionsEvidenceError(f"GitHub run {field} is missing or invalid.")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise GitHubActionsEvidenceError(f"GitHub run {field} is missing or invalid.") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise GitHubActionsEvidenceError(f"GitHub run {field} must include a timezone.")
        return parsed.astimezone(timezone.utc)

    def read_evidence(self) -> EvidenceEnvelope:
        if not isinstance(self.token, str) or not self.token.strip():
            raise GitHubActionsEvidenceError("Set GH_TOKEN or GITHUB_TOKEN with read-only Actions access.")
        allowed_repositories = _allowed_repositories_from_env()
        if self.repository.casefold() not in allowed_repositories:
            raise GitHubActionsEvidenceError(
                "Requested repository is not included in the configured GitHub evidence allowlist."
            )
        url = f"{_API_ROOT}/repos/{self.repository}/actions/runs/{self.run_id}"
        request = Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "AI-Workflow-Assurance-MCP",
            },
            method="GET",
        )
        try:
            with _open_without_redirects(request, timeout=self.timeout_seconds) as response:
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            # Do not echo response bodies, request headers, or credentials.
            if exc.code == 404:
                message = "GitHub Actions run was not found or is not accessible."
            elif exc.code == 401 or exc.code == 403:
                message = "GitHub rejected the token or its read permissions."
            elif exc.code == 429:
                message = "GitHub API rate limit reached."
            else:
                message = f"GitHub API request failed with HTTP {exc.code}."
            raise GitHubActionsEvidenceError(message) from None
        except (URLError, TimeoutError, OSError):
            raise GitHubActionsEvidenceError("GitHub Actions evidence request failed or timed out.") from None

        if len(raw) > _MAX_RESPONSE_BYTES:
            raise GitHubActionsEvidenceError("GitHub Actions response exceeded the size limit.")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            raise GitHubActionsEvidenceError("GitHub Actions response was not valid JSON.") from None
        if not isinstance(payload, dict):
            raise GitHubActionsEvidenceError("GitHub Actions response must be a JSON object.")

        response_run_id = payload.get("id")
        if (
            isinstance(response_run_id, bool)
            or not isinstance(response_run_id, int)
            or response_run_id != self.run_id
        ):
            raise GitHubActionsEvidenceError("GitHub returned a different workflow run ID.")
        repository = payload.get("repository")
        if (
            not isinstance(repository, dict)
            or not isinstance(repository.get("full_name"), str)
            or repository["full_name"].casefold() != self.repository.casefold()
        ):
            raise GitHubActionsEvidenceError("Workflow run repository does not match the configured repository.")
        head_sha = payload.get("head_sha")
        if not isinstance(head_sha, str) or head_sha != self.expected_head_sha:
            raise GitHubActionsEvidenceError("Workflow run head SHA does not match the expected commit.")
        if payload.get("status") != "completed" or payload.get("conclusion") != "success":
            raise GitHubActionsEvidenceError("Workflow run must be completed successfully.")

        created_at = self._timestamp(payload.get("created_at"), "created_at")
        updated_at = self._timestamp(payload.get("updated_at"), "updated_at")
        if created_at > updated_at:
            raise GitHubActionsEvidenceError(
                "Workflow run created_at must not be later than updated_at."
            )
        now_utc = self.now.astimezone(timezone.utc)
        age = now_utc - updated_at
        if age < timedelta(minutes=-5):
            raise GitHubActionsEvidenceError("Workflow run timestamp is unexpectedly in the future.")
        if age > timedelta(seconds=self.max_age_seconds):
            raise GitHubActionsEvidenceError("Workflow run evidence is stale.")
        workflow_id = payload.get("workflow_id")
        if isinstance(workflow_id, bool) or not isinstance(workflow_id, int) or workflow_id <= 0:
            raise GitHubActionsEvidenceError("GitHub run workflow_id is missing or invalid.")
        run_attempt = payload.get("run_attempt", 1)
        if isinstance(run_attempt, bool) or not isinstance(run_attempt, int) or run_attempt < 1:
            raise GitHubActionsEvidenceError("GitHub run attempt is missing or invalid.")

        safe_evidence = {
            "repository": self.repository,
            "run_id": self.run_id,
            "workflow_id": workflow_id,
            "workflow_name": (
                payload["name"][:256]
                if isinstance(payload.get("name"), str)
                else None
            ),
            "head_sha": head_sha,
            "status": "completed",
            "conclusion": "success",
            "run_attempt": run_attempt,
            "created_at": created_at.isoformat(),
            "updated_at": updated_at.isoformat(),
            "html_url": (
                payload.get("html_url")
                if isinstance(payload.get("html_url"), str)
                and payload["html_url"].startswith("https://github.com/")
                else None
            ),
        }
        return EvidenceEnvelope(
            source_name="github-actions-workflow-run",
            source_version=head_sha,
            assurance_scope="github_actions_run_metadata_only",
            source_authenticity="not_verified",
            release_eligible=False,
            evidence=safe_evidence,
            collected_at=now_utc,
        )
