from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_tau2_retail_smoke.sh"


def _bash() -> str:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("Bash is required for the Tau2 workflow shell regression test")
    return bash


def _prepare_fake_uv(tmp_path: Path) -> tuple[Path, Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    capture_path = tmp_path / "uv-args.txt"
    work_dir = tmp_path / "tau2-bench"
    work_dir.mkdir()
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$@\" > \"$CAPTURE_ARGS\"\n"
        "printf 'fake tau2 output\\n'\n"
        'exit "$FAKE_UV_EXIT"\n',
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    return bin_dir, capture_path, work_dir


def _env(bin_dir: Path, capture_path: Path, *, uv_exit: int = 0) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "PATH": str(bin_dir) + os.pathsep + env.get("PATH", ""),
            "CAPTURE_ARGS": str(capture_path),
            "FAKE_UV_EXIT": str(uv_exit),
            "OPENROUTER_API_KEY": "test-key-not-used-for-network",
            "OPENROUTER_API_BASE": "https://openrouter.ai/api/v1",
            "MODEL": "openrouter/test/model",
            "MAX_STEPS": "40",
            "MAX_TOKENS": "1024",
        }
    )
    return env


def test_tau2_smoke_command_passes_bounded_flags_as_one_invocation(tmp_path: Path) -> None:
    bash = _bash()
    bin_dir, capture_path, work_dir = _prepare_fake_uv(tmp_path)

    result = subprocess.run(
        [bash, str(SCRIPT)],
        cwd=work_dir,
        env=_env(bin_dir, capture_path),
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    args = capture_path.read_text(encoding="utf-8").splitlines()
    assert args[:3] == ["run", "tau2", "run"]
    for flag, value in (
        ("--agent-llm-args", json.dumps({"max_tokens": 1024, "temperature": 0.0})),
        ("--user-llm-args", json.dumps({"max_tokens": 1024, "temperature": 0.0})),
        ("--max-steps", "40"),
        ("--max-errors", "12"),
        ("--max-retries", "0"),
        ("--timeout", "480"),
        ("--save-to", "tau2-standalone-retail-task0"),
        ("--num-trials", "1"),
        ("--max-concurrency", "1"),
    ):
        assert args[args.index(flag) + 1] == value
    assert (tmp_path / "tau2-benchmark.log").read_text(encoding="utf-8").strip() == (
        "fake tau2 output"
    )


def test_tau2_smoke_command_propagates_uv_failure_through_tee(tmp_path: Path) -> None:
    bash = _bash()
    bin_dir, capture_path, work_dir = _prepare_fake_uv(tmp_path)

    result = subprocess.run(
        [bash, str(SCRIPT)],
        cwd=work_dir,
        env=_env(bin_dir, capture_path, uv_exit=17),
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 17
    assert capture_path.exists()
    assert (tmp_path / "tau2-benchmark.log").read_text(encoding="utf-8").strip() == (
        "fake tau2 output"
    )


def test_tau2_smoke_command_rejects_unbounded_step_values(tmp_path: Path) -> None:
    bash = _bash()
    bin_dir, capture_path, work_dir = _prepare_fake_uv(tmp_path)
    env = _env(bin_dir, capture_path)
    env["MAX_STEPS"] = "100"

    result = subprocess.run(
        [bash, str(SCRIPT)],
        cwd=work_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 2
    assert "MAX_STEPS must be one of" in result.stderr
    assert not capture_path.exists()



def test_tau2_smoke_command_rejects_unbounded_token_values(tmp_path: Path) -> None:
    bash = _bash()
    bin_dir, capture_path, work_dir = _prepare_fake_uv(tmp_path)
    env = _env(bin_dir, capture_path)
    env["MAX_TOKENS"] = "999999"

    result = subprocess.run(
        [bash, str(SCRIPT)],
        cwd=work_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 2
    assert "MAX_TOKENS must be one of" in result.stderr
    assert not capture_path.exists()
