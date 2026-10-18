# Keyless Local Model Lab

This is a phone-friendly experiment for testing **real local inference without an API key, paid inference credits, or access to a personal computer**. GitHub Actions downloads public GGUF weights, runs a CPU-only OpenAI-compatible server on the runner, probes a basic completion, optionally probes structured tool-call output, and runs the deterministic offline AWA suite as a separate stage. Relevant pushes to the isolated `feat/keyless-local-model-lab` branch trigger it automatically; the path filter avoids paying the model-download and inference cost for documentation-only edits.

## Run it from a phone

- **Before this PR is merged:** the relevant push to the lab branch starts a run automatically. Open [Actions → Keyless Local Model Lab](../actions/workflows/keyless-model-smoke.yml) and select the newest run on `feat/keyless-local-model-lab`.
- **After the workflow is present on the default branch:** open the same Actions page, tap **Run workflow**, and leave **Probe structured tool-call output** enabled for the first run.
- Open the completed run and download its `keyless-local-model-lab-<run-id>` artifact.

No secrets or API keys are required. The public model download and GitHub Actions runner still require internet access. The automatic trigger is restricted to the lab branch and relevant code/workflow paths; it does not run for documentation-only changes.

## Interpreting the report

- `runtime` records the Python version, installed `llama-cpp-python` version, and selected `chat_format`; `server_health` and `basic_inference` test the local runtime/model path.
- `tool_call_probe` tests whether this exact model/runtime emits a correctly shaped function call. The report records the expected function and arguments and never executes the proposed function. A small model or mismatched formatter may return `NOT_SUPPORTED_OR_INVALID`; that is a measured capability limit, not a hidden pass. The validated `chatml-function-calling` setup produced one valid synthetic call in [run #15](../actions/runs/39096537092), but that result does not generalize to other models or tasks.
- The deterministic offline AWA suite runs separately. Model output does not influence the assurance test oracle.
- The report states `credentials_used=false`, `hosted_inference_api_used=false`, `production_tools_invoked=false`, `release_eligible=false`, and `release_decision=HOLD`.
- This is **not** a Tau2 end-to-end retail task and cannot be treated as fresh model-backed workflow evidence.

## Reproducibility and safety

The workflow pins the public model repository to a specific revision and verifies the downloaded file against its published SHA-256 before starting inference. The report also retains the computed hash for traceability. This guards against accidental file drift, but does not independently prove the publisher's identity or the integrity of the upstream account.

The server binds to loopback only. The probe uses no production connectors, credentials, MCP write tools, or business database. No model-generated result can change the AWA release decision; release remains `HOLD` pending separately reviewed, fresh and evaluable model-backed workflow evidence.
