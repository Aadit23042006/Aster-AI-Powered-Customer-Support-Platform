from __future__ import annotations

import random
import uuid

from sqlalchemy.orm import Session

from app.db.models import Ticket, TicketMessage

_VALID_CATEGORIES = {
    "order_issue", "shipping", "return", "refund", "damaged_product",
    "product_question", "payment", "account", "other",
}
_VALID_PRIORITIES = {"low", "medium", "high", "urgent"}
_VALID_STATUSES = {"open", "in_progress", "waiting_for_customer", "resolved", "closed"}


def _generate_ticket_number(db: Session) -> str:
    for _ in range(10):
        candidate = f"AR-{random.randint(10000, 99999)}"
        if not db.query(Ticket).filter(Ticket.ticket_number == candidate).first():
            return candidate
    raise RuntimeError("Could not generate a unique ticket number.")


def create_ticket(
    db: Session,
    *,
    user_id: uuid.UUID,
    subject: str,
    description: str,
    category: str,
    priority: str = "medium",
    order_id: uuid.UUID | None = None,
    created_by_ai: bool = False,
    handoff_reason: str | None = None,
    source_conversation_id: uuid.UUID | None = None,
) -> Ticket:
    if category not in _VALID_CATEGORIES:
        category = "other"
    if priority not in _VALID_PRIORITIES:
        priority = "medium"

    ticket = Ticket(
        ticket_number=_generate_ticket_number(db),
        user_id=user_id,
        order_id=order_id,
        subject=subject[:200],
        description=description,
        category=category,
        priority=priority,
        created_by_ai=created_by_ai,
        handoff_reason=handoff_reason,
        source_conversation_id=source_conversation_id,
    )
    db.add(ticket)
    db.flush()
    db.add(
        TicketMessage(
            ticket_id=ticket.id,
            author_id=user_id,
            author_role="system" if created_by_ai else "customer",
            content=description,
        )
    )
    return ticket


def create_ticket_from_handoff(
    db: Session,
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    handoff_reason: str,
    last_user_message: str,
    order_id: uuid.UUID | None = None,
) -> Ticket:
    """Bridges the existing AI agent's deterministic handoff decision
    (`app.agent.Agent._apply_deterministic_handoff_rules`) into a real
    ticket. Called from the conversation route, never from inside
    `app/agent.py` itself, so the agent's core turn logic stays untouched --
    it only ever returns a `handoff: bool` + `handoff_reason: str`, exactly
    as it always has."""
    priority = "high" if order_id is not None else "medium"
    return create_ticket(
        db,
        user_id=user_id,
        subject=f"Support needed: {handoff_reason[:150]}",
        description=(
            f"Automatically opened by the AI assistant.\n\nReason: {handoff_reason}\n\n"
            f"Customer's last message: \"{last_user_message}\""
        ),
        category="order_issue" if order_id is not None else "other",
        priority=priority,
        order_id=order_id,
        created_by_ai=True,
        handoff_reason=handoff_reason,
        source_conversation_id=conversation_id,
    )


def list_tickets_for_user(db: Session, user_id: uuid.UUID) -> list[Ticket]:
    return db.query(Ticket).filter(Ticket.user_id == user_id).order_by(Ticket.created_at.desc()).all()


def get_ticket_for_user(db: Session, user_id: uuid.UUID, ticket_id: uuid.UUID) -> Ticket | None:
    return db.query(Ticket).filter(Ticket.id == ticket_id, Ticket.user_id == user_id).first()


def get_ticket_any_owner(db: Session, ticket_id: uuid.UUID) -> Ticket | None:
    """For support-agent/admin access, which is not owner-scoped but IS
    role-scoped (see `require_roles` in the routes)."""
    return db.query(Ticket).filter(Ticket.id == ticket_id).first()


def add_ticket_message(db: Session, ticket: Ticket, *, author_id: uuid.UUID, author_role: str, content: str) -> TicketMessage:
    msg = TicketMessage(ticket_id=ticket.id, author_id=author_id, author_role=author_role, content=content)
    db.add(msg)
    if author_role == "customer" and ticket.status == "waiting_for_customer":
        ticket.status = "in_progress"
    return msg


def update_ticket_status(ticket: Ticket, new_status: str) -> None:
    if new_status not in _VALID_STATUSES:
        raise ValueError(f"Invalid status: {new_status}")
    ticket.status = new_status
