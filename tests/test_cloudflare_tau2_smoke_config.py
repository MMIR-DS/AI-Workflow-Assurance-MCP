from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_cloudflare_tau2_smoke_is_manual_and_fixed_provider() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "tau2-retail-smoke-cloudflare.yml"
    ).read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "MODEL: cloudflare/@cf/zai-org/glm-4.7-flash" in workflow
    assert "secrets.CLOUDFLARE_API_KEY" in workflow
    assert "secrets.CLOUDFLARE_ACCOUNT_ID" in workflow
    assert "OPENROUTER_API_KEY" not in workflow
    assert "GEMINI_API_KEY" not in workflow
    assert 'options: ["20", "40", "60"]' in workflow
    assert "id: patch_tau2_prompt" in workflow
    assert "install_tau2_prewrite_guard.py" in workflow
    assert "max-concurrency" not in workflow  # concurrency is enforced by the runner


def test_cloudflare_runner_requires_credentials_and_stays_bounded() -> None:
    script = (
        ROOT / "scripts" / "run_tau2_retail_smoke_cloudflare.sh"
    ).read_text(encoding="utf-8")
    for contract in (
        "CLOUDFLARE_API_KEY is required",
        "CLOUDFLARE_ACCOUNT_ID is required",
        "20|40|60",
        "--num-trials 1",
        "--task-ids 0",
        "--seed 300",
        "--max-concurrency 1",
        '--max-steps "$MAX_STEPS"',
        "--max-retries 0",
        "--timeout 480",
    ):
        assert contract in script
