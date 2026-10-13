# tau2 Retail Smoke Run — 2026-10-10

> **Historical, one-task benchmark record.** This page preserves the original model-backed Tau2 run and its recorded reward/state-match outputs. Those benchmark metrics are not AWA authorization evidence. Since this run, the pinned Tau2 dispatcher has a separate V6 simulator-only pre-write guard and the current adapter evaluates the saved raw trace as `NO_GO` when required pre-write disclosure is absent. See the current enforcement docs and CI workflows for current behavior; this 2026-10-10 run itself was not rerun under V6.


## Result

- Benchmark: public `sierra-research/tau2-bench`, retail domain, task ID `0`
- Model: `openrouter/google/gemini-2.5-flash` for both agent and user simulator
- Trials: 1
- Maximum steps: 40
- Maximum output tokens per model request: 2,048
- tau2 task reward: **1.0**
- Database state match: **true**
- Action checks: **5/5 matched**
- Termination: `user_stop`
- Simulation duration: approximately 17.8 seconds
- Agent/user aggregate cost reported by tau2: `0.0`, which is **not reliable** because LiteLLM emitted “model isn't mapped yet” warnings for this OpenRouter model. Summing per-message provider usage metadata in the saved trace gives approximately **$0.01660 USD**. Treat this as an estimate and reconcile with OpenRouter's activity/billing page.

The first attempt was rejected by OpenRouter because the default request asked for up to 65,535 output tokens while the available credit balance only covered a smaller request. The retry capped agent and user requests at 2,048 tokens and completed the task.

## Interpretation limits

This confirms that the selected model completed one simulated retail exchange task in tau2. It does **not** prove that AI Workflow Assurance independently executed or evaluated the agent, nor does one task establish general reliability. This historical run predates the current adapter and V6 dispatcher guard. Current no-model CI workflows separately test the normalized saved-trace adapter, raw-trace `NO_GO`, pinned dispatcher callback suppression, and independent database-state verification. Those checks do not retroactively change how this historical model-backed run executed.

## Artifacts

The GitHub Actions run stores the raw tau2 result JSON and log as the artifact `tau2-standalone-retail-smoke` for 14 days.

- Run: https://github.com/MMIR-DS/AI-Workflow-Assurance-MCP/actions/runs/38047957343
- Artifact ID: 11668352434
