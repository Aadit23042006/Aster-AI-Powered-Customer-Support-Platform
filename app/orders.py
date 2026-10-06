"""Order-status lookup tool.

This is the one place in the codebase that touches `data/orders.json`. The
model never sees that file -- it only ever sees the dict returned by
`OrderLookupTool.lookup()`, which is already field-filtered and status-aware
per the rules in `data/orders-data-dictionary.md`.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app import config

# Exactly the "customer-safe fields" list from orders-data-dictionary.md.
# Anything not in this allowlist (customer.*, internal.*) is never copied
# into the tool result, so it can never leak into the model context no
# matter what the caller asks for.
_SAFE_TOP_LEVEL_FIELDS = {
    "order_id",
    "membership_tier",
    "placed_at",
    "status",
    "status_updated_at",
    "shipped_at",
    "delivered_at",
    "carrier",
    "tracking_number",
    "estimated_delivery",
    "customer_safe_message",
}
_SAFE_ITEM_FIELDS = {"name", "quantity", "final_sale"}

# Statuses where a stale estimated_delivery/carrier field must not be read
# as "still arriving" -- the dictionary calls this out explicitly for
# cancelled/returned orders.
_TERMINAL_NON_ARRIVING_STATUSES = {"cancelled", "returned"}

_ORDER_ID_RE = re.compile(r"^ORD-\d+$")


@dataclass
class OrderLookupResult:
    found: bool
    order_id_queried: str
    data: dict[str, Any] | None = None
    error: str | None = None  # "not_found" | "malformed"

    def to_tool_response(self) -> dict[str, Any]:
        """What actually gets logged/passed back to the model. Never includes
        anything outside the safe-field allowlist."""
        if not self.found:
            return {"found": False, "order_id_queried": self.order_id_queried, "error": self.error}
        return {"found": True, "order_id_queried": self.order_id_queried, **self.data}


def normalize_order_id(raw: str) -> str:
    """Uppercase + strip whitespace/punctuation the dictionary calls
    'harmless input differences' -- e.g. 'ord 1007' -> 'ORD-1007'.

    Also tolerates two conversational forms found through manual testing
    (bug diary entry #3 in the README): the word "order" plus a bare number
    ("order 1007", "order# 1007" both clean to ORDER1007 after punctuation
    stripping), and a bare number by itself ("1007", "#1007"). Does NOT
    guess a substantially different ID -- non-numeric, non-order-shaped
    input is left alone and will simply fail to match any order, which is
    the desired "don't invent a match" behaviour."""
    cleaned = raw.strip().upper()
    cleaned = re.sub(r"[^A-Z0-9-]", "", cleaned)

    m = re.match(r"^ORD-?(\d+)$", cleaned)
    if m:
        return f"ORD-{m.group(1)}"

    m = re.match(r"^ORDER-?(\d+)$", cleaned)
    if m:
        return f"ORD-{m.group(1)}"

    m = re.match(r"^(\d{3,6})$", cleaned)
    if m:
        return f"ORD-{m.group(1)}"

    return cleaned


def _filter_order(order: dict[str, Any]) -> dict[str, Any]:
    safe = {k: v for k, v in order.items() if k in _SAFE_TOP_LEVEL_FIELDS}
    safe["items"] = [
        {k: v for k, v in item.items() if k in _SAFE_ITEM_FIELDS} for item in order.get("items", [])
    ]

    # Status precedence: status is authoritative. Never let a stale
    # estimated_delivery imply "still arriving" once the order is cancelled
    # or returned.
    if order.get("status") in _TERMINAL_NON_ARRIVING_STATUSES:
        safe["estimated_delivery"] = None
        safe["stale_estimate_suppressed"] = True

    return safe


class OrderLookupTool:
    def __init__(self, orders_path: Path = config.ORDERS_PATH):
        payload = json.loads(orders_path.read_text(encoding="utf-8"))
        self.snapshot_at = payload.get("snapshot_at")
        self._by_id: dict[str, dict[str, Any]] = {o["order_id"]: o for o in payload["orders"]}

    def lookup(self, raw_order_id: str) -> OrderLookupResult:
        if not raw_order_id or not raw_order_id.strip():
            return OrderLookupResult(found=False, order_id_queried=raw_order_id, error="malformed")

        normalized = normalize_order_id(raw_order_id)
        if not _ORDER_ID_RE.match(normalized):
            return OrderLookupResult(found=False, order_id_queried=raw_order_id, error="malformed")

        order = self._by_id.get(normalized)
        if order is None:
            return OrderLookupResult(found=False, order_id_queried=normalized, error="not_found")

        return OrderLookupResult(found=True, order_id_queried=normalized, data=_filter_order(order))


ORDER_LOOKUP_TOOL_SCHEMA = {
    "name": "order_lookup",
    "description": (
        "Look up the current status of a customer's order by order ID. "
        "Returns only customer-safe fields (never email, address, or internal "
        "notes). Call this whenever the customer asks about a specific "
        "order's status, shipping, or delivery and has provided (or you "
        "already have, from earlier in this conversation) an order ID."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "order_id": {
                "type": "STRING",
                "description": "The order ID as given by the customer, e.g. 'ORD-1007'.",
            }
        },
        "required": ["order_id"],
    },
}
