"""Database-backed order access.

Two consumers:
1. The REST API (`app/api/orders_routes.py`) -- straightforward, always
   filtered to `current_user.id` at the query level.
2. The AI agent's `order_lookup` tool -- `DBOrderLookupTool` below, which
   swaps in for the JSON-backed `app.orders.OrderLookupTool` used by the
   CLI/eval harness.

The database-backed tool:
- validates the order ID;
- scopes every lookup to the authenticated user;
- never exposes another customer's order;
- returns customer-safe fields only;
- supports latest-order resolution;
- records AI order lookups in the Enterprise Action Center as read-only
  audit records;
- never requires the customer to have staff-level `orders.read` permission
  merely to record an audit entry;
- never allows Action Center auditing to break a valid order lookup.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.orders import (
    OrderLookupResult,
    _ORDER_ID_RE,
    _SAFE_ITEM_FIELDS,
    _TERMINAL_NON_ARRIVING_STATUSES,
    normalize_order_id,
)
from app.db.models import AIAction, Order


logger = logging.getLogger("aster_row.order_service")


# ---------------------------------------------------------------------------
# Request / agent context
# ---------------------------------------------------------------------------

# Set by the conversation route for the duration of one agent turn.
#
# The AI agent itself does not need to be modified to accept the authenticated
# user ID. The context variable allows DBOrderLookupTool to enforce ownership
# deep inside the tool call.
current_user_id_var: contextvars.ContextVar[
    uuid.UUID | None
] = contextvars.ContextVar(
    "current_user_id",
    default=None,
)


# Set by the conversation route for the duration of one agent turn.
#
# This lets the Action Center audit entry point back to the conversation that
# caused the lookup.
current_conversation_id_var: contextvars.ContextVar[
    uuid.UUID | None
] = contextvars.ContextVar(
    "current_conversation_id",
    default=None,
)


# ---------------------------------------------------------------------------
# Customer-safe order serialization
# ---------------------------------------------------------------------------

def _order_to_safe_dict(order: Order) -> dict[str, Any]:
    """Convert an Order ORM object into the customer-safe order structure.

    Only fields already approved by the application's order lookup contract
    are exposed.

    This function intentionally does not expose internal database fields,
    customer-private fields, payment information, addresses, etc.
    """
    safe = {
        "order_id": order.order_number,
        "membership_tier": order.membership_tier,
        "placed_at": (
            order.placed_at.isoformat()
            if order.placed_at
            else None
        ),
        "status": order.status,
        "status_updated_at": (
            order.status_updated_at.isoformat()
            if order.status_updated_at
            else None
        ),
        "shipped_at": (
            order.shipped_at.isoformat()
            if order.shipped_at
            else None
        ),
        "delivered_at": (
            order.delivered_at.isoformat()
            if order.delivered_at
            else None
        ),
        "carrier": order.carrier,
        "tracking_number": order.tracking_number,
        "estimated_delivery": (
            order.estimated_delivery.isoformat()
            if order.estimated_delivery
            else None
        ),
        "customer_safe_message": order.customer_safe_message,
        "items": [
            {
                key: value
                for key, value in {
                    "name": item.product_name,
                    "quantity": item.quantity,
                    "final_sale": item.final_sale,
                }.items()
                if key in _SAFE_ITEM_FIELDS
            }
            for item in order.items
        ],
    }

    # Never expose a stale estimated delivery date for terminal states where
    # the order is no longer expected to arrive.
    if order.status in _TERMINAL_NON_ARRIVING_STATUSES:
        safe["estimated_delivery"] = None
        safe["stale_estimate_suppressed"] = True

    return safe


# ---------------------------------------------------------------------------
# Action Center integration
# ---------------------------------------------------------------------------

def _lookup_action_idempotency_key(
    *,
    user_id: uuid.UUID,
    order_id: str,
    conversation_id: uuid.UUID | None,
) -> str:
    """Create a deterministic idempotency key for an AI order lookup.

    This is intentionally local to this service.

    We do not call `action_center.execute()` here because that method applies
    the staff-facing `orders.read` permission check. A customer is allowed to
    access their OWN order without having that staff-level permission.

    The actual order lookup has already enforced ownership at the database
    query level, so this function only creates the audit identity.
    """
    raw = json.dumps(
        {
            "user_id": str(user_id),
            "tool_name": "lookup_order",
            "order_id": order_id,
            "conversation_id": (
                str(conversation_id)
                if conversation_id
                else None
            ),
        },
        sort_keys=True,
        default=str,
    )

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def _record_ai_order_lookup_action(
    db: Session,
    *,
    user_id: uuid.UUID,
    order_id: str,
    result: dict[str, Any],
) -> None:
    """Record an AI order lookup as a read-only Action Center audit entry.

    IMPORTANT SECURITY / PERMISSION DESIGN:

    `orders.read` is a staff-level permission meaning that the user may view
    arbitrary customers' orders.

    A normal customer does NOT have that permission, because customers should
    only be able to access their own orders.

    However, the AI agent is already operating on behalf of the authenticated
    customer, and the actual order lookup has already enforced:

        Order.order_number == normalized
        Order.user_id == authenticated_user_id

    Therefore the audit record itself must not require the customer to have
    staff-level `orders.read`.

    Instead of calling:

        action_center.execute(...)

    this function writes the already-completed READ_ONLY audit record directly
    to `ai_actions`.

    This prevents:

        PermissionError("Insufficient permissions")

    from breaking an otherwise valid customer order lookup.

    The function NEVER raises an exception to the caller.
    """
    try:
        conversation_id = current_conversation_id_var.get()

        idempotency_key = _lookup_action_idempotency_key(
            user_id=user_id,
            order_id=order_id,
            conversation_id=conversation_id,
        )

        # ---------------------------------------------------------------
        # Prevent duplicate audit rows for the same AI lookup.
        # ---------------------------------------------------------------
        existing = (
            db.query(AIAction)
            .filter(
                AIAction.idempotency_key == idempotency_key,
                AIAction.user_id == user_id,
                AIAction.tool_name == "lookup_order",
            )
            .order_by(AIAction.created_at.desc())
            .first()
        )

        if existing is not None:
            logger.debug(
                "AI lookup_order audit already exists: "
                "action_id=%s user_id=%s order_id=%s",
                existing.id,
                user_id,
                order_id,
            )
            return

        # ---------------------------------------------------------------
        # Sanitize the result before storing it in the audit record.
        # ---------------------------------------------------------------
        try:
            from app.security.pii import redact_pii

            sanitized_result = redact_pii(result)
        except Exception:
            # Auditing must not break the order lookup even if sanitization
            # has an unexpected problem.
            sanitized_result = {
                "found": bool(result.get("found")),
            }

        # ---------------------------------------------------------------
        # Directly create the completed READ_ONLY audit record.
        #
        # This is deliberately NOT a mutating Action Center action.
        #
        # No approval is required.
        # ---------------------------------------------------------------
        row = AIAction(
            conversation_id=conversation_id,
            user_id=user_id,
            tool_name="lookup_order",
            arguments_sanitized={
                "order_id": order_id,
            },
            permission_result="ALLOWED",
            execution_status="success",
            result_sanitized=sanitized_result,
            risk_level="LOW",
            duration_ms=None,
            error=None,
            category="read_only",
            origin="ai",
            reason=(
                "AI agent looked up the authenticated customer's order."
            ),
            approval_status="not_required",
            approved_by=None,
            approved_at=None,
            idempotency_key=idempotency_key,
            ticket_id=None,
            order_number=order_id,
        )

        db.add(row)
        db.commit()

        logger.info(
            "Recorded AI lookup_order Action Center audit: "
            "action_id=%s user_id=%s order_id=%s found=%s",
            row.id,
            user_id,
            order_id,
            result.get("found"),
        )

    except Exception:
        # ---------------------------------------------------------------
        # CRITICAL:
        #
        # Action Center auditing is secondary to the actual customer order
        # lookup.
        #
        # If audit persistence fails for any reason, the customer must still
        # receive the real order lookup result.
        # ---------------------------------------------------------------
        try:
            db.rollback()
        except Exception:
            pass

        logger.exception(
            "Failed to record AI lookup_order Action Center action "
            "for order_id=%s user_id=%s",
            order_id,
            user_id,
        )


# ---------------------------------------------------------------------------
# Database-backed AI order lookup tool
# ---------------------------------------------------------------------------

class DBOrderLookupTool:
    """Database-backed replacement for `app.orders.OrderLookupTool`.

    Public interface:

        lookup(raw_order_id) -> OrderLookupResult

    This makes the class compatible with:

        Agent.set_order_tool()

    Every lookup is scoped to the authenticated user stored in
    `current_user_id_var`.

    AI lookups are recorded as read-only Action Center audit records.
    """

    def __init__(self, db_factory):
        # `db_factory` must return a fresh SQLAlchemy Session.
        #
        # We intentionally do not keep a database session open for the
        # lifetime of the application or Agent instance.
        self._db_factory = db_factory

    def lookup(self, raw_order_id: str) -> OrderLookupResult:
        """Look up one order while enforcing authenticated-user ownership."""

        # ---------------------------------------------------------------
        # 1. Validate input before touching the database.
        # ---------------------------------------------------------------
        if not raw_order_id or not raw_order_id.strip():
            return OrderLookupResult(
                found=False,
                order_id_queried=raw_order_id,
                error="malformed",
            )

        normalized = normalize_order_id(raw_order_id)

        if not _ORDER_ID_RE.match(normalized):
            return OrderLookupResult(
                found=False,
                order_id_queried=raw_order_id,
                error="malformed",
            )

        # ---------------------------------------------------------------
        # 2. Get authenticated user from request context.
        # ---------------------------------------------------------------
        user_id = current_user_id_var.get()

        # TEMPORARY DIAGNOSTIC:
        # This confirms whether the authenticated user context reaches the
        # database-backed AI order lookup.
        logger.warning(
            "[DEBUG ORDER LOOKUP] user_id=%r order_id=%r",
            user_id,
            normalized,
        )

        # An AI order lookup without an authenticated user MUST NOT fall
        # back to a global order search.
        if user_id is None:
            logger.warning(
                "[DEBUG ORDER LOOKUP] user_id is None; "
                "returning not_found for order_id=%r",
                normalized,
            )

            return OrderLookupResult(
                found=False,
                order_id_queried=normalized,
                error="not_found",
            )

        db: Session = self._db_factory()

        try:
            # -----------------------------------------------------------
            # 3. SECURITY CRITICAL:
            #
            # Ownership is enforced directly in the database query.
            #
            # We do NOT:
            #
            #     query by order_number
            #     then check user_id in Python
            #
            # The database query itself is scoped to the authenticated
            # customer.
            # -----------------------------------------------------------
            order = (
                db.query(Order)
                .filter(
                    Order.order_number == normalized,
                    Order.user_id == user_id,
                )
                .first()
            )

            # TEMPORARY DIAGNOSTIC:
            # This confirms whether the database query itself finds the
            # authenticated customer's order.
            logger.warning(
                "[DEBUG ORDER LOOKUP] order_found=%s "
                "user_id=%r order_id=%r",
                order is not None,
                user_id,
                normalized,
            )

            # -----------------------------------------------------------
            # 4. Not found.
            #
            # Deliberately use the same result for:
            #
            #   - order does not exist
            #   - order exists but belongs to another customer
            #
            # This prevents order-existence enumeration.
            # -----------------------------------------------------------
            if order is None:
                lookup_result = OrderLookupResult(
                    found=False,
                    order_id_queried=normalized,
                    error="not_found",
                )

                _record_ai_order_lookup_action(
                    db,
                    user_id=user_id,
                    order_id=normalized,
                    result={
                        "found": False,
                    },
                )

                return lookup_result

            # -----------------------------------------------------------
            # 5. Serialize only customer-safe fields.
            # -----------------------------------------------------------
            safe_data = _order_to_safe_dict(order)

            lookup_result = OrderLookupResult(
                found=True,
                order_id_queried=normalized,
                data=safe_data,
            )

            # -----------------------------------------------------------
            # 6. Record successful AI lookup.
            #
            # This is READ_ONLY:
            #   - no approval;
            #   - no mutation;
            #   - Action Center audit only.
            #
            # The customer does NOT need staff-level `orders.read`.
            # -----------------------------------------------------------
            _record_ai_order_lookup_action(
                db,
                user_id=user_id,
                order_id=normalized,
                result={
                    "found": True,
                    **safe_data,
                },
            )

            return lookup_result

        except Exception:
            # -----------------------------------------------------------
            # Do not leak internal database errors through the AI order
            # lookup contract.
            # -----------------------------------------------------------
            logger.exception(
                "Unexpected database error during AI order lookup: "
                "user_id=%s order_id=%s",
                user_id,
                normalized,
            )

            try:
                db.rollback()
            except Exception:
                pass

            return OrderLookupResult(
                found=False,
                order_id_queried=normalized,
                error="not_found",
            )

        finally:
            db.close()


# ---------------------------------------------------------------------------
# Latest-order helpers
# ---------------------------------------------------------------------------

def get_latest_order_for_current_user(db_factory) -> str | None:
    """Return the newest order number belonging to the authenticated user.

    Supports natural-language requests such as:

        "What is the status of my latest order?"
        "What's my most recent order?"
        "Where is my last order?"

    Security properties:

    - Uses `current_user_id_var`.
    - Never searches globally.
    - Never returns another customer's order.
    - Returns None without an authenticated user.
    - Returns None when the customer has no orders.

    The returned value is only the order number. The normal
    `DBOrderLookupTool.lookup()` must still be used to obtain customer-safe
    order data.
    """
    user_id = current_user_id_var.get()

    if user_id is None:
        return None

    db: Session = db_factory()

    try:
        order = (
            db.query(Order)
            .filter(Order.user_id == user_id)
            .order_by(Order.placed_at.desc())
            .first()
        )

        if order is None:
            return None

        return order.order_number

    finally:
        db.close()


def get_latest_order_for_user(
    db: Session,
    user_id: uuid.UUID,
) -> Order | None:
    """Return the newest Order belonging to a specific user.

    Ownership is enforced directly in the database query.
    """
    return (
        db.query(Order)
        .filter(Order.user_id == user_id)
        .order_by(Order.placed_at.desc())
        .first()
    )


# ---------------------------------------------------------------------------
# REST API order helpers
# ---------------------------------------------------------------------------

def list_orders_for_user(
    db: Session,
    user_id: uuid.UUID,
) -> list[Order]:
    """Return all orders belonging to one user, newest first."""
    return (
        db.query(Order)
        .filter(Order.user_id == user_id)
        .order_by(Order.placed_at.desc())
        .all()
    )


def get_order_for_user(
    db: Session,
    user_id: uuid.UUID,
    order_id: uuid.UUID,
) -> Order | None:
    """Return one order only when it belongs to the requested user.

    Ownership is enforced directly in the query.

    There is intentionally no separate:
        fetch -> check user_id

    code path that could accidentally be skipped.
    """
    return (
        db.query(Order)
        .filter(
            Order.id == order_id,
            Order.user_id == user_id,
        )
        .first()
    )