# AI Workflow Assurance MCP — bootstrap status

This repository is being prepared for a reproducible **v0.1.2** baseline.

## Current repository state

- The initial repository commit and this README exist.
- `.github/workflows/tau2-retail-smoke.yml` has been added as a **manual-only** OpenRouter-backed smoke run against the public `sierra-research/tau2-bench` retail task 0. Its display name explicitly marks it as standalone and not yet AWA-integrated.
- **The AWA v0.1.2 source package and its tests have not yet been committed to this repository.** The smoke workflow only runs tau2-bench; it does not call AWA or prove AWA detects a workflow violation.
- The complete starter bundle is available in the related ChatGPT conversation as `AI_Workflow_Assurance_v0.1.2_GitHub_Starter.zip`. It contains the v0.1.2 source archive, public simulated retail workflow pack, CI workflow, documentation, and a PowerShell helper for a safe Git push.

## What is needed to complete the baseline

Transfer the starter bundle's source and `.github/workflows/ci.yml` into the repository. Once the source is present, CI should install the package and run pytest and Ruff across supported Python versions. Only after that should we adapt tau2 traces and final state into AWA's normalized observation contract.

## OpenRouter and cost controls

Create a repository secret named `OPENROUTER_API_KEY` under **Settings → Secrets and variables → Actions**. The benchmark workflow is manual-only and defaults to one retail task, one trial, one concurrent run, and a low step cap. Model calls may incur charges, so verify your OpenRouter spending limit before launching it.

Go to **Actions → tau2 retail smoke benchmark (AWA v0.1.2 baseline) → Run workflow** to run the model-backed smoke test. It produces a downloadable artifact containing logs and simulation outputs. Do not treat a model-run result as evidence that AWA passed or failed until the AWA adapter and assurance report are integrated and reviewed.

## Pinned source checksums

- Full v0.1.2 source release ZIP: `8e8c3f31461857557bf4ea794e0266d00bd36c85056f8ca6e86b638a0b49567a`
- Public retail workflow pack ZIP: `34e08942fba2da825b42b5a91394425a1fc5dbd348093bf40374478677de4af8`
