"""Support-workspace helpers: summary, suggested reply, next action, context.

All text is derived deterministically from real stored data (messages,
classification, order/ticket records). Nothing is invented: when data is
missing the helper says so. The suggested reply is a DRAFT for a human agent
and is never sent automatically.
"""
from __future__ import annotations

import re
from sqlalchemy.orm import Session

from app.db.models import Order, Ticket, Conversation, ConversationCitation, User
from app.security.pii import redact_pii

_ORDER_RE = re.compile(r"ORD-?\s?\d{3,5}", re.I)


def _clip(text: str, n: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def order_ids_in(conversation: Conversation) -> list[str]:
    seen: list[str] = []
    for m in conversation.messages:
        for hit in _ORDER_RE.findall(m.content or ""):
            norm = re.sub(r"\s", "", hit).upper()
            if not norm.startswith("ORD-"):
                norm = "ORD-" + norm[3:].lstrip("-")
            if norm not in seen:
                seen.append(norm)
    return seen


def related_orders(db: Session, conversation: Conversation) -> list[dict]:
    ids = order_ids_in(conversation)
    q = db.query(Order).filter(Order.user_id == conversation.user_id)
    rows = q.filter(Order.order_number.in_(ids)).all() if ids else []
    return [{"order_number": o.order_number, "status": o.status, "carrier": o.carrier,
             "estimated_delivery": o.estimated_delivery.isoformat() if o.estimated_delivery else None,
             "items": [i.product_name for i in o.items][:5]} for o in rows]


def related_tickets(db: Session, conversation: Conversation) -> list[dict]:
    rows = (db.query(Ticket).filter(Ticket.user_id == conversation.user_id)
            .order_by(Ticket.created_at.desc()).limit(10).all())
    return [{"id": str(t.id), "ticket_number": t.ticket_number, "status": t.status, "priority": t.priority,
             "subject": t.subject, "this_conversation": t.source_conversation_id == conversation.id} for t in rows]


def customer_context(db: Session, conversation: Conversation) -> dict:
    u = db.get(User, conversation.user_id) if conversation.user_id else None
    n_conv = db.query(Conversation).filter(Conversation.user_id == conversation.user_id).count()
    n_open = db.query(Ticket).filter(Ticket.user_id == conversation.user_id,
                                     Ticket.status.notin_(["resolved", "closed"])).count()
    return {"customer_id": str(u.id) if u else None, "name": u.full_name if u else None,
            "conversations": n_conv, "open_tickets": n_open}


def summarize(conversation: Conversation, cls, orders: list[dict]) -> str:
    users = [m for m in conversation.messages if m.role == "user"]
    if not users:
        return "No customer messages yet."
    parts = [f"Customer asked: “{_clip(redact_pii(users[0].content), 140)}”."]
    if len(users) > 1:
        parts.append(f"{len(users)} customer messages in total; latest: “{_clip(redact_pii(users[-1].content), 120)}”.")
    if cls is not None:
        parts.append(f"Classified as {cls.intent.replace('_', ' ')} ({cls.topic}), sentiment {cls.sentiment}, priority {cls.priority}.")
    for o in orders[:2]:
        parts.append(f"Related order {o['order_number']} is {o['status']}.")
    last_ai = next((m for m in reversed(conversation.messages) if m.role == "assistant"), None)
    if last_ai and (last_ai.meta or {}).get("handoff"):
        parts.append("The AI recommended human follow-up.")
    return " ".join(parts)


def next_action(cls, orders: list[dict], tickets: list[dict], handoff: bool) -> str:
    open_here = [t for t in tickets if t["this_conversation"] and t["status"] not in ("resolved", "closed")]
    if cls is not None and cls.intent in {"order_delay", "shipping", "order_status"} and orders:
        return f"Verify shipment status for {orders[0]['order_number']} with the carrier and update the customer."
    if cls is not None and cls.intent in {"refund", "return", "payment"}:
        return "Review the applicable policy and the order record, then confirm the resolution with the customer."
    if handoff and not open_here:
        return "Create a ticket for this conversation and assign it to an agent."
    if open_here:
        return "Continue the open ticket and reply to the customer."
    return "Review the conversation and reply using the verified information shown."


def suggested_reply(conversation: Conversation, cls, orders: list[dict], sources: list[str]) -> dict:
    """Returns {"text", "basis"}. Only facts that exist in stored data are used."""
    name = None
    lines = ["Hi" + (f" {name}" if name else "") + ","]
    basis: list[str] = []
    if orders:
        o = orders[0]
        line = f"Thanks for reaching out about order {o['order_number']}. It is currently {o['status']}"
        if o.get("carrier"):
            line += f" with {o['carrier']}"
        if o.get("estimated_delivery"):
            line += f", with an estimated delivery of {o['estimated_delivery'][:10]}"
        lines.append(line + ".")
        basis.append("order record")
    else:
        lines.append("Thanks for reaching out — I'm looking into this for you now.")
    if sources:
        basis.append("knowledge base: " + ", ".join(sources[:3]))
    if cls is not None and cls.sentiment in {"frustrated", "angry", "negative"}:
        lines.insert(1, "I'm sorry for the trouble this has caused.")
    lines.append("I'll follow up here as soon as I have an update.")
    return {"text": "\n".join(lines), "basis": basis or ["conversation context only"]}


def timeline(conversation: Conversation, tickets: list[dict]) -> list[dict]:
    ev = [{"at": m.created_at, "type": f"message_{m.role}", "label": _clip(redact_pii(m.content), 90)} for m in conversation.messages]
    return sorted(ev, key=lambda e: e["at"])
