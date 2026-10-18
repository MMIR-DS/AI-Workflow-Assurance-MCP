"""Unit tests for the keyless local-model probe's report and safety contract."""

import json

import pytest

from scripts import keyless_model_probe as probe


@pytest.mark.parametrize(
    ("tool_calls", "expected_status"),
    [
        (
            [
                {
                    "id": "call_valid",
                    "type": "function",
                    "function": {
                        "name": "record_status",
                        "arguments": '{"status": "ready"}',
                    },
                }
            ],
            "PASS",
        ),
        (
            [
                {
                    "id": "call_wrong_args",
                    "type": "function",
                    "function": {
                        "name": "record_status",
                        "arguments": '{"status": "not-ready"}',
                    },
                }
            ],
            "NOT_SUPPORTED_OR_INVALID",
        ),
        (
            [
                {
                    "id": "call_bad_json",
                    "type": "function",
                    "function": {
                        "name": "record_status",
                        "arguments": "{not-json",
                    },
                }
            ],
            "NOT_SUPPORTED_OR_INVALID",
        ),
        ([], "NOT_SUPPORTED_OR_INVALID"),
    ],
    ids=["valid-call", "wrong-arguments", "malformed-json", "no-call"],
)
def test_probe_records_tool_capability_without_executing_tools(
    monkeypatch, tmp_path, capsys, tool_calls, expected_status
):
    report_path = tmp_path / "keyless-model-report.json"
    monkeypatch.setattr(probe, "REPORT_PATH", report_path)
    monkeypatch.setattr(probe, "RUN_TOOL_PROBE", True)
    monkeypatch.setenv("CHAT_FORMAT", "chatml-function-calling")
    monkeypatch.delenv("MODEL_SHA_PATH", raising=False)

    def fake_request_json(path, payload=None):
        if path == "/models":
            return {"data": [{"id": probe.MODEL}]}
        if path == "/chat/completions" and payload is not None:
            if "tools" in payload:
                return {"choices": [{"message": {"tool_calls": tool_calls}}]}
            return {
                "choices": [{"message": {"content": "AWA_LOCAL_OK"}}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
            }
        raise AssertionError(f"Unexpected probe request: {path}")

    monkeypatch.setattr(probe, "request_json", fake_request_json)

    assert probe.main() == 0
    capsys.readouterr()
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert report["runtime"]["name"] == "llama-cpp-python"
    assert report["runtime"]["version"]
    assert report["runtime"]["python_version"]
    assert report["runtime"]["chat_format"] == "chatml-function-calling"
    assert report["stages"]["server_health"]["status"] == "PASS"
    assert report["stages"]["basic_inference"]["status"] == "PASS"

    tool_stage = report["stages"]["tool_call_probe"]
    assert tool_stage["status"] == expected_status
    assert tool_stage["expected_function"] == "record_status"
    assert tool_stage["expected_arguments"] == {"status": "ready"}
    assert tool_stage["tool_execution"] == "NOT_RUN"
    assert tool_stage["valid_structured_tool_call"] is (expected_status == "PASS")
    assert report["production_tools_invoked"] is False
    assert report["release_eligible"] is False
    assert report["release_decision"] == "HOLD"
