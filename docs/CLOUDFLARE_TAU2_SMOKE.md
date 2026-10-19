# Cloudflare Workers AI Tau2 smoke

This is a separate, manual-only model-backed experiment. It does not replace the existing OpenRouter or Gemini workflows and does not run as part of deterministic CI.

## Configure GitHub Actions secrets

In the repository, open **Settings → Secrets and variables → Actions → New repository secret** and add:

- `CLOUDFLARE_API_KEY`: a Cloudflare Workers AI API token.
- `CLOUDFLARE_ACCOUNT_ID`: the account ID for the account where Workers AI is enabled.

Create the token from the Cloudflare dashboard's Workers AI → Use REST API flow. Grant the required Workers AI API permissions. Never commit the token or print it in logs.

Official setup: https://developers.cloudflare.com/workers-ai/get-started/rest-api/

## Endpoint and model

The workflow pins `openai/@cf/zai-org/glm-4.7-flash` in LiteLLM and points the OpenAI-compatible client at:

`https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/v1`

This calls Cloudflare's OpenAI-compatible Chat Completions endpoint and deliberately avoids LiteLLM's native `cloudflare/` response transformer. That transformer has a documented failure mode where it assumes `result.response` even when the response uses the OpenAI-style `result.choices[0].message.content` shape. The GitHub Actions workflow aliases the existing `CLOUDFLARE_API_KEY` secret to `OPENAI_API_KEY`; no extra credential or secret is needed.

References:
- Cloudflare OpenAI-compatible endpoint: https://developers.cloudflare.com/workers-ai/configuration/open-ai-compatibility/
- LiteLLM Cloudflare adapter issue: https://github.com/BerriAI/litellm/issues/25999
- Model: https://developers.cloudflare.com/workers-ai/models/glm-4.7-flash/
- Pricing: https://developers.cloudflare.com/workers-ai/platform/pricing/
- Function calling: https://developers.cloudflare.com/workers-ai/features/function-calling/

## Cost and bounded execution

The Workers Free plan has a daily 10,000-Neuron allocation, but usage is not unlimited: the allocation resets at 00:00 UTC, requests can fail at the cap, and usage beyond it requires a paid plan. Verify the current model-specific price and account eligibility before running; do not assume every model is free.

Open **Actions → tau2 retail + AWA assurance prototype (Cloudflare Workers AI) → Run workflow**. Start with `max_steps=20`. The workflow is limited to task 0, one trial, one seed, concurrency 1, and no Tau2 retries. It applies the reviewed prompt patch and installs the AWA pre-write guard before any model call.

The first execution (run 39242156595) reached the model stage but failed inside LiteLLM's native Cloudflare response transformer with `KeyError: 'response'`; zero benchmark tasks were evaluated. The OpenAI-compatible endpoint workaround was then validated by a second live run (run 39253573075): model calls and Tau2 tool use worked, but AWA blocked the exchange before mutation because the initial customer-facing summary omitted the exact old/new item IDs and exact `payment_method_id`. The agent correctly did not retry the denied write; the simulator then ended the conversation before a new confirmation, so the task remained incomplete and the release decision was `NO_GO`.

Cloudflare returned `usage.neurons` in 15 recorded responses in that run, totaling approximately 548.0296 Neurons. LiteLLM did not map the model for USD pricing, so Tau2's displayed `$0.0000` is not evidence of zero spend. The adapter now preserves observed Neuron totals separately and intentionally leaves USD cost unknown unless a reliable cost is available.

A successful workflow is not automatically a GO decision or a production reliability claim. Inspect the uploaded `tau2-awa-retail-assurance-cloudflare` artifact and review the pre-write behavior, tool trace, task completion, and AWA decision. Use only the synthetic public benchmark data; never send real customer or confidential data.


## Empty simulated-user responses

The pinned Tau2 user simulator can receive an empty model response with no tool calls. Tau2 then rejects the resulting `UserMessage` before a task trace is evaluable. The smoke workflow installs `AWA_USER_EMPTY_RESPONSE_RETRY_V1`, which retries this specific empty response once. It never invents user text or treats an empty response as a stop/confirmation. If the retry is also empty, the run remains an infrastructure error and the AWA release decision stays closed (`HOLD`).

This is a bounded resilience measure, not evidence that the provider/model is reliable. A run only counts as a task evaluation when Tau2 records a complete trace and the AWA checks are evaluable.
