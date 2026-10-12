# Windows MCP client acceptance — VS Code

This procedure verifies AWA from a real VS Code MCP client using the freshly built wheel, not an editable install. It complements CI; it does not claim that every MCP client has been tested or that AWA is production-certified.

Official references:
- [VS Code: Add and manage MCP servers](https://code.visualstudio.com/docs/agent-customization/mcp-servers)
- [VS Code: MCP configuration reference](https://code.visualstudio.com/docs/agents/reference/mcp-configuration)

## 1. Build and install the candidate wheel

Run these commands in **PowerShell** from the repository root. Python 3.12 is used here because it is in the project's supported CI matrix; another supported version can be selected by changing `-3.12`.

```powershell
$ErrorActionPreference = "Stop"

if (Test-Path .\dist) { Remove-Item .\dist -Recurse -Force }
if (Test-Path .\.venv-wheel) { Remove-Item .\.venv-wheel -Recurse -Force }

py -3.12 -m pip wheel . --no-deps --wheel-dir dist
py -3.12 -m venv .venv-wheel

$wheel = Get-ChildItem .\dist\ai_workflow_assurance_mcp-*.whl | Select-Object -First 1
if (-not $wheel) { throw "Built wheel not found." }

.\.venv-wheel\Scripts\python.exe -m pip install $wheel.FullName
```

The wheel installation step installs the package's runtime dependencies. Network access is needed during this setup if required packages are not already cached; the smoke test itself should make no model/API calls.

Run the same import-origin check used by CI:

```powershell
.\.venv-wheel\Scripts\python.exe scripts\check_installed_wheel_origin.py `
  --python .\.venv-wheel\Scripts\python.exe `
  --cli .\.venv-wheel\Scripts\ai-workflow-assurance.exe `
  --server .\.venv-wheel\Scripts\ai-workflow-assurance-mcp.exe
```

Expected report fields include `"status": "passed"`, `"import_from_installed_package": true`, and matching `metadata_version` / `package_version`. Stop here if the check fails; do not configure the client to use a source checkout or editable installation as a workaround.

Record the candidate commit and wheel hash for the acceptance record:

```powershell
git rev-parse HEAD
Get-FileHash $wheel.FullName -Algorithm SHA256
```

## 2. Configure VS Code to launch that wheel installation

Create `.vscode/mcp.json` in the repository workspace (create the `.vscode` folder if needed). Do not commit this file unless the project team intentionally chooses to make it a shared workspace configuration.

```json
{
  "servers": {
    "ai-workflow-assurance": {
      "type": "stdio",
      "command": "${workspaceFolder}/.venv-wheel/Scripts/ai-workflow-assurance-mcp.exe",
      "args": []
    }
  }
}
```

This uses VS Code's current workspace configuration shape: the top-level `servers` map and `type: "stdio"`. It starts the installed console entry point. It does not expose an HTTP/network service.

Open the saved configuration in VS Code. Use the available **Start** action or the Command Palette command **MCP: List Servers**, select `ai-workflow-assurance`, then start it. Approve the workspace/server trust prompt only after reviewing the local command and path.

## 3. Verify the actual client interaction

In VS Code, confirm all of the following:

1. The server is shown as running, with no startup or JSON-RPC/stdio error in the MCP server output/log.
2. The tool picker/discovery view lists exactly these eight tools:
   - `validate_workflow_spec`
   - `run_eval_suite`
   - `compare_eval_runs`
   - `explain_failures`
   - `generate_release_report`
   - `inspect_tau2_evidence_manifest`
   - `inspect_github_actions_run`
   - `preflight_sensitive_write`
3. Invoke `validate_workflow_spec` directly from the client's available tool UI, using this argument. Keep the nested JSON as a **string** in `workflow_spec_json`:

```json
{
  "workflow_spec_json": "{\"id\":\"vscode-client-smoke\",\"name\":\"VS Code MCP smoke\",\"version\":\"1.0.0\",\"criteria\":[{\"id\":\"decision_matches\",\"operator\":\"equals\",\"actual_path\":\"decision\",\"expected_path\":\"decision\",\"severity\":\"critical\"}],\"thresholds\":{\"min_pass_rate\":1.0,\"max_critical_failures\":0}}"
}
```

Expected result: `valid: true`, one criterion, and no validation errors.

4. Invoke `run_eval_suite` from the client with:
   - `workflow_spec_json`: the exact same specification JSON string used above.
   - `cases_json`: `[{"case_id":"vscode-control","expected":{"decision":"approve"},"actual":{"decision":"approve"},"human_review_observed":false,"cost_usd":0.01,"latency_ms":100}]`

Expected result: the summary shows a 100% pass rate, and `case_results_omitted` is `true` by default.

5. Stop and restart the server once, then repeat tool discovery. Confirm that the tools reappear and the calls still succeed.

The manual client may use its own model to orchestrate a chat request. The AWA server-side smoke fixture makes no model calls; do not confuse those two scopes. Do not supply real customer data, credentials, or real business-write requests to this test.

## 4. Acceptance record

Copy and complete this record in the release issue or candidate notes. Mark a step as failed rather than inferring success from CI.

- Candidate commit SHA:
- Wheel filename and SHA-256:
- Windows version:
- VS Code version:
- Python version:
- MCP server status after start/restart:
- Number of tools discovered (expected 8):
- `validate_workflow_spec` result (expected valid):
- `run_eval_suite` pass rate and summary-only result (expected 100%, `case_results_omitted=true`):
- MCP server log errors:
- Final result: PASS / FAIL / NOT RUN
- Operator and date:

A PASS only confirms this version of VS Code, this Windows environment, these two tool invocations, and this wheel. It is not a general compatibility certification, security boundary, or production-readiness claim.
