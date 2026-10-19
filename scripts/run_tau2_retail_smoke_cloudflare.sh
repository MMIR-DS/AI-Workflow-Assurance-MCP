#!/usr/bin/env bash
set -euo pipefail

: "${CLOUDFLARE_API_KEY:?CLOUDFLARE_API_KEY is required}"
: "${CLOUDFLARE_ACCOUNT_ID:?CLOUDFLARE_ACCOUNT_ID is required}"
: "${OPENAI_API_KEY:?OPENAI_API_KEY alias is required}"
: "${OPENAI_BASE_URL:?OPENAI_BASE_URL is required}"
: "${OPENAI_API_BASE:?OPENAI_API_BASE compatibility alias is required}"
: "${MODEL:?MODEL is required}"
: "${MAX_STEPS:?MAX_STEPS is required}"

case "$MAX_STEPS" in
  20|40|60) ;;
  *)
    printf 'MAX_STEPS must be one of 20, 40, or 60 (got: %s)\n' "$MAX_STEPS" >&2
    exit 2
    ;;
esac

# One task/trial, deterministic sampling settings, no hidden Tau2 retries.
# The OpenAI-compatible LiteLLM route uses Cloudflare's /ai/v1 endpoint and
# avoids LiteLLM's currently incompatible native Cloudflare response parser.
PYTHONPATH="../src${PYTHONPATH:+:$PYTHONPATH}" uv run tau2 run \
  --domain retail \
  --agent llm_agent \
  --agent-llm "$MODEL" \
  --agent-llm-args '{"max_tokens": 2048, "temperature": 0.0}' \
  --user-llm "$MODEL" \
  --user-llm-args '{"max_tokens": 2048, "temperature": 0.0}' \
  --num-trials 1 \
  --task-ids 0 \
  --seed 300 \
  --max-concurrency 1 \
  --max-steps "$MAX_STEPS" \
  --max-errors 12 \
  --max-retries 0 \
  --timeout 480 \
  --save-to tau2-standalone-retail-task0 \
  2>&1 | tee ../tau2-benchmark.log
