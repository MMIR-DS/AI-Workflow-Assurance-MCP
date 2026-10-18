# Keyless Local Model Lab

This is a phone-friendly experiment for testing **real local inference without an API key, paid inference credits, or access to a personal computer**. GitHub Actions downloads public GGUF weights, runs a CPU-only OpenAI-compatible server on loopback, probes a basic completion and structured tool-call output, and runs the probe contract tests and repository test suite separately from model inference. Relevant pushes to the isolated `feat/keyless-local-model-lab-main` branch trigger it automatically; the path filter avoids paying the model-download and inference cost for documentation-only edits.

## Run it from a phone

- **Before this PR is merged:** a relevant push to the lab branch starts validation automatically. Open [Actions → Keyless Local Model Lab](https://github.com/MMIR-DS/AI-Workflow-Assurance-MCP/actions/workflows/keyless-model-smoke.yml) and select the newest run on `feat/keyless-local-model-lab-main`.
- **After the workflow is present on the default branch:** open that Actions page, tap **Run workflow**, and leave **Probe structured tool-call output** enabled for the first run.
- Open the completed run and download its `keyless-local-model-lab-<run-id>` artifact.

No secrets or API keys are required. The public model and package downloads require runner internet access. The push trigger is limited to the lab branch and relevant code/workflow paths; documentation-only changes do not re-download the model.

## Interpreting the report

- `runtime` records the Python version, installed `llama-cpp-python` version, and selected `chat_format`; `server_health` and `basic_inference` test the local runtime/model path.
- `tool_call_probe` tests whether this exact model/runtime emits a correctly shaped function call. The report records the expected function and arguments and never executes the proposed function. The probe only passes when there is exactly one call with a non-empty ID, `type=function`, the expected function name, and exactly the expected arguments. Multiple calls or incomplete wrappers are rejected. A small model or mismatched formatter may return `NOT_SUPPORTED_OR_INVALID`; that is a measured capability limit, not a hidden pass.
- The main-based validation in [run #25](https://github.com/MMIR-DS/AI-Workflow-Assurance-MCP/actions/runs/39112781455) recorded a valid synthetic tool call under the stricter single-call envelope checks, passed all 16 probe contract cases, and passed the repository suite (377 tests and 20 subtests). In that run the basic marker took 0.198 seconds and structured tool-call validation took 1.207 seconds. These results apply only to this exact model/runtime pair, not other models or tasks.
- [Download the run #25 evidence artifact](https://github.com/MMIR-DS/AI-Workflow-Assurance-MCP/actions/runs/39112781455/artifacts/12130849072), which contains the report JSON, model hash, and server log.
- The report states `credentials_used=false`, `hosted_inference_api_used=false`, `production_tools_invoked=false`, `release_eligible=false`, and `release_decision=HOLD`. [CI #1574](https://github.com/MMIR-DS/AI-Workflow-Assurance-MCP/actions/runs/39112781425) also passed the Python 3.10–3.13 matrix and Windows installed-wheel MCP smoke on the tested code head.
- This is **not** a Tau2 end-to-end retail task and cannot be treated as fresh model-backed workflow evidence.

## Reproducibility and safety

The workflow pins the public model repository to a specific revision and checks the download against a pinned expected SHA-256 before starting inference. The hash is retained in the report for traceability. This guards against accidental file drift; it does not independently prove the identity or integrity of the upstream publisher.

The server binds to loopback, and the probe itself rejects any `LOCAL_MODEL_URL` that is not an HTTP `/v1` endpoint with a loopback IP literal. It also rejects usernames/passwords, query strings, and fragments before making a request. The probe uses no production connectors, credentials, MCP write tools, or business database. No model-generated result can change the AWA release decision; release remains `HOLD` pending separately reviewed, fresh and evaluable model-backed workflow evidence.
