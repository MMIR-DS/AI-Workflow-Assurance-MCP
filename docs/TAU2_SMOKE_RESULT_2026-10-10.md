# tau2 Retail Smoke Run — 2026-10-10

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
- Agent/user cost reported by tau2: `0.0`, but this is **not a reliable billing estimate** because LiteLLM emitted “model isn't mapped yet” warnings for this OpenRouter model. Check the OpenRouter activity/credits page for actual billing.

The first attempt was rejected by OpenRouter because the default request asked for up to 65,535 output tokens while the available credit balance only covered a smaller request. The retry capped agent and user requests at 2,048 tokens and completed the task.

## Interpretation limits

This confirms that the selected model completed one simulated retail exchange task in tau2. It does **not** prove that AI Workflow Assurance independently executed or evaluated the agent, nor does one task establish general reliability. The current benchmark workflow remains separate from AWA until a reviewed adapter maps the raw tau2 trace and final environment state into AWA's normalized observation contract and produces a deterministic AWA report.

## Artifacts

The GitHub Actions run stores the raw tau2 result JSON and log as the artifact `tau2-standalone-retail-smoke` for 14 days.

- Run: https://github.com/MMIR-DS/AI-Workflow-Assurance-MCP/actions/runs/38047957343
- Artifact ID: 11668352434
