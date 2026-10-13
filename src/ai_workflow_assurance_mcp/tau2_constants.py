"""Shared Tau2 retail write-tool inventory used by assurance and replay paths."""

WRITE_TOOLS = frozenset({
    "cancel_pending_order",
    "exchange_delivered_order_items",
    "modify_pending_order_address",
    "modify_pending_order_items",
    "modify_pending_order_payment",
    "modify_user_address",
    "return_delivered_order_items",
})
