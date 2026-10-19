# Cloudflare Workers AI Tau2 smoke

This is a separate, manual-only model-backed experiment. It does not replace the existing OpenRouter or Gemini workflows and does not run as part of deterministic CI.

## Configure GitHub Actions secrets

In the repository, open **Settings → Secrets and variables → Actions → New repository secret** and add:

- `CLOUDFLARE_API_KEY`: a Cloudflare Workers AI API token.
- `CLOUDFLARE_ACCOUNT_ID`: the account ID for the account where Workers AI is enabled.

Create the token from the Cloudflare dashboard's Workers AI → Use REST API flow. Grant the documented Workers AI permissions (Workers AI Read and Workers AI Edit). Never commit the token or print it in logs.

Official setup: https://developers.cloudflare.com/workers-ai/get-started/rest-api/

## Model and cost

The workflow pins LiteLLM to `cloudflare/@cf/zai-org/glm-4.7-flash`, a Workers AI model documented as supporting multi-turn function calling. The Workers Free plan has a daily 10,000-Neuron allocation, but usage is not unlimited: the allocation resets at 00:00 UTC, requests can fail at the cap, and usage beyond it requires a paid plan. Verify the current model-specific price and account eligibility before running; do not assume every model is free.

References:
- https://developers.cloudflare.com/workers-ai/models/glm-4.7-flash/
- https://developers.cloudflare.com/workers-ai/platform/pricing/
- https://developers.cloudflare.com/workers-ai/features/function-calling/

## Run safely

Open **Actions → tau2 retail + AWA assurance prototype (Cloudflare Workers AI) → Run workflow**. Start with `max_steps=20`. The workflow is limited to task 0, one trial, one seed, concurrency 1, and no Tau2 retries. It applies the reviewed prompt patch and installs the AWA pre-write guard before any model call.

A successful workflow is not automatically a GO decision or a production reliability claim. Inspect the uploaded `tau2-awa-retail-assurance-cloudflare` artifact and review the pre-write behavior, tool trace, task completion, and AWA decision. Use only the synthetic public benchmark data; never send real customer or confidential data.
