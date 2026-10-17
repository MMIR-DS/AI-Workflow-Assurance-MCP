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
  384|512|1024|1280|2048) ;;
  *)
    printf 'MAX_TOKENS must be one of 384, 512, 1024, 1280, or 2048 (got: %s)\n' "$MAX_TOKENS" >&2
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

# Record an execution-level failure without overwriting a more specific non-zero
# Tau2 exit status that a caller/test may need to diagnose.
mark_failed() {
  if [[ "$tau2_status" -eq 0 ]]; then
    tau2_status=1
  fi
}

results_path="data/simulations/tau2-standalone-retail-task0/results.json"
if [[ -f "$results_path" ]]; then
  # Tau2 can serialize an infrastructure_error while still exiting with status 0.
  if python - "$results_path" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    results = json.load(handle)
simulations = results.get("simulations")
sys.exit(
    1
    if isinstance(simulations, list)
    and any(
        isinstance(simulation, dict)
        and str(simulation.get("termination_reason", "")).lower() == "infrastructure_error"
        for simulation in simulations
    )
    else 0
)
PY
  then
    :
  else
    printf '%s\n' "::error::Tau2 recorded termination_reason=infrastructure_error; inspect tau2-benchmark.log and tau2-execution-status.json."
    mark_failed
  fi
else
  printf '%s\n' "::error::Tau2 did not produce the expected results.json file."
  mark_failed
fi

if grep -Fq "in_flight_budget_exhausted" ../tau2-benchmark.log; then
  printf '%s\n' "::warning::OpenRouter returned HTTP 402 (in_flight_budget_exhausted). This is a transient in-flight budget condition, not an AWA policy result. No automatic retry was made; rerun separately after the provider condition clears."
  mark_failed
elif grep -Eiq "Prompt tokens limit exceeded: [0-9]+ > [0-9]+" ../tau2-benchmark.log; then
  printf '%s\n' "::error::OpenRouter rejected the prompt because its token count exceeds the key/workspace prompt-token budget. Lowering MAX_TOKENS will not reduce input prompt tokens; adjust the OpenRouter key limit/available credits or reduce the prompt/tool context before another model-backed run."
  mark_failed
elif grep -Eiq "weight_exceeds_budget|openrouter_credits|can only afford|requires more credits, or fewer max_tokens" ../tau2-benchmark.log; then
  printf '%s\n' "::warning::OpenRouter rejected the request because its estimated credit/token reservation exceeded the available budget. Adjust available credits/key limits; a lower output cap may help only when the rejection concerns the requested completion budget, not an oversized prompt."
  mark_failed
fi
if grep -Fq "This model isn't mapped yet" ../tau2-benchmark.log; then
  printf '%s\n' "::notice::LiteLLM did not find local pricing metadata for this model. This warning is separate from request success/failure and is not proof of a model-call failure."
fi

exit "$tau2_status"
