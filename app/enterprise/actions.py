"""AI tool registry + safe execution.

Pipeline:

    permission check
        -> idempotency check
        -> approval check
        -> execute
        -> validate/sanitise
        -> audit

Security model:

* Staff-initiated Action Center operations require the normal tool
  permission and execute immediately.

* AI-originated read-only operations require the normal permission unless
  they use the narrowly scoped internal read-only audit path.

* Customer-owned AI read-only lookups may be internally audited without
  giving the customer staff-level Action Center permissions. The actual
  resource lookup remains ownership-scoped by the tool implementation.

* AI-originated mutating/external operations may be proposed by an
  authenticated customer even when that customer does not have the
  corresponding staff mutation permission.

* Customer AI mutation proposals NEVER execute immediately when human
  approval is enabled. They are stored as:
      execution_status = "approval_required"
      approval_status = "pending"

* A support/admin reviewer must have the normal tool permission before
  approving and executing the action.

* Approval execution uses the reviewer as the authorized actor and the
  original customer's user_id as the subject of the action.

* Customer roles are NOT granted staff-level permissions such as
  tickets.update merely to allow AI proposals.

* Idempotency prevents duplicate mutation proposals/executions.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app import config
from app.db.models import AIAction, Order, Ticket, User
from app.security.pii import redact_pii
from app.services import ticket_service
from app.services.audit_service import log_event
from app.services.order_service import _order_to_safe_dict


READ_ONLY, MUTATING, EXTERNAL = (
    "read_only",
    "mutating",
    "external",
)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    permission: str
    risk_level: str
    category: str = READ_ONLY


# ---------------------------------------------------------------------------
# Action Center tool registry
# ---------------------------------------------------------------------------

TOOLS = {
    spec.name: spec
    for spec in [
        ToolSpec(
            "lookup_order",
            "Look up the authenticated customer's order",
            "orders.read",
            "LOW",
            READ_ONLY,
        ),
        ToolSpec(
            "check_shipment_status",
            "Check shipment/delay status of the customer's order",
            "orders.read",
            "LOW",
            READ_ONLY,
        ),
        ToolSpec(
            "get_ticket",
            "Read a support ticket",
            "tickets.read",
            "LOW",
            READ_ONLY,
        ),
        ToolSpec(
            "create_support_ticket",
            "Create a support ticket",
            "tickets.create",
            "MEDIUM",
            MUTATING,
        ),
        ToolSpec(
            "add_ticket_message",
            "Add a message to a ticket",
            "tickets.update",
            "MEDIUM",
            MUTATING,
        ),
        ToolSpec(
            "assign_ticket",
            "Assign a ticket to a support agent",
            "tickets.assign",
            "MEDIUM",
            MUTATING,
        ),
        ToolSpec(
            "reassign_ticket",
            "Reassign a ticket",
            "tickets.assign",
            "MEDIUM",
            MUTATING,
        ),
        ToolSpec(
            "escalate_ticket",
            "Escalate a ticket",
            "tickets.update",
            "MEDIUM",
            MUTATING,
        ),
        ToolSpec(
            "resolve_ticket",
            "Resolve a ticket",
            "tickets.close",
            "MEDIUM",
            MUTATING,
        ),
        ToolSpec(
            "notify_customer",
            "Send an in-app notification to the ticket owner",
            "tickets.update",
            "MEDIUM",
            MUTATING,
        ),
    ]
}


# NOTE:
# No EXTERNAL tools (email / third-party) are registered yet.
#
# Any future tool declared with category=EXTERNAL automatically receives
# the same AI human-approval gate used for mutating actions.


# ---------------------------------------------------------------------------
# Public registry
# ---------------------------------------------------------------------------

def registry():
    """Return the public Action Center tool registry."""
    return [
        spec.__dict__
        for spec in TOOLS.values()
    ]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ActionsDisabled(PermissionError):
    """Raised when AI agent actions are disabled by configuration."""

    pass


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _uuid(value) -> uuid.UUID:
    """Convert a value to UUID."""
    return uuid.UUID(str(value))


def idempotency_key_for(
    user_id,
    name: str,
    args: dict,
    conversation_id,
) -> str:
    """Build a stable idempotency key for an action invocation."""

    raw = json.dumps(
        {
            "u": str(user_id),
            "t": name,
            "a": args,
            "c": (
                str(conversation_id)
                if conversation_id
                else None
            ),
        },
        sort_keys=True,
        default=str,
    )

    return hashlib.sha256(
        raw.encode()
    ).hexdigest()[:40]


def _out(
    row: AIAction,
    *,
    duplicate: bool = False,
    result=None,
) -> dict:
    """Return the safe public representation of an AI action."""

    return {
        "action_id": str(row.id),
        "tool": row.tool_name,
        "status": row.execution_status,
        "approval_status": row.approval_status,
        "category": row.category,
        "origin": row.origin,
        "result": (
            result
            if result is not None
            else (row.result_sanitized or {})
        ),
        "duration_ms": (
            round(float(row.duration_ms), 2)
            if row.duration_ms is not None
            else None
        ),
        "risk_level": row.risk_level,
        "duplicate": duplicate,
    }


# ---------------------------------------------------------------------------
# Actual tool execution
# ---------------------------------------------------------------------------

def _run_tool(
    db: Session,
    actor: User,
    subject_id,
    name: str,
    args: dict,
    conversation_id=None,
) -> dict:
    """Run the actual Action Center tool.

    Parameters
    ----------
    actor:
        The user actually authorized to perform the operation.

        For staff approval this is the reviewer.

    subject_id:
        The customer/resource owner the operation applies to.

        For an approved customer AI action this is the original customer's
        user_id stored on AIAction.user_id.

    conversation_id:
        The originating conversation for conversation-aware actions.

    Security
    --------
    Read-only customer order operations are explicitly scoped to subject_id.

    This means that allowing an authenticated customer's AI agent to create
    an internal read-only audit record does NOT allow the customer to access
    another customer's order.
    """

    # ------------------------------------------------------------------
    # ORDER LOOKUP
    # ------------------------------------------------------------------

    if name == "lookup_order":
        from app.orders import normalize_order_id

        normalized_order_id = normalize_order_id(
            str(args.get("order_id", ""))
        )

        order = (
            db.query(Order)
            .filter(
                Order.order_number == normalized_order_id,
                Order.user_id == subject_id,
            )
            .first()
        )

        result = {
            "found": bool(order),
        }

        if order:
            result.update(
                _order_to_safe_dict(order)
            )

        return result

    # ------------------------------------------------------------------
    # SHIPMENT STATUS
    # ------------------------------------------------------------------

    if name == "check_shipment_status":
        from app.orders import normalize_order_id

        normalized_order_id = normalize_order_id(
            str(args.get("order_id", ""))
        )

        order = (
            db.query(Order)
            .filter(
                Order.order_number == normalized_order_id,
                Order.user_id == subject_id,
            )
            .first()
        )

        if not order:
            return {
                "found": False,
            }

        estimated_delivery = order.estimated_delivery

        now = datetime.now(timezone.utc)

        if (
            estimated_delivery is not None
            and estimated_delivery.tzinfo is None
        ):
            estimated_delivery = (
                estimated_delivery.replace(
                    tzinfo=timezone.utc
                )
            )

        delivered = (
            order.delivered_at is not None
            or (order.status or "").lower()
            == "delivered"
        )

        # Delay is derived only from real order data.
        #
        # If no estimate exists, delay status is unknown.
        delayed = (
            None
            if estimated_delivery is None
            else (
                not delivered
                and estimated_delivery < now
            )
        )

        return {
            "found": True,
            "order_id": order.order_number,
            "status": order.status,
            "carrier": order.carrier,
            "tracking_number": order.tracking_number,
            "estimated_delivery": (
                estimated_delivery.isoformat()
                if estimated_delivery
                else None
            ),
            "delayed": delayed,
        }

    # ------------------------------------------------------------------
    # TICKET LOOKUP / OPERATIONS
    # ------------------------------------------------------------------

    ticket = None

    if name in {
        "get_ticket",
        "add_ticket_message",
        "assign_ticket",
        "reassign_ticket",
        "escalate_ticket",
        "resolve_ticket",
        "notify_customer",
    }:
        ticket_id = args.get("ticket_id")

        if not ticket_id:
            raise ValueError(
                "ticket_id is required"
            )

        ticket = (
            db.query(Ticket)
            .filter(
                Ticket.id == _uuid(ticket_id)
            )
            .first()
        )

        if not ticket:
            raise ValueError(
                "Ticket not found"
            )

    # ------------------------------------------------------------------
    # GET TICKET
    # ------------------------------------------------------------------

    if name == "get_ticket":

        # Customers may read only their own tickets.
        #
        # Staff users with tickets.read may read other customers' tickets.
        if (
            ticket.user_id != actor.id
            and "tickets.read"
            not in actor.permission_names
        ):
            raise ValueError(
                "Ticket not found"
            )

        return {
            "id": str(ticket.id),
            "ticket_number": ticket.ticket_number,
            "status": ticket.status,
            "priority": ticket.priority,
            "subject": ticket.subject,
        }

    # ------------------------------------------------------------------
    # CREATE SUPPORT TICKET
    # ------------------------------------------------------------------

    if name == "create_support_ticket":

        created_ticket = ticket_service.create_ticket(
            db,
            user_id=subject_id,
            subject=str(
                args.get(
                    "subject",
                    "Support request",
                )
            ),
            description=str(
                args.get(
                    "description",
                    "",
                )
            ),
            category=str(
                args.get(
                    "category",
                    "other",
                )
            ),
            priority=str(
                args.get(
                    "priority",
                    "medium",
                )
            ),

            # IMPORTANT:
            # Preserve the originating conversation so the Support
            # Workspace can identify the ticket as belonging directly
            # to this conversation.
            source_conversation_id=conversation_id,
        )

        return {
            "ticket_id": str(
                created_ticket.id
            ),
            "ticket_number": (
                created_ticket.ticket_number
            ),
            "status": created_ticket.status,
        }

    # ------------------------------------------------------------------
    # ADD TICKET MESSAGE
    # ------------------------------------------------------------------

    if name == "add_ticket_message":

        message = ticket_service.add_ticket_message(
            db,
            ticket,
            author_id=actor.id,
            author_role="support_agent",
            content=str(
                args["content"]
            ),
        )

        return {
            "message_id": str(
                message.id
            ),
        }

    # ------------------------------------------------------------------
    # ASSIGN / REASSIGN
    # ------------------------------------------------------------------

    if name in {
        "assign_ticket",
        "reassign_ticket",
    }:

        agent_id = args.get("agent_id")

        if not agent_id:
            raise ValueError(
                "agent_id is required"
            )

        agent = (
            db.query(User)
            .filter(
                User.id == _uuid(agent_id)
            )
            .first()
        )

        if not agent or not (
            agent.role_names
            & {
                "support_agent",
                "admin",
                "super_admin",
            }
        ):
            raise ValueError(
                "Invalid ticket or agent"
            )

        ticket.assigned_agent_id = agent.id

        return {
            "ticket_id": str(
                ticket.id
            ),
            "assigned_agent_id": str(
                agent.id
            ),
        }

    # ------------------------------------------------------------------
    # ESCALATE
    # ------------------------------------------------------------------

    if name == "escalate_ticket":

        # Escalation is intentionally performed only when _run_tool()
        # is reached.
        #
        # AI customer proposals never reach this code until a reviewer
        # approves the Action Center action.
        ticket.status = "in_progress"
        ticket.priority = "high"

        return {
            "ticket_id": str(
                ticket.id
            ),
            "status": ticket.status,
            "priority": ticket.priority,
        }

    # ------------------------------------------------------------------
    # RESOLVE
    # ------------------------------------------------------------------

    if name == "resolve_ticket":

        ticket.status = "resolved"

        return {
            "ticket_id": str(
                ticket.id
            ),
            "status": ticket.status,
        }

    # ------------------------------------------------------------------
    # NOTIFY CUSTOMER
    # ------------------------------------------------------------------

    if name == "notify_customer":
        from app.notifications.service import (
            create_notification,
        )

        create_notification(
            db,
            user_id=ticket.user_id,
            type="ticket_updated",
            send_email=False,
            title=str(
                args.get(
                    "title",
                    "Update on your support request",
                )
            )[:200],
            message=str(
                args.get(
                    "message",
                    "",
                )
            )[:1000],
            data={
                "ticket_id": str(
                    ticket.id
                ),
                "ticket_number": (
                    ticket.ticket_number
                ),
            },
        )

        return {
            "ticket_id": str(
                ticket.id
            ),
            "notified": True,
        }

    raise ValueError(
        "Unknown tool"
    )


# ---------------------------------------------------------------------------
# Action execution
# ---------------------------------------------------------------------------

def _execute_row(
    db: Session,
    row: AIAction,
    actor: User,
    subject_id,
    spec: ToolSpec,
    args: dict,
) -> AIAction:
    """Execute a previously authorized action row."""

    start = time.perf_counter()

    status = "success"
    error = None
    result = {}

    try:
        with db.begin_nested():
            # A failing tool never poisons the surrounding transaction.
            result = _run_tool(
                db,
                actor,
                subject_id,
                spec.name,
                args,
                conversation_id=row.conversation_id,
            )

    except Exception as exc:  # noqa: BLE001
        # Tool failures must not crash the conversation.
        status = "failed"
        error = str(exc)[:500]
        result = {}

    row.execution_status = status
    row.error = error
    row.result_sanitized = redact_pii(
        result
    )

    row.duration_ms = (
        time.perf_counter() - start
    ) * 1000

    if result.get("ticket_id"):
        row.ticket_id = _uuid(
            result["ticket_id"]
        )

    if result.get("order_id"):
        row.order_number = (
            result["order_id"]
        )

    log_event(
        db,
        event_type=(
            "AI_TOOL_EXECUTED"
            if status == "success"
            else "AI_TOOL_FAILED"
        ),
        user=actor,
        resource_type="ai_action",
        resource_id=str(row.id),
        detail={
            "tool_name": spec.name,
            "status": status,
            "category": spec.category,
            "risk_level": spec.risk_level,
            "origin": row.origin,
        },
        success=status == "success",
    )

    return row


# ---------------------------------------------------------------------------
# Execute / propose action
# ---------------------------------------------------------------------------

def execute(
    db: Session,
    user: User,
    name: str,
    args: dict,
    conversation_id=None,
    *,
    origin: str = "staff",
    idempotency_key: str | None = None,
    reason: str | None = None,
    commit: bool = True,
    internal_read_audit: bool = False,
) -> dict:
    """Authorize, optionally approve, and execute an Action Center tool.

    Normal staff behavior:

        permission check
            -> idempotency check
            -> approval check
            -> execute
            -> audit

    AI read-only behavior:

        authenticated customer
            -> optional internal audit bypass
            -> ownership-scoped read
            -> audit

    AI mutating behavior:

        authenticated customer
            -> AI proposal authorization
            -> idempotency check
            -> approval_required
            -> Action Center
            -> human approval
            -> execution by reviewer

    Important:
        The AI proposal authorization does NOT give the customer the
        underlying staff permission.

        For example, a customer does not receive ``tickets.update`` merely
        because the AI is allowed to propose ``escalate_ticket``.

        The actual mutation occurs only after an authorized reviewer calls
        approve().
    """

    # ------------------------------------------------------------------
    # Resolve tool
    # ------------------------------------------------------------------

    spec = TOOLS.get(name)

    if not spec:
        raise ValueError(
            "Unknown tool"
        )

    # ------------------------------------------------------------------
    # Global feature flag
    # ------------------------------------------------------------------

    if not config.AI_AGENT_ACTIONS_ENABLED:
        raise ActionsDisabled(
            "AI agent actions are disabled"
        )

    # ------------------------------------------------------------------
    # Authorization modes
    # ------------------------------------------------------------------

    # Customer AI read-only audit path.
    #
    # This is intentionally narrow and does not grant Action Center UI
    # permissions or staff permissions.
    permission_bypassed_for_internal_audit = (
        internal_read_audit
        and origin == "ai"
        and spec.category == READ_ONLY
    )

    # Customer AI mutation proposal path.
    #
    # This allows the AI to CREATE A PROPOSAL for human review.
    #
    # It does NOT allow execution.
    #
    # Execution is prevented by the approval gate below as long as
    # AI_ACTION_APPROVAL_REQUIRED=true.
    permission_bypassed_for_ai_proposal = (
        origin == "ai"
        and spec.category != READ_ONLY
        and config.AI_ACTION_APPROVAL_REQUIRED
    )

    # ------------------------------------------------------------------
    # Normal permission check
    # ------------------------------------------------------------------

    if not (
        permission_bypassed_for_internal_audit
        or permission_bypassed_for_ai_proposal
    ):
        if spec.permission not in user.permission_names:

            denied_row = AIAction(
                conversation_id=conversation_id,
                user_id=user.id,
                tool_name=name,
                arguments_sanitized=redact_pii(
                    args
                ),
                permission_result="DENIED",
                execution_status="denied",
                risk_level=spec.risk_level,
                error="Insufficient permissions",
                category=spec.category,
                origin=origin,
                approval_status="not_required",
            )

            db.add(denied_row)

            log_event(
                db,
                event_type="ai_action_denied",
                user=user,
                resource_type="ai_action",
                detail={
                    "tool_name": name,
                    "arguments": args,
                },
                success=False,
            )

            if commit:
                db.commit()
            else:
                db.flush()

            raise PermissionError(
                "Insufficient permissions"
            )

    # ------------------------------------------------------------------
    # Idempotency
    # ------------------------------------------------------------------

    key = (
        idempotency_key
        or idempotency_key_for(
            user.id,
            name,
            args,
            conversation_id,
        )
    )

    prior = (
        db.query(AIAction)
        .filter(
            AIAction.idempotency_key == key,
            AIAction.user_id == user.id,
            AIAction.execution_status.in_(
                [
                    "success",
                    "approval_required",
                ]
            ),
        )
        .order_by(
            AIAction.created_at.desc()
        )
        .first()
    )

    # Never execute or propose the same mutation twice.
    if (
        prior is not None
        and spec.category != READ_ONLY
    ):
        return _out(
            prior,
            duplicate=True,
        )

    # ------------------------------------------------------------------
    # Approval gate
    # ------------------------------------------------------------------

    # Only AI-originated mutating/external actions are subject to the
    # human approval requirement.
    #
    # Read-only actions never require approval.
    #
    # Staff-originated actions remain human-authorized and execute directly.
    needs_approval = (
        spec.category != READ_ONLY
        and origin == "ai"
        and config.AI_ACTION_APPROVAL_REQUIRED
    )

    # ------------------------------------------------------------------
    # Create Action Center audit row
    # ------------------------------------------------------------------

    action_row = AIAction(
        conversation_id=conversation_id,
        user_id=user.id,
        tool_name=name,
        arguments_sanitized=redact_pii(
            args
        ),
        permission_result="ALLOWED",
        execution_status="pending",
        risk_level=spec.risk_level,
        category=spec.category,
        origin=origin,
        reason=reason,
        idempotency_key=key,
        approval_status=(
            "pending"
            if needs_approval
            else "not_required"
        ),
        order_number=(
            str(
                args["order_id"]
            )[:50]
            if args.get("order_id")
            else None
        ),
        ticket_id=(
            _uuid(
                args["ticket_id"]
            )
            if args.get("ticket_id")
            else None
        ),
    )

    db.add(action_row)
    db.flush()

    # ------------------------------------------------------------------
    # Human approval required
    # ------------------------------------------------------------------

    if needs_approval:

        action_row.execution_status = (
            "approval_required"
        )

        log_event(
            db,
            event_type="AI_TOOL_APPROVAL_REQUIRED",
            user=user,
            resource_type="ai_action",
            resource_id=str(
                action_row.id
            ),
            detail={
                "tool_name": name,
                "category": spec.category,
                "risk_level": spec.risk_level,
                "origin": origin,
            },
        )

        if commit:
            db.commit()
        else:
            db.flush()

        return _out(
            action_row
        )

    # ------------------------------------------------------------------
    # Immediate execution
    # ------------------------------------------------------------------
    #
    # This path is used for:
    #
    # 1. Staff-originated actions.
    # 2. Read-only actions.
    #
    # AI-originated mutations should not normally reach this path when
    # AI_ACTION_APPROVAL_REQUIRED=true.
    # ------------------------------------------------------------------

    _execute_row(
        db,
        action_row,
        user,
        user.id,
        spec,
        args,
    )

    if commit:
        db.commit()
    else:
        db.flush()

    return _out(
        action_row
    )


# ---------------------------------------------------------------------------
# Pending approval loader
# ---------------------------------------------------------------------------

def _load_pending(
    db: Session,
    reviewer: User,
    action_id,
) -> tuple[AIAction, ToolSpec]:
    """Load and validate an action awaiting human approval."""

    action_row = (
        db.query(AIAction)
        .filter(
            AIAction.id
            == _uuid(action_id)
        )
        .with_for_update()
        .first()
    )

    if not action_row:
        raise LookupError(
            "Action not found"
        )

    spec = TOOLS.get(
        action_row.tool_name
    )

    if not spec:
        raise ValueError(
            "Unknown tool"
        )

    # IMPORTANT:
    #
    # Approval always requires the normal tool permission.
    #
    # This is what prevents a customer from approving their own AI action.
    if (
        spec.permission
        not in reviewer.permission_names
    ):
        raise PermissionError(
            "Insufficient permissions"
        )

    if (
        action_row.approval_status
        != "pending"
        or action_row.execution_status
        != "approval_required"
    ):
        raise ValueError(
            "Action is not awaiting approval"
        )

    return (
        action_row,
        spec,
    )


# ---------------------------------------------------------------------------
# Approve
# ---------------------------------------------------------------------------

def approve(
    db: Session,
    reviewer: User,
    action_id,
) -> dict:
    """Approve and execute a pending AI action.

    The reviewer is the authorized actor.

    The original customer stored in AIAction.user_id remains the subject.
    """

    action_row, spec = _load_pending(
        db,
        reviewer,
        action_id,
    )

    action_row.approval_status = (
        "approved"
    )

    action_row.approved_by = (
        reviewer.id
    )

    action_row.approved_at = (
        datetime.now(timezone.utc)
    )

    log_event(
        db,
        event_type="AI_TOOL_APPROVED",
        user=reviewer,
        resource_type="ai_action",
        resource_id=str(
            action_row.id
        ),
        detail={
            "tool_name": spec.name,
            "original_customer_id": str(
                action_row.user_id
            ),
        },
    )

    # ------------------------------------------------------------------
    # Execute using reviewer as actor
    # and original customer as subject.
    # ------------------------------------------------------------------

    _execute_row(
        db,
        action_row,
        reviewer,
        action_row.user_id,
        spec,
        action_row.arguments_sanitized
        or {},
    )

    db.commit()

    return _out(
        action_row
    )


# ---------------------------------------------------------------------------
# Reject
# ---------------------------------------------------------------------------

def reject(
    db: Session,
    reviewer: User,
    action_id,
    note: str | None = None,
) -> dict:
    """Reject a pending AI action.

    Rejection never executes the underlying tool.
    """

    action_row, spec = _load_pending(
        db,
        reviewer,
        action_id,
    )

    action_row.approval_status = (
        "rejected"
    )

    action_row.approved_by = (
        reviewer.id
    )

    action_row.approved_at = (
        datetime.now(timezone.utc)
    )

    action_row.execution_status = (
        "rejected"
    )

    action_row.error = (
        note
        or "Rejected by reviewer"
    )[:500]

    log_event(
        db,
        event_type="AI_TOOL_REJECTED",
        user=reviewer,
        resource_type="ai_action",
        resource_id=str(
            action_row.id
        ),
        detail={
            "tool_name": spec.name,
            "original_customer_id": str(
                action_row.user_id
            ),
        },
    )

    db.commit()

    return _out(
        action_row
    )