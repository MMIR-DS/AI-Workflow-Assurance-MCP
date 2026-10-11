# GitHub Actions read-only evidence source

The `GitHubActionsRunSource` adapter reads metadata for one explicitly selected GitHub Actions run using the GitHub REST API. It uses Python's standard library and performs one `GET`; it does not download workflow logs or artifacts, start/rerun workflows, or mutate repository state.

## Minimal use

```python
from ai_workflow_assurance_mcp.github_actions_evidence import GitHubActionsRunSource

source = GitHubActionsRunSource(
    repository="owner/repository",
    run_id=123456789,
    expected_head_sha="0123456789abcdef0123456789abcdef01234567",
    max_age_seconds=3600,
)
envelope = source.read_evidence()
```

Set `GH_TOKEN` (preferred) or `GITHUB_TOKEN` in the process environment. Use a fine-grained token restricted to the intended repository with read-only Actions and repository metadata permissions. Never put a token in source code, command-line arguments, evidence JSON, logs, or issue/PR text. The adapter does not print or return the token.

## Fail-closed checks

The adapter rejects missing credentials, invalid repository/run/SHA inputs, inaccessible runs, HTTP errors, malformed or oversized responses, a different run ID or repository, a mismatched head commit, non-completed or non-successful runs, invalid timestamps, stale evidence, and future-dated evidence. Default freshness is one hour and the allowed configured range is one second to seven days. Network timeout is bounded.

Only an allowlisted set of run metadata is returned. Logs, artifacts, actor details, event payloads, and arbitrary API fields are not propagated.

## Trust boundary

This adapter returns `source_authenticity=not_verified` and `release_eligible=false` unconditionally. HTTPS plus a token authenticates API access, but this adapter does not independently verify workflow definition integrity, trusted workflow identity, branch protection, artifact attestations, or the business system's underlying state. A successful Actions run only says that GitHub reports that selected run succeeded. It is not proof that a production workflow executed correctly and must not be treated as a release authorization.

The adapter is a read-only metadata source, not a production commerce connector. Keep the existing tau2 manifest labelled simulator-only. Add a separate, explicitly reviewed trust policy before using any external evidence in a real release gate.
