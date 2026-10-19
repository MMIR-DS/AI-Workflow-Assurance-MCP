from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_manual_tau2_smoke_uses_cost_conservative_defaults() -> None:
    workflow = (ROOT / ".github" / "workflows" / "tau2-retail-smoke.yml").read_text(
        encoding="utf-8"
    )
    assert 'default: "20"' in workflow
    assert "MAX_STEPS: ${{ inputs.max_steps || '20' }}" in workflow
    assert 'options: ["20", "40", "60"]' in workflow
    assert "id: patch_tau2_prompt" in workflow
    assert "steps.patch_tau2_prompt.outputs.prompt_mode" in workflow
    assert "steps.patch_tau2_prompt.outputs.prompt_marker" in workflow
    assert 'MODEL: gemini/gemini-3.8-flash' in workflow
    assert "secrets.GEMINI_API_KEY" in workflow
    assert "OPENROUTER_API_KEY" not in workflow
    assert "OPENROUTER_API_BASE" not in workflow

    runner = (ROOT / "scripts" / "run_tau2_retail_smoke.sh").read_text(encoding="utf-8")
    assert "GEMINI_API_KEY is required" in runner
    assert "OPENROUTER_API_KEY" not in runner


def test_tau2_smoke_remains_one_trial_and_bounded() -> None:
    script = (ROOT / "scripts" / "run_tau2_retail_smoke.sh").read_text(encoding="utf-8")
    for contract in (
        "20|40|60",
        "--num-trials 1",
        "--task-ids 0",
        '--max-concurrency 1',
        '--max-steps "$MAX_STEPS"',
        "--max-retries 0",
        "--timeout 480",
    ):
        assert contract in script
