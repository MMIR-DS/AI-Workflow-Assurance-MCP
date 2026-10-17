"""Shared Tau2 retail write-tool inventory used by assurance and replay paths."""

WRITE_TOOLS = frozenset({
    "cancel_pending_order",
    "create_order",
    "exchange_delivered_order_items",
    "modify_pending_order_address",
    "modify_pending_order_items",
    "modify_pending_order_payment",
    "modify_user_address",
    "return_delivered_order_items",
})

# Explicitly reviewed Tau2 retail tools that do not mutate retail DB state.
# The pinned-tool smoke test compares this set against Tau2's live toolkit.
TAU2_PASSTHROUGH_TOOLS = frozenset({
    "calculate",
    "find_user_id_by_email",
    "find_user_id_by_name_zip",
    "get_item_details",
    "get_order_details",
    "get_product_details",
    "get_user_details",
    "list_all_product_types",
    "think",
    "transfer_to_human_agents",
})
