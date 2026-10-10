# AI Workflow Assurance MCP — v0.1.2 baseline

The first commit has initialized this repository. The full v0.1.2 source tree and GitHub Actions workflows are prepared in the starter bundle linked in the ChatGPT conversation.

## Next step: add the source and workflows

The connected GitHub integration was able to create this initial commit, but the bulk source upload has not been completed here. Download and extract `AI_Workflow_Assurance_v0.1.2_GitHub_Starter.zip` from the conversation, open PowerShell in the extracted folder, and run:

```powershell
.\PUSH_TO_GITHUB.ps1
```

The script clones this repository, copies the starter source into it, commits, and pushes to `main`. Sign in through Git Credential Manager if prompted. It does not force-push or store GitHub credentials. If the push fails, stop and review the error rather than pasting a token into chat.

## Required secret

In **Settings → Secrets and variables → Actions**, confirm that the repository secret is named exactly `OPENROUTER_API_KEY`. The workflow will not print its value.

## Planned execution

- CI will run the v0.1.2 tests and Ruff lint on Python 3.10–3.13 for pushes and pull requests.
- The model-backed evaluation is manual-only under **Actions → tau2 retail smoke benchmark (AWA v0.1.2 baseline) → Run workflow**, to avoid surprise API charges.
- Default run: one retail task (`0`), one trial, one concurrent run, max 80 steps, and OpenRouter model `openrouter/google/gemini-3.8-flash`.
- Logs and the benchmark simulation output will be preserved as a workflow artifact.

The benchmark uses a simulated public retail environment, not real customer production data. The AWA test suite and tau2 run remain separate until a reviewed adapter converts the raw trace and final state into AWA's normalized observation contract; do not claim AWA caught a defect/regression until that adapter and evidence case are reviewed.

