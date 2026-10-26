from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_cloudflare_tau2_smoke_is_manual_and_uses_openai_compatible_route() -> None:
    workflow = (
        ROOT / ".github" / "workflows" / "tau2-retail-smoke-cloudflare.yml"
    ).read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert 'default: "gpt-oss-120b"' in workflow
    assert 'options: ["gpt-oss-120b", "glm-4.7-flash"]' in workflow
    assert "openai/@cf/openai/gpt-oss-120b" in workflow
    assert "openai/@cf/zai-org/glm-4.7-flash" in workflow
    assert "inputs.model || 'gpt-oss-120b'" in workflow
    assert "OPENAI_API_KEY: ${{ secrets.CLOUDFLARE_API_KEY || secrets.CLOUDFLARE_API }}" in workflow
    cloudflare_base = (
        "https://api.cloudflare.com/client/v4/accounts/"
        "${{ secrets.CLOUDFLARE_ACCOUNT_ID }}/ai/v1"
    )
    assert f"OPENAI_BASE_URL: {cloudflare_base}" in workflow
    assert f"OPENAI_API_BASE: {cloudflare_base}" in workflow
    assert "secrets.CLOUDFLARE_API_KEY" in workflow
    assert "secrets.CLOUDFLARE_API" in workflow
    assert "secrets.CLOUDFLARE_ACCOUNT_ID" in workflow
    assert "MODEL: cloudflare/" not in workflow
    assert "OPENROUTER_API_KEY" not in workflow
    assert "GEMINI_API_KEY" not in workflow
    assert 'options: ["20", "40", "60"]' in workflow
    assert "id: patch_tau2_prompt" in workflow
    assert "id: patch_tau2_user_completion" in workflow
    assert "patch_tau2_retail_user_simulator.py" in workflow
    assert "steps.patch_tau2_user_completion.outputs.prompt_mode" in workflow
    assert "steps.patch_tau2_user_completion.outputs.prompt_marker" in workflow
    assert "install_tau2_prewrite_guard.py" in workflow
    assert "max-concurrency" not in workflow  # concurrency is enforced by the runner


def test_cloudflare_prompt_makes_prewrite_no_go_a_terminal_stop() -> None:
    prompt_patch = (
        ROOT / "scripts" / "patch_tau2_retail_agent_prompt.py"
    ).read_text(encoding="utf-8")
    hard_stop = "<" + "!-- AWA_PREWRITE_NO_GO_HARD_STOP_V2 -->"
    assert hard_stop in prompt_patch
    assert "write path for this trial is permanently closed" in prompt_patch
    assert "Do not call any write tool again during this trial" in prompt_patch
    assert "Do not bypass, reset, or work around the guard" in prompt_patch
    assert "Never place all old items in a \\\"Current Items\\\" list followed by all replacements in a separate \\\"New Items\\\" list" in prompt_patch
    assert "old1, new1, old2, new2 order" in prompt_patch
    assert "The very next assistant turn MUST be a text-only customer message" in prompt_patch
    assert "Do not rely on the transfer tool's automatic" in prompt_patch
    assert "Every assistant message that asks for exchange confirmation must be a complete, standalone disclosure" in prompt_patch
    assert "do NOT answer with only the requested fragment" in prompt_patch
    assert "FINAL RESPONSE SAFETY RULE" in prompt_patch
    assert '"Your exchange has been successfully processed"' in prompt_patch
    assert '"Status: exchange requested."' in prompt_patch
    assert "Use this minimal final-response template" in prompt_patch
    assert "Do not add a refund-processing deadline" in prompt_patch
    assert "Do not claim that an email was already sent" in prompt_patch
    assert "RUNTIME_PATCH_MARKER = \"AWA_PREWRITE_NO_GO_HANDOFF_RUNTIME_V3\"" in prompt_patch
    assert "AWA_EXCHANGE_CONFIRMATION_TURN_GUARD_V1" in prompt_patch
    assert "def patch_no_go_handoff_runtime(source: str) -> str:" in prompt_patch
    assert 'assistant_message.content = ""' in prompt_patch
    assert prompt_patch.index(hard_stop) < prompt_patch.index("CRITICAL EXCHANGE GATE")


def test_cloudflare_runner_requires_credentials_and_stays_bounded() -> None:
    script = (
        ROOT / "scripts" / "run_tau2_retail_smoke_cloudflare.sh"
    ).read_text(encoding="utf-8")
    for contract in (
        "CLOUDFLARE_API_KEY is required",
        "CLOUDFLARE_ACCOUNT_ID is required",
        "OPENAI_API_KEY alias is required",
        "OPENAI_BASE_URL is required",
        "OPENAI_API_BASE compatibility alias is required",
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
