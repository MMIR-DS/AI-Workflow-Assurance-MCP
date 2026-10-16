from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github/workflows/tau2-retail-smoke.yml").read_text(encoding="utf-8")
SCRIPT = (ROOT / "scripts/run_tau2_retail_smoke.sh").read_text(encoding="utf-8")


def test_workflow_defaults_to_conservative_output_token_budget() -> None:
    assert 'default: "1024"' in WORKFLOW
    assert 'options: ["1024", "1280", "2048"]' in WORKFLOW
    assert "MAX_TOKENS: ${{ inputs.max_tokens || '1024' }}" in WORKFLOW


def test_smoke_script_validates_and_applies_token_budget_to_both_models() -> None:
    assert ': "${MAX_TOKENS:?MAX_TOKENS is required}"' in SCRIPT
    assert "1024|1280|2048" in SCRIPT
    assert "--agent-llm-args" in SCRIPT
    assert "--user-llm-args" in SCRIPT
    assert SCRIPT.count('"max_tokens": ${MAX_TOKENS}') == 2
