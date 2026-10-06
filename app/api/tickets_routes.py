from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import config
from app.auth.deps import get_current_user, require_roles
from app.security.rate_limit_deps import rate_limit_by_user
from app.api.web_schemas import (
    TicketCreateRequest,
    TicketDetailOut,
    TicketMessageCreateRequest,
    TicketMessageOut,
    TicketOut,
    TicketStatusUpdateRequest,
)
from app.db.base import get_db
from app.db.models import User
from app.notifications.service import create_notification
from app.services import ticket_service
from app.services.order_service import get_order_for_user
from app.phase4 import dispatch_webhook, get_current_org

router = APIRouter(prefix="/tickets", tags=["tickets"])


def _is_agent_or_admin(user: User) -> bool:
    return bool(user.role_names & {"support_agent", "admin", "super_admin"})


@router.get("", response_model=list[TicketOut])
def list_tickets(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[TicketOut]:
    # Customers see only their own; agents/admins see the full queue.
    if _is_agent_or_admin(user):
        return (
            db.query(ticket_service.Ticket)
            .order_by(ticket_service.Ticket.created_at.desc())
            .all()
        )

    return ticket_service.list_tickets_for_user(db, user.id)


@router.post(
    "",
    response_model=TicketOut,
    status_code=201,
    dependencies=[
        Depends(rate_limit_by_user("ticket_create", "RATE_LIMIT_TICKET_CREATE"))
    ],
)
def create_ticket(
    payload: TicketCreateRequest,
    user: User = Depends(get_current_user),
    org=Depends(get_current_org),
    db: Session = Depends(get_db),
) -> TicketOut:
    if payload.order_id is not None:
        # A customer can only attach a ticket to their OWN order --
        # checked the same ownership-scoped way as GET /orders/{id}.
        order = get_order_for_user(db, user.id, payload.order_id)

        if order is None:
            raise HTTPException(
                status_code=404,
                detail="Order not found.",
            )

    ticket = ticket_service.create_ticket(
        db,
        user_id=user.id,
        subject=payload.subject,
        description=payload.description,
        category=payload.category,
        priority=payload.priority,
        order_id=payload.order_id,
    )

    db.flush()

    create_notification(
        db,
        user_id=user.id,
        type="ticket_created",
        title=f"Ticket #{ticket.ticket_number} created",
        message=(
            f"We've received your request: "
            f"\u201c{payload.subject}\u201d. We'll follow up here."
        ),
        data={
            "ticket_id": str(ticket.id),
            "ticket_number": ticket.ticket_number,
        },
    )

    # Dispatch the Phase 4 webhook event after the ticket has been
    # created and flushed, but before the transaction is committed.
    #
    # The webhook payload intentionally contains only safe business
    # metadata. It does not expose passwords, API keys, webhook secrets,
    # JWTs, or the full SQLAlchemy model.
    dispatch_webhook(
        db,
        org.id,
        "ticket.created",
        {
            "ticket_id": str(ticket.id),
            "ticket_number": str(ticket.ticket_number),
            "user_id": str(user.id),
            "subject": ticket.subject,
            "category": ticket.category,
            "priority": ticket.priority,
            "status": ticket.status,
            "order_id": (
                str(ticket.order_id)
                if ticket.order_id is not None
                else None
            ),
            "created_at": (
                ticket.created_at.isoformat()
                if ticket.created_at is not None
                else None
            ),
        },
    )

    db.commit()
    db.refresh(ticket)

    return ticket


def _get_ticket_or_404(
    ticket_id: uuid.UUID,
    user: User,
    db: Session,
):
    if _is_agent_or_admin(user):
        ticket = ticket_service.get_ticket_any_owner(db, ticket_id)
    else:
        ticket = ticket_service.get_ticket_for_user(
            db,
            user.id,
            ticket_id,
        )

    if ticket is None:
        raise HTTPException(
            status_code=404,
            detail="Ticket not found.",
        )

    return ticket


@router.get(
    "/{ticket_id}",
    response_model=TicketDetailOut,
)
def get_ticket(
    ticket_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TicketDetailOut:
    return _get_ticket_or_404(
        ticket_id,
        user,
        db,
    )


@router.post(
    "/{ticket_id}/messages",
    response_model=TicketMessageOut,
    status_code=201,
)
def add_message(
    ticket_id: uuid.UUID,
    payload: TicketMessageCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> TicketMessageOut:
    ticket = _get_ticket_or_404(
        ticket_id,
        user,
        db,
    )

    role = (
        "support_agent"
        if _is_agent_or_admin(user)
        else "customer"
    )

    msg = ticket_service.add_ticket_message(
        db,
        ticket,
        author_id=user.id,
        author_role=role,
        content=payload.content,
    )

    db.commit()
    db.refresh(msg)

    return msg


@router.patch(
    "/{ticket_id}",
    response_model=TicketOut,
)
def update_ticket(
    ticket_id: uuid.UUID,
    payload: TicketStatusUpdateRequest,
    user: User = Depends(
        require_roles(
            "support_agent",
            "admin",
            "super_admin",
        )
    ),
    db: Session = Depends(get_db),
) -> TicketOut:
    ticket = ticket_service.get_ticket_any_owner(
        db,
        ticket_id,
    )

    if ticket is None:
        raise HTTPException(
            status_code=404,
            detail="Ticket not found.",
        )

    if (
        payload.assigned_agent_id is not None
        and payload.assigned_agent_id != ticket.assigned_agent_id
    ):
        agent = db.get(
            User,
            payload.assigned_agent_id,
        )

        if agent is None or not _is_agent_or_admin(agent):
            raise HTTPException(
                status_code=400,
                detail=(
                    "assigned_agent_id must be an existing "
                    "support agent or admin."
                ),
            )

        ticket.assigned_agent_id = agent.id

        create_notification(
            db,
            user_id=ticket.user_id,
            type="ticket_assigned",
            title=f"Ticket #{ticket.ticket_number} assigned",
            message=(
                f"{agent.full_name} is now looking into "
                "your request."
            ),
            data={
                "ticket_id": str(ticket.id),
                "ticket_number": str(ticket.ticket_number),
            },
        )

    if payload.priority is not None and payload.priority != ticket.priority:
        allowed_priorities = {"low", "medium", "high", "urgent"}
        if payload.priority not in allowed_priorities:
            raise HTTPException(
                status_code=400,
                detail="Invalid ticket priority.",
            )
        ticket.priority = payload.priority

    if (
        payload.status is not None
        and payload.status != ticket.status
    ):
        try:
            ticket_service.update_ticket_status(
                ticket,
                payload.status,
            )
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=str(e),
            )

        notif_type = (
            "ticket_resolved"
            if payload.status == "resolved"
            else "ticket_updated"
        )

        create_notification(
            db,
            user_id=ticket.user_id,
            type=notif_type,
            title=f"Ticket #{ticket.ticket_number} updated",
            message=(
                "Your ticket status changed to "
                f"\u201c{payload.status.replace('_', ' ')}\u201d."
            ),
            data={
                "ticket_id": str(ticket.id),
                "ticket_number": str(ticket.ticket_number),
                "status": payload.status,
            },
        )

    db.commit()
    db.refresh(ticket)

    return ticket