"""Compatibility facade for the operation-specific Tau2 pre-write policies.

Policy implementation is split by operation. Keep these re-exports stable for the
pinned simulator installer and source-tree tests.
"""

from __future__ import annotations

from ai_workflow_assurance_mcp.tau2_constants import WRITE_TOOLS as _WRITE_TOOLS
from ai_workflow_assurance_mcp.tau2_prewrite_address import (
    _address_confirmation_references_consistent,
    evaluate_tau2_address_prewrite,
)
from ai_workflow_assurance_mcp.tau2_prewrite_cancel import (
    _cancel_confirmation_references_consistent,
    evaluate_tau2_cancel_prewrite,
)
from ai_workflow_assurance_mcp.tau2_prewrite_common import (
    _get,
    _messages,
    _tool_calls,
    _decode_tool_result,
    _find_call_result,
    _normalize_disclosure_text,
    _contains_all,
    _mentioned_order_ids,
    _exchange_pairing_disclosed,
    _order_snapshot_is_fresh,
    _variant_details,
    _alias_is_asserted,
    _assistant_variant_claims_match_catalog,
    _exchange_price_difference,
    _price_difference_disclosed,
    _confirmation_references_consistent,
    _is_affirmative,
    _evaluate_exchange_confirmation_context,
    _latest_blocked_write_result_index,
)
from ai_workflow_assurance_mcp.tau2_prewrite_exchange import evaluate_tau2_prewrite
from ai_workflow_assurance_mcp.tau2_prewrite_items import (
    _has_prior_attempt_not_blocked_by_awa,
    evaluate_tau2_pending_items_prewrite,
)
from ai_workflow_assurance_mcp.tau2_prewrite_payment import (
    _order_and_payment_references_consistent,
    evaluate_tau2_payment_prewrite,
)
from ai_workflow_assurance_mcp.tau2_prewrite_return import evaluate_tau2_return_prewrite
from ai_workflow_assurance_mcp.tau2_prewrite_user_address import (
    _latest_blocked_user_write_result_index,
    _user_snapshot_is_fresh,
    evaluate_tau2_user_address_prewrite,
)

__all__ = [
    "_WRITE_TOOLS",
    "_address_confirmation_references_consistent",
    "_cancel_confirmation_references_consistent",
    "_get",
    "_messages",
    "_tool_calls",
    "_decode_tool_result",
    "_find_call_result",
    "_normalize_disclosure_text",
    "_contains_all",
    "_mentioned_order_ids",
    "_exchange_pairing_disclosed",
    "_order_snapshot_is_fresh",
    "_variant_details",
    "_alias_is_asserted",
    "_assistant_variant_claims_match_catalog",
    "_exchange_price_difference",
    "_price_difference_disclosed",
    "_confirmation_references_consistent",
    "_is_affirmative",
    "_evaluate_exchange_confirmation_context",
    "_latest_blocked_write_result_index",
    "_has_prior_attempt_not_blocked_by_awa",
    "_order_and_payment_references_consistent",
    "_latest_blocked_user_write_result_index",
    "_user_snapshot_is_fresh",
    "evaluate_tau2_prewrite",
    "evaluate_tau2_cancel_prewrite",
    "evaluate_tau2_address_prewrite",
    "evaluate_tau2_payment_prewrite",
    "evaluate_tau2_pending_items_prewrite",
    "evaluate_tau2_user_address_prewrite",
    "evaluate_tau2_return_prewrite",
]
