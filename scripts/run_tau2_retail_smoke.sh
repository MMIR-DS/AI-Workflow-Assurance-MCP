#!/usr/bin/env bash
set -euo pipefail

: "${OPENROUTER_API_KEY:?OPENROUTER_API_KEY is required}"
: "${MODEL:?MODEL is required}"
: "${MAX_STEPS:?MAX_STEPS is required}"
: "${MAX_TOKENS:?MAX_TOKENS is required}"

case "$MAX_STEPS" in
  20|40|60) ;;
  *)
    printf 'MAX_STEPS must be one of 20, 40, or 60 (got: %s)\n' "$MAX_STEPS" >&2
    exit 2
    ;;
esac

case "$MAX_TOKENS" in
  1024|1280|2048) ;;
  *)
    printf 'MAX_TOKENS must be one of 1024, 1280, or 2048 (got: %s)\\n' "$MAX_TOKENS" >&2
    exit 2
    ;;
esac

# AWA denials count as tool errors; allow recovery turns while explicit bounds remain active.
PYTHONPATH="../src${PYTHONPATH:+:$PYTHONPATH}" uv run tau2 run \
  --domain retail \
  --agent llm_agent \
  --agent-llm "$MODEL" \
  --agent-llm-args "{\"max_tokens\": ${MAX_TOKENS}, \"temperature\": 0.0}" \
  --user-llm "$MODEL" \
  --user-llm-args "{\"max_tokens\": ${MAX_TOKENS}, \"temperature\": 0.0}" \
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
