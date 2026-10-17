from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from scripts.patch_tau2_litellm_retries import (
    ORIGINAL,
    PATCH_MARKER,
    REPLACEMENT,
    patch_llm_source,
)


BASELINE = '''import os
from litellm import completion
DEFAULT_MAX_RETRIES = 3

def generate(kwargs):
''' + ORIGINAL + '''
    return kwargs
'''


def test_retry_override_patch_is_applied_and_idempotent() -> None:
    patched = patch_llm_source(BASELINE)
    assert PATCH_MARKER in patched
    assert ORIGINAL not in patched
    assert patched.count(REPLACEMENT) == 1
    assert patch_llm_source(patched) == patched


def test_environment_override_can_disable_all_hidden_provider_retries() -> None:
    patched = patch_llm_source(BASELINE)
    namespace: dict[str, object] = {}
    executable = patched.replace("from litellm import completion\n", "")
    exec(compile(executable, "pinned_tau2_llm_utils.py", "exec"), namespace)
    generate = namespace["generate"]
    with patch.dict(os.environ, {"TAU2_LITELLM_NUM_RETRIES": "0"}):
        assert generate({})["num_retries"] == 0


def test_unset_override_preserves_pinned_tau2_default() -> None:
    patched = patch_llm_source(BASELINE)
    namespace: dict[str, object] = {}
    executable = patched.replace("from litellm import completion\n", "")
    exec(compile(executable, "pinned_tau2_llm_utils.py", "exec"), namespace)
    generate = namespace["generate"]
    with patch.dict(os.environ):
        os.environ.pop("TAU2_LITELLM_NUM_RETRIES", None)
        assert generate({})["num_retries"] == 3


@pytest.mark.parametrize("value", ["-1", "invalid"])
def test_invalid_environment_override_fails_closed(value: str) -> None:
    patched = patch_llm_source(BASELINE)
    namespace: dict[str, object] = {}
    executable = patched.replace("from litellm import completion\n", "")
    exec(compile(executable, "pinned_tau2_llm_utils.py", "exec"), namespace)
    generate = namespace["generate"]
    with patch.dict(os.environ, {"TAU2_LITELLM_NUM_RETRIES": value}):
        with pytest.raises(ValueError, match="non-negative integer"):
            generate({})


def test_unexpected_tau2_source_is_rejected() -> None:
    with pytest.raises(ValueError, match="Expected exactly one"):
        patch_llm_source(BASELINE.replace(ORIGINAL, "    pass"))
