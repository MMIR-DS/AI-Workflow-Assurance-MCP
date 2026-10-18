"""Unit tests for the keyless local-model probe's report and safety contract."""

import json
import urllib.request

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
        (
            [{"id": "call_bad_shape", "type": "function", "function": None}],
            "NOT_SUPPORTED_OR_INVALID",
        ),
        (
            [{
                "type": "function",
                "function": {"name": "record_status", "arguments": '{"status": "ready"}'},
            }],
            "NOT_SUPPORTED_OR_INVALID",
        ),
        (
            [{
                "id": "call_wrong_type",
                "type": "other",
                "function": {"name": "record_status", "arguments": '{"status": "ready"}'},
            }],
            "NOT_SUPPORTED_OR_INVALID",
        ),
        (
            [
                {
                    "id": "call_valid",
                    "type": "function",
                    "function": {"name": "record_status", "arguments": '{"status": "ready"}'},
                },
                {
                    "id": "call_extra",
                    "type": "function",
                    "function": {"name": "unexpected_tool", "arguments": '{}'},
                },
            ],
            "NOT_SUPPORTED_OR_INVALID",
        ),
        (
            [{
                "id": "call_wrong_function",
                "type": "function",
                "function": {"name": "unexpected_tool", "arguments": '{}'},
            }],
            "NOT_SUPPORTED_OR_INVALID",
        ),
        ("not-a-tool-call", "NOT_SUPPORTED_OR_INVALID"),
        ([], "NOT_SUPPORTED_OR_INVALID"),
    ],
    ids=[
        "valid-call",
        "wrong-arguments",
        "malformed-json",
        "malformed-function-shape",
        "missing-call-id",
        "wrong-call-type",
        "multiple-calls",
        "wrong-function",
        "non-object-call",
        "no-call",
    ],
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


@pytest.mark.parametrize(
    "base_url",
    [
        "https://example.com/v1",
        "http://example.com/v1",
        "http://127.0.0.1.attacker.example:8000/v1",
        "http://127.0.0.1:8000/v1?redirect=https://example.com",
        "http://user@127.0.0.1:8000/v1",
        "http://127.0.0.1:99999/v1",
    ],
)
def test_request_json_rejects_nonlocal_or_ambiguous_endpoints_before_network(
    monkeypatch, base_url
):
    monkeypatch.setattr(probe, "BASE_URL", base_url)

    def unexpected_network_call(*args, **kwargs):
        pytest.fail("The probe must reject this endpoint before opening a connection.")

    monkeypatch.setattr(probe.urllib.request, "build_opener", unexpected_network_call)

    with pytest.raises(ValueError, match="LOCAL_MODEL_URL"):
        probe.request_json("/models")



def test_local_request_disables_proxies_and_redirects(monkeypatch):
    monkeypatch.setattr(probe, "BASE_URL", "http://127.0.0.1:8000/v1")
    observed = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return False

        def read(self):
            return b'{"data":[{"id":"keyless-qwen"}]}'

    class FakeOpener:
        def open(self, request, timeout):
            observed["url"] = request.full_url
            observed["timeout"] = timeout
            return FakeResponse()

    def fake_build_opener(*handlers):
        observed["proxy_handler"] = any(
            isinstance(handler, urllib.request.ProxyHandler)
            and handler.proxies == {}
            for handler in handlers
        )
        observed["no_redirect_handler"] = any(
            isinstance(handler, probe._NoRedirectHandler) for handler in handlers
        )
        return FakeOpener()

    monkeypatch.setattr(probe.urllib.request, "build_opener", fake_build_opener)

    assert probe.request_json("/models") == {"data": [{"id": "keyless-qwen"}]}
    assert observed["url"] == "http://127.0.0.1:8000/v1/models"
    assert observed["timeout"] == 120
    assert observed["proxy_handler"] is True
    assert observed["no_redirect_handler"] is True
