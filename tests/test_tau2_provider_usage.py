from __future__ import annotations

from scripts.adapt_tau2_results import (
    _add_provider_usage_warnings,
    _provider_neuron_usage,
)


def test_cloudflare_usage_records_neurons_without_inventing_usd_cost() -> None:
    messages = [
        {"raw_data": {"usage": {"neurons": 1.25}}},
        {"raw_data": {"usage": {"neurons": "2.5"}}},
        {"raw_data": {"usage": {"neurons": -10}}},
        {"raw_data": {"usage": {"neurons": "not-a-number"}}},
        {"raw_data": {"usage": {"neurons": True}}},
        {"raw_data": {"usage": {"neurons": 0}}},
    ]

    usage = _provider_neuron_usage(messages, "openai/@cf/zai-org/glm-4.7-flash")

    assert usage["provider"] == "cloudflare_workers_ai"
    assert usage["metric"] == "neurons"
    assert usage["observed_response_count"] == 3
    assert usage["total_neurons_observed"] == "3.75"
    assert usage["usd_cost_observed"] is None
    assert "must not be read as evidence of zero spend" in usage["usd_cost_note"]


def test_cloudflare_missing_cost_adds_explicit_non_blocking_release_warning() -> None:
    release = {"decision": "GO", "warnings": []}
    metadata = [
        {
            "provider_usage": {
                "provider": "cloudflare_workers_ai",
                "usd_cost_observed": None,
            }
        }
    ]

    _add_provider_usage_warnings(release, metadata)
    _add_provider_usage_warnings(release, metadata)

    matches = [
        warning for warning in release["warnings"]
        if warning.get("code") == "PROVIDER_COST_NOT_OBSERVED"
    ]
    assert len(matches) == 1
    assert release["decision"] == "GO"
    assert "budget compliance" in matches[0]["message"]


def test_other_provider_does_not_receive_cloudflare_specific_warning() -> None:
    release = {"decision": "GO", "warnings": []}
    metadata = [
        {
            "provider_usage": {
                "provider": None,
                "usd_cost_observed": None,
            }
        }
    ]

    _add_provider_usage_warnings(release, metadata)

    assert release["warnings"] == []
