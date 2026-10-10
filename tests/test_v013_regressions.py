from __future__ import annotations

import math

import pytest

from ai_workflow_assurance_mcp.core import AssuranceInputError, stable_json_digest


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_stable_digest_normalizes_non_finite_values_to_input_error(value: float) -> None:
    with pytest.raises(AssuranceInputError, match="non-finite"):
        stable_json_digest({"value": value})


def test_stable_digest_normalizes_unsupported_values_to_input_error() -> None:
    with pytest.raises(AssuranceInputError, match="unsupported or non-finite"):
        stable_json_digest({"value": object()})
