# Keyless Local Model Lab

This is a phone-triggerable experiment for testing **real local inference without an API key, paid inference credits, or access to a personal computer**. GitHub Actions downloads public GGUF weights, runs a CPU-only OpenAI-compatible server on the runner, probes a basic completion, optionally probes structured tool-call output, and runs the deterministic offline AWA suite as a separate stage.

## Run it from a phone

1. Open [Actions → Keyless Local Model Lab](../actions/workflows/keyless-model-smoke.yml).
2. Tap **Run workflow**.
3. Leave **Probe structured tool-call output** enabled for the first run.
4. Open the completed run and download its `keyless-local-model-lab-<run-id>` artifact.

No secrets or API keys are required. The public model download and GitHub Actions runner still require internet access. The workflow is manual-only because model downloads and CPU inference consume runner time.

## Interpreting the report

- `server_health` and `basic_inference` test the local runtime/model path.
- `tool_call_probe` tests whether this exact model/runtime emits a correctly shaped function call. It never executes the proposed function. A small model may return `NOT_SUPPORTED_OR_INVALID`; that is a measured capability limit, not a hidden pass.
- The deterministic offline AWA suite runs separately. Model output does not influence the assurance test oracle.
- The report states `credentials_used=false`, `hosted_inference_api_used=false`, `production_tools_invoked=false`, `release_eligible=false`, and `release_decision=HOLD`.
- This is **not** a Tau2 end-to-end retail task and cannot be treated as fresh model-backed workflow evidence.

## Reproducibility and safety

The report includes the SHA-256 of the downloaded model for traceability. The model URL points to a public repository, but the file digest is not pinned in the workflow; therefore the hash records what was downloaded and is not a supply-chain authenticity guarantee.

The server binds to loopback only. The probe uses no production connectors, credentials, MCP write tools, or business database. No model-generated result can change the AWA release decision; release remains `HOLD` pending separately reviewed, fresh and evaluable model-backed workflow evidence.
