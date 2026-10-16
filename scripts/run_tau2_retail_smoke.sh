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
  512|1024|1280|2048) ;;
  *)
    printf 'MAX_TOKENS must be one of 512, 1024, 1280, or 2048 (got: %s)\n' "$MAX_TOKENS" >&2
    exit 2
    ;;
esac

# AWA denials count as tool errors; allow recovery turns while explicit bounds remain active.
# Capture the benchmark status so provider diagnostics can be surfaced before failing the step.
set +e
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

tau2_status=$?
set -e

if grep -Fq "in_flight_budget_exhausted" ../tau2-benchmark.log; then
  printf '%s\n' "::warning::OpenRouter returned HTTP 402 (in_flight_budget_exhausted). This is a provider credit/concurrency condition, not an AWA policy result. No automatic retry was made; wait for in-flight requests to settle, then manually rerun once if appropriate."
fi
if grep -Fq "This model isn't mapped yet" ../tau2-benchmark.log; then
  printf '%s\n' "::notice::LiteLLM did not find local pricing metadata for this model. This warning is separate from request success/failure and is not proof of a model-call failure."
fi

exit "$tau2_status"
