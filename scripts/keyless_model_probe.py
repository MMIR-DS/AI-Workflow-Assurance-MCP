#!/usr/bin/env python3
"""Probe local inference; tool calls are observed but never executed."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any

BASE_URL = os.environ.get("LOCAL_MODEL_URL", "http://127.0.0.1:8000/v1").rstrip("/")
MODEL = "keyless-qwen"
REPORT_PATH = Path(os.environ.get("REPORT_PATH", "keyless-model-report.json"))
RUN_TOOL_PROBE = os.environ.get("RUN_TOOL_PROBE", "true").lower() == "true"


def request_json(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{BASE_URL}{path}", data=data,
        headers={"Content-Type": "application/json"},
        method="GET" if data is None else "POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not isinstance(result, dict):
        raise ValueError(f"Expected JSON object from {path}")
    return result


def installed_version(distribution: str) -> str:
    """Return a package version without making report generation fragile."""
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return "unknown"


def main() -> int:
    report: dict[str, Any] = {
        "schema_version": "1.0",
        "lab": "keyless-local-model",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "model_alias": MODEL,
        "runtime": {
            "name": "llama-cpp-python",
            "version": installed_version("llama-cpp-python"),
            "python_version": ".".join(str(part) for part in sys.version_info[:3]),
            "chat_format": os.environ.get("CHAT_FORMAT", "unspecified"),
        },
        "endpoint": "localhost-only",
        "credentials_used": False,
        "hosted_inference_api_used": False,
        "production_tools_invoked": False,
        "release_eligible": False,
        "release_decision": "HOLD",
        "stages": {},
        "limitations": [
            "This is not a Tau2 end-to-end task run.",
            "Tool-call capability applies only to this model/runtime pair.",
            "This report cannot change AWA release eligibility.",
        ],
    }
    try:
        models = request_json("/models")
        model_ids = [
            item.get("id") for item in models.get("data", []) if isinstance(item, dict)
        ]
        report["stages"]["server_health"] = {
            "status": "PASS" if model_ids else "FAIL",
            "model_ids": model_ids,
        }
        if not model_ids:
            raise RuntimeError("Local /models endpoint returned no model IDs.")

        started = time.monotonic()
        completion = request_json("/chat/completions", {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": "Follow the instruction exactly."},
                {"role": "user", "content": "Reply with exactly this token: AWA_LOCAL_OK"},
            ],
            "temperature": 0,
            "max_tokens": 32,
        })
        choices = completion.get("choices", [])
        message = choices[0].get("message", {}) if choices else {}
        content = message.get("content", "")
        content_text = content if isinstance(content, str) else json.dumps(content)
        passed = "AWA_LOCAL_OK" in content_text
        report["stages"]["basic_inference"] = {
            "status": "PASS" if passed else "FAIL",
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "response_marker_found": passed,
            "response_excerpt": content_text[:200],
            "usage": completion.get("usage"),
        }
        if not passed:
            raise RuntimeError("Expected marker was absent from local model response.")

        if RUN_TOOL_PROBE:
            started = time.monotonic()
            response = request_json("/chat/completions", {
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": "Use the provided function to report the requested status."},
                    {"role": "user", "content": "Call record_status with status set to ready."},
                ],
                "tools": [{
                    "type": "function",
                    "function": {
                        "name": "record_status",
                        "description": "A harmless test function. It is never executed.",
                        "parameters": {
                            "type": "object",
                            "properties": {"status": {"type": "string", "enum": ["ready"]}},
                            "required": ["status"],
                            "additionalProperties": False,
                        },
                    },
                }],
                "tool_choice": "auto",
                "temperature": 0,
                "max_tokens": 96,
            })
            tool_choices = response.get("choices", [])
            tool_message = tool_choices[0].get("message", {}) if tool_choices else {}
            calls = tool_message.get("tool_calls", [])
            valid = False
            if isinstance(calls, list):
                for call in calls:
                    function = call.get("function", {}) if isinstance(call, dict) else {}
                    if function.get("name") != "record_status":
                        continue
                    try:
                        args = json.loads(function.get("arguments", "{}"))
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if args == {"status": "ready"}:
                        valid = True
                        break
            report["stages"]["tool_call_probe"] = {
                "status": "PASS" if valid else "NOT_SUPPORTED_OR_INVALID",
                "expected_function": "record_status",
                "expected_arguments": {"status": "ready"},
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "valid_structured_tool_call": valid,
                "tool_calls_observed": len(calls) if isinstance(calls, list) else 0,
                "tool_execution": "NOT_RUN",
            }
        else:
            report["stages"]["tool_call_probe"] = {"status": "SKIPPED_BY_INPUT"}

        sha_path = os.environ.get("MODEL_SHA_PATH")
        if sha_path and Path(sha_path).is_file():
            report["model_sha256"] = Path(sha_path).read_text(encoding="utf-8").split()[0]
        report["overall_smoke"] = "PASS"
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        report["overall_smoke"] = "FAIL"
        report["fatal_error"] = {"type": type(exc).__name__, "message": str(exc)[:300]}
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1
    finally:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
