from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/tau2-retail-smoke.yml").read_text(encoding="utf-8")
SCRIPT = (ROOT / "scripts/run_tau2_retail_smoke.sh").read_text(encoding="utf-8")


def test_workflow_defaults_to_conservative_output_token_budget() -> None:
    assert 'default: "1024"' in WORKFLOW
    assert 'options: ["512", "1024", "1280", "2048"]' in WORKFLOW
    assert "MAX_TOKENS: ${{ inputs.max_tokens || '1024' }}" in WORKFLOW


def test_smoke_script_validates_and_applies_token_budget_to_both_models() -> None:
    assert ': "${MAX_TOKENS:?MAX_TOKENS is required}"' in SCRIPT
    assert "512|1024|1280|2048" in SCRIPT
    assert "--agent-llm-args" in SCRIPT
    assert "--user-llm-args" in SCRIPT
    # Shell-escaped JSON quotes mean the source text contains escaped key quotes.
    # Verify the bounded variable is present for both model args as well as validation.
    assert SCRIPT.count("${MAX_TOKENS}") == 2
