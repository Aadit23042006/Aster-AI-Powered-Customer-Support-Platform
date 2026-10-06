from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, exists, func as f
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user, require_roles
from app.db.base import get_db
from app.db.models import (
    User,
    Conversation,
    Message,
    Ticket,
    AIAction,
    ConversationClassification,
    AIQualityCheck,
    ConversationCitation,
    InternalNote,
)
from app.enterprise import actions as _actions
from app.enterprise.actions import registry, execute
from app.enterprise.intelligence import classify_message
from app.enterprise.quality import assess
from app.enterprise.citations import build_citations
from app.services.audit_service import log_event
from app.services import ticket_service


router = APIRouter(tags=["enterprise-ai"])


# ============================================================
# ROLE DEPENDENCIES
# ============================================================

staff = Depends(
    require_roles(
        "support_agent",
        "admin",
        "super_admin",
    )
)

admin = Depends(
    require_roles(
        "admin",
        "super_admin",
    )
)


# ============================================================
# REQUEST MODELS
# ============================================================

class ActionRequest(BaseModel):
    tool_name: str
    arguments: dict = {}
    conversation_id: uuid.UUID | None = None


class NoteRequest(BaseModel):
    content: str = Field(
        min_length=1,
        max_length=5000,
    )


class AssignmentRequest(BaseModel):
    agent_id: uuid.UUID


class ActionRequest2(ActionRequest):
    idempotency_key: str | None = Field(
        default=None,
        max_length=80,
    )
    reason: str | None = Field(
        default=None,
        max_length=500,
    )


class RejectRequest(BaseModel):
    note: str | None = Field(
        default=None,
        max_length=500,
    )


# ============================================================
# ACTION CENTER HELPERS
# ============================================================

def _action_row(r, db=None):
    return {
        "id": str(r.id),
        "conversation_id": (
            str(r.conversation_id)
            if r.conversation_id
            else None
        ),
        "tool_name": r.tool_name,
        "category": r.category,
        "origin": r.origin,
        "reason": r.reason,
        "arguments": r.arguments_sanitized,
        "permission_result": r.permission_result,
        "approval_status": r.approval_status,
        "execution_status": r.execution_status,
        "result": r.result_sanitized,
        "risk_level": r.risk_level,
        "duration_ms": (
            float(r.duration_ms)
            if r.duration_ms is not None
            else None
        ),
        "error": r.error,
        "actor_id": (
            str(r.user_id)
            if r.user_id
            else None
        ),
        "approved_by": (
            str(r.approved_by)
            if r.approved_by
            else None
        ),
        "approved_at": r.approved_at,
        "ticket_id": (
            str(r.ticket_id)
            if r.ticket_id
            else None
        ),
        "order_number": r.order_number,
        "created_at": r.created_at,
    }


def _map_action_errors(fn):
    try:
        return fn()

    except _actions.ActionsDisabled as e:
        raise HTTPException(
            status_code=403,
            detail=str(e),
        )

    except PermissionError as e:
        raise HTTPException(
            status_code=403,
            detail=str(e),
        )

    except LookupError as e:
        raise HTTPException(
            status_code=404,
            detail=str(e),
        )

    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e),
        )


# ============================================================
# ACTION CENTER
# ============================================================

@router.get("/action-center/tools")
def tools(_: User = staff):
    return {
        "tools": registry()
    }


@router.post("/action-center/execute")
def execute_action(
    payload: ActionRequest2,
    user: User = staff,
    db: Session = Depends(get_db),
):
    return _map_action_errors(
        lambda: execute(
            db,
            user,
            payload.tool_name,
            payload.arguments,
            payload.conversation_id,
            origin="staff",
            idempotency_key=payload.idempotency_key,
            reason=payload.reason,
        )
    )


@router.get("/action-center/actions")
def list_actions(
    user: User = staff,
    db: Session = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    approval_status: str | None = None,
    tool_name: str | None = None,
):
    q = db.query(AIAction)

    if status:
        q = q.filter(
            AIAction.execution_status == status
        )

    if approval_status:
        q = q.filter(
            AIAction.approval_status == approval_status
        )

    if tool_name:
        q = q.filter(
            AIAction.tool_name == tool_name
        )

    rows = (
        q.order_by(AIAction.created_at.desc())
        .offset(max(offset, 0))
        .limit(min(max(limit, 1), 200))
        .all()
    )

    return [
        _action_row(r)
        for r in rows
    ]


@router.get("/action-center/actions/{action_id}")
def get_action(
    action_id: uuid.UUID,
    user: User = staff,
    db: Session = Depends(get_db),
):
    r = db.get(
        AIAction,
        action_id,
    )

    if not r:
        raise HTTPException(
            status_code=404,
            detail="Action not found",
        )

    return _action_row(r)


@router.post("/action-center/actions/{action_id}/approve")
def approve_action(
    action_id: uuid.UUID,
    user: User = staff,
    db: Session = Depends(get_db),
):
    return _map_action_errors(
        lambda: _actions.approve(
            db,
            user,
            action_id,
        )
    )


@router.post("/action-center/actions/{action_id}/reject")
def reject_action(
    action_id: uuid.UUID,
    payload: RejectRequest = RejectRequest(),
    user: User = staff,
    db: Session = Depends(get_db),
):
    return _map_action_errors(
        lambda: _actions.reject(
            db,
            user,
            action_id,
            payload.note,
        )
    )


# ============================================================
# SUPPORT WORKSPACE — CONVERSATIONS
# ============================================================

@router.get("/support-workspace/conversations")
def workspace_conversations(
    user: User = staff,
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Conversation)
        .order_by(Conversation.updated_at.desc())
        .limit(200)
        .all()
    )

    return [
        {
            "id": str(c.id),
            "title": c.title,
            "status": c.status,
            "updated_at": c.updated_at,
            "last_message": (
                c.messages[-1].content[:180]
                if c.messages
                else ""
            ),
        }
        for c in rows
    ]


@router.get("/support-workspace/conversations/{conversation_id}")
def workspace_detail(
    conversation_id: uuid.UUID,
    user: User = staff,
    db: Session = Depends(get_db),
):
    c = db.get(
        Conversation,
        conversation_id,
    )

    if not c:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found",
        )

    messages = [
        {
            "id": str(m.id),
            "role": m.role,
            "content": m.content,
            "meta": m.meta,
            "created_at": m.created_at,
        }
        for m in c.messages
    ]

    latest_user = next(
        (
            m
            for m in reversed(c.messages)
            if m.role == "user"
        ),
        None,
    )

    cls = (
        db.query(ConversationClassification)
        .filter_by(
            conversation_id=c.id
        )
        .order_by(
            ConversationClassification.created_at.desc()
        )
        .first()
    )

    quality = (
        db.query(AIQualityCheck)
        .filter_by(
            conversation_id=c.id
        )
        .order_by(
            AIQualityCheck.created_at.desc()
        )
        .first()
    )

    # --------------------------------------------------------
    # Build missing quality record for older conversations
    # --------------------------------------------------------

    if not quality and c.messages:
        am = next(
            (
                m
                for m in reversed(c.messages)
                if m.role == "assistant"
            ),
            None,
        )

        if am:
            qr = assess(
                am.content,
                (am.meta or {}).get("sources", []),
                (am.meta or {}).get("handoff", False),
            )

            quality = AIQualityCheck(
                conversation_id=c.id,
                message_id=am.id,
                grounding_score=qr.grounding_score,
                policy_check=qr.policy_check,
                pii_check=qr.pii_check,
                confidence=qr.confidence,
                decision=qr.decision,
            )

            db.add(quality)
            db.commit()

    # --------------------------------------------------------
    # Notes
    # --------------------------------------------------------

    notes = (
        db.query(InternalNote)
        .filter_by(
            conversation_id=c.id
        )
        .order_by(
            InternalNote.created_at.desc()
        )
        .all()
    )

    # --------------------------------------------------------
    # Tickets created directly from this conversation
    # --------------------------------------------------------

    tickets = (
        db.query(Ticket)
        .filter(
            Ticket.source_conversation_id == c.id
        )
        .order_by(
            Ticket.created_at.desc()
        )
        .all()
    )

    # --------------------------------------------------------
    # Workspace helpers
    # --------------------------------------------------------

    from app.enterprise import workspace as _ws

    orders = _ws.related_orders(
        db,
        c,
    )

    rel_tickets = _ws.related_tickets(
        db,
        c,
    )

    last_ai = next(
        (
            m
            for m in reversed(c.messages)
            if m.role == "assistant"
        ),
        None,
    )

    sources = (
        list(
            (last_ai.meta or {}).get("sources") or []
        )
        if last_ai
        else []
    )

    handoff = (
        bool(
            (last_ai.meta or {}).get("handoff")
        )
        if last_ai
        else False
    )

    draft = _ws.suggested_reply(
        c,
        cls,
        orders,
        sources,
    )

    suggestion = draft["text"]

    extra = {
        "summary": _ws.summarize(
            c,
            cls,
            orders,
        ),
        "next_action": _ws.next_action(
            cls,
            orders,
            rel_tickets,
            handoff,
        ),
        "suggested_reply_basis": draft["basis"],
        "customer": _ws.customer_context(
            db,
            c,
        ),
        "related_orders": orders,
        "related_tickets": rel_tickets,
        "timeline": _ws.timeline(
            c,
            rel_tickets,
        ),
        "sources": sources,
    }

    return {
        **extra,

        "conversation": {
            "id": str(c.id),
            "title": c.title,
            "status": c.status,
        },

        "messages": messages,

        "classification": (
            {
                "intent": cls.intent,
                "sentiment": cls.sentiment,
                "priority": cls.priority,
                "topic": cls.topic,
                "risk_level": cls.risk_level,
                "confidence": float(cls.confidence),
            }
            if cls
            else None
        ),

        "quality": (
            {
                "grounding_score": float(
                    quality.grounding_score
                ),
                "policy_check": quality.policy_check,
                "pii_check": quality.pii_check,
                "confidence": quality.confidence,
                "decision": quality.decision,
            }
            if quality
            else None
        ),

        "suggested_reply": suggestion,

        "tickets": [
            {
                "id": str(t.id),
                "ticket_number": t.ticket_number,
                "status": t.status,
                "priority": t.priority,
                "assigned_agent_id": (
                    str(t.assigned_agent_id)
                    if t.assigned_agent_id
                    else None
                ),
            }
            for t in tickets
        ],

        "internal_notes": [
            {
                "id": str(n.id),
                "content": n.content,
                "author_id": str(n.author_id),
                "created_at": n.created_at,
            }
            for n in notes
        ],
    }


# ============================================================
# SUPPORT WORKSPACE — INTERNAL NOTES
# ============================================================

@router.post(
    "/support-workspace/conversations/{conversation_id}/notes"
)
def add_note(
    conversation_id: uuid.UUID,
    payload: NoteRequest,
    user: User = staff,
    db: Session = Depends(get_db),
):
    c = db.get(
        Conversation,
        conversation_id,
    )

    if not c:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found",
        )

    n = InternalNote(
        conversation_id=c.id,
        author_id=user.id,
        content=payload.content,
    )

    db.add(n)

    log_event(
        db,
        event_type="internal_note_created",
        user=user,
        resource_type="conversation",
        resource_id=c.id,
        detail={
            "note_id": str(n.id)
        },
    )

    db.commit()
    db.refresh(n)

    return {
        "id": str(n.id),
        "content": n.content,
        "created_at": n.created_at,
    }


# ============================================================
# TICKET HELPERS
# ============================================================

def _ticket_or_404(
    db: Session,
    ticket_id: uuid.UUID,
):
    t = db.get(
        Ticket,
        ticket_id,
    )

    if not t:
        raise HTTPException(
            status_code=404,
            detail="Ticket not found",
        )

    return t


def _audit_both(
    db,
    user,
    legacy,
    new_name,
    ticket,
    detail=None,
):
    log_event(
        db,
        event_type=legacy,
        user=user,
        resource_type="ticket",
        resource_id=ticket.id,
        detail=detail,
    )

    log_event(
        db,
        event_type=new_name,
        user=user,
        resource_type="ticket",
        resource_id=ticket.id,
        detail=detail,
    )


# ============================================================
# SUPPORT WORKSPACE — ASSIGNMENT
# ============================================================

@router.post(
    "/support-workspace/tickets/{ticket_id}/assign"
)
def assign_ticket(
    ticket_id: uuid.UUID,
    payload: AssignmentRequest,
    user: User = staff,
    db: Session = Depends(get_db),
):
    ticket = _ticket_or_404(
        db,
        ticket_id,
    )

    agent = db.get(
        User,
        payload.agent_id,
    )

    if not agent or not (
        agent.role_names
        & {
            "support_agent",
            "admin",
            "super_admin",
        }
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid ticket or agent",
        )

    if ticket.status in (
        "resolved",
        "closed",
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Cannot assign a resolved or closed ticket"
            ),
        )

    previous = ticket.assigned_agent_id

    if previous == agent.id:
        return {
            "ticket_id": str(ticket.id),
            "assigned_agent_id": str(agent.id),
            "unchanged": True,
        }

    ticket.assigned_agent_id = agent.id

    if previous is None:
        _audit_both(
            db,
            user,
            "ticket_assigned",
            "TICKET_ASSIGNED",
            ticket,
            {
                "assigned_agent_id": str(agent.id)
            },
        )
    else:
        _audit_both(
            db,
            user,
            "ticket_assigned",
            "TICKET_REASSIGNED",
            ticket,
            {
                "assigned_agent_id": str(agent.id),
                "previous_agent_id": str(previous),
            },
        )

    db.commit()

    return {
        "ticket_id": str(ticket.id),
        "assigned_agent_id": str(agent.id),
        "previous_agent_id": (
            str(previous)
            if previous
            else None
        ),
        "reassigned": previous is not None,
    }


# ============================================================
# SUPPORT WORKSPACE — ESCALATE
# ============================================================

@router.post(
    "/support-workspace/tickets/{ticket_id}/escalate"
)
def escalate_ticket(
    ticket_id: uuid.UUID,
    user: User = staff,
    db: Session = Depends(get_db),
):
    ticket = _ticket_or_404(
        db,
        ticket_id,
    )

    if ticket.status in (
        "resolved",
        "closed",
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Cannot escalate a resolved or closed ticket"
            ),
        )

    ticket.status = "in_progress"
    ticket.priority = "high"

    _audit_both(
        db,
        user,
        "ticket_escalated",
        "TICKET_ESCALATED",
        ticket,
    )

    db.commit()

    return {
        "ticket_id": str(ticket.id),
        "status": ticket.status,
        "priority": ticket.priority,
    }


# ============================================================
# SUPPORT WORKSPACE — RESOLVE
# ============================================================

@router.post(
    "/support-workspace/tickets/{ticket_id}/resolve"
)
def resolve_ticket(
    ticket_id: uuid.UUID,
    user: User = staff,
    db: Session = Depends(get_db),
):
    ticket = _ticket_or_404(
        db,
        ticket_id,
    )

    if ticket.status in (
        "resolved",
        "closed",
    ):
        return {
            "ticket_id": str(ticket.id),
            "status": ticket.status,
            "unchanged": True,
        }

    ticket.status = "resolved"

    _audit_both(
        db,
        user,
        "ticket_resolved",
        "TICKET_RESOLVED",
        ticket,
    )

    db.commit()

    return {
        "ticket_id": str(ticket.id),
        "status": ticket.status,
    }


# ============================================================
# SUPPORT WORKSPACE — AGENTS
# ============================================================

@router.get("/support-workspace/agents")
def workspace_agents(
    user: User = staff,
    db: Session = Depends(get_db),
):
    return [
        {
            "id": str(u.id),
            "full_name": u.full_name,
            "roles": sorted(u.role_names),
        }
        for u in db.query(User).all()
        if u.role_names
        & {
            "support_agent",
            "admin",
            "super_admin",
        }
    ]


# ============================================================
# SUPPORT WORKSPACE — HUMAN REPLY
# ============================================================

@router.post(
    "/support-workspace/tickets/{ticket_id}/messages"
)
def workspace_reply(
    ticket_id: uuid.UUID,
    payload: NoteRequest,
    user: User = staff,
    db: Session = Depends(get_db),
):
    """
    Send a human-approved support reply.

    IMPORTANT:
    The reply is persisted in BOTH:

    1. Ticket message history
    2. Conversation message history

    The Support Workspace reads Conversation.messages.
    Therefore, saving only the TicketMessage causes the edited
    reply to disappear after a page refresh.
    """

    # --------------------------------------------------------
    # 1. Find ticket
    # --------------------------------------------------------

    ticket = db.get(
        Ticket,
        ticket_id,
    )

    if not ticket:
        raise HTTPException(
            status_code=404,
            detail="Ticket not found",
        )

    # --------------------------------------------------------
    # 2. Validate content
    # --------------------------------------------------------

    content = (payload.content or "").strip()

    if not content:
        raise HTTPException(
            status_code=400,
            detail="Reply content cannot be empty",
        )

    # --------------------------------------------------------
    # 3. Save reply to ticket message history
    # --------------------------------------------------------

    ticket_msg = ticket_service.add_ticket_message(
        db,
        ticket,
        author_id=user.id,
        author_role="support_agent",
        content=content,
    )

    # --------------------------------------------------------
    # 4. Find the conversation linked to this ticket
    # --------------------------------------------------------

    conversation = None

    if ticket.source_conversation_id:
        conversation = db.get(
            Conversation,
            ticket.source_conversation_id,
        )

    # --------------------------------------------------------
    # 5. HUMAN REPLY PERSISTENCE FIX
    #
    # Save the human-approved reply into Conversation.messages
    # so it remains visible after refreshing the Support Workspace.
    # --------------------------------------------------------

    conversation_msg = None

    if conversation:
        conversation_msg = Message(
            conversation_id=conversation.id,
            role="assistant",
            content=content,
            meta={
                "human_approved": True,
                "support_workspace": True,
                "ticket_id": str(ticket.id),
                "ticket_number": ticket.ticket_number,
                "author_id": str(user.id),
                "author_role": "support_agent",
            },
        )

        db.add(conversation_msg)

        # Update conversation ordering in the workspace list.
        conversation.updated_at = datetime.now(
            timezone.utc
        )

    # --------------------------------------------------------
    # 6. Keep ticket in progress
    # --------------------------------------------------------

    ticket.status = "in_progress"

    # --------------------------------------------------------
    # 7. Audit the human-approved reply
    # --------------------------------------------------------

    log_event(
        db,
        event_type="support_reply_sent",
        user=user,
        resource_type="ticket",
        resource_id=ticket.id,
        detail={
            "conversation_id": (
                str(conversation.id)
                if conversation
                else None
            ),
            "ticket_number": ticket.ticket_number,
            "human_approved": True,
            "conversation_persisted": (
                conversation is not None
            ),
        },
    )

    # --------------------------------------------------------
    # 8. Commit ticket + conversation changes together
    # --------------------------------------------------------

    db.commit()

    db.refresh(ticket_msg)

    if conversation_msg is not None:
        db.refresh(conversation_msg)

    # --------------------------------------------------------
    # 9. Return useful information to frontend
    # --------------------------------------------------------

    return {
        "id": str(ticket_msg.id),
        "content": ticket_msg.content,
        "created_at": ticket_msg.created_at,

        "ticket_id": str(ticket.id),
        "ticket_number": ticket.ticket_number,

        "conversation_id": (
            str(conversation.id)
            if conversation
            else None
        ),

        "conversation_message_id": (
            str(conversation_msg.id)
            if conversation_msg
            else None
        ),

        "conversation_persisted": (
            conversation is not None
            and conversation_msg is not None
        ),

        "human_approved": True,
    }


# ============================================================
# CONVERSATION INTELLIGENCE
# ============================================================

@router.get(
    "/conversations/{conversation_id}/intelligence"
)
def conversation_intelligence(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    c = db.get(
        Conversation,
        conversation_id,
    )

    if not c or (
        c.user_id != user.id
        and not (
            user.role_names
            & {
                "support_agent",
                "admin",
                "super_admin",
            }
        )
    ):
        raise HTTPException(
            status_code=404,
            detail="Conversation not found",
        )

    last = next(
        (
            m
            for m in reversed(c.messages)
            if m.role == "user"
        ),
        None,
    )

    if not last:
        return {
            "classification": None
        }

    cl = classify_message(
        last.content
    )

    row = (
        db.query(ConversationClassification)
        .filter_by(
            conversation_id=c.id
        )
        .order_by(
            ConversationClassification.created_at.desc()
        )
        .first()
    )

    if not row:
        row = ConversationClassification(
            conversation_id=c.id,
            intent=cl.intent,
            sentiment=cl.sentiment,
            priority=cl.priority,
            topic=cl.topic,
            risk_level=cl.risk_level,
            confidence=cl.confidence,
        )

        db.add(row)
        db.commit()

    return {
        "intent": row.intent,
        "sentiment": row.sentiment,
        "priority": row.priority,
        "topic": row.topic,
        "risk_level": row.risk_level,
        "confidence": float(row.confidence),
    }


# ============================================================
# CONVERSATION CITATIONS
# ============================================================

@router.get(
    "/conversations/{conversation_id}/citations"
)
def conversation_citations(
    conversation_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    c = db.get(
        Conversation,
        conversation_id,
    )

    if not c or (
        c.user_id != user.id
        and not (
            user.role_names
            & {
                "support_agent",
                "admin",
                "super_admin",
            }
        )
    ):
        raise HTTPException(
            status_code=404,
            detail="Conversation not found",
        )

    from app import config as _cfg

    if not _cfg.RAG_CITATIONS_ENABLED:
        return []

    if hasattr(
        ConversationCitation,
        "created_at",
    ):
        rows = (
            db.query(ConversationCitation)
            .filter_by(
                conversation_id=c.id
            )
            .order_by(
                ConversationCitation.created_at.asc()
            )
            .all()
        )
    else:
        rows = (
            db.query(ConversationCitation)
            .filter_by(
                conversation_id=c.id
            )
            .all()
        )

    if rows:
        return [
            {
                "id": r.citation_id,
                "document": r.document_name,
                "heading": r.heading,
                "passage": r.relevant_passage,
                "document_version": r.document_version,
                "source_type": r.source_type,
                "updated_at": r.updated_at,
                "relevance_score": (
                    float(r.relevance_score)
                    if r.relevance_score is not None
                    else None
                ),
            }
            for r in rows
        ]

    # --------------------------------------------------------
    # Older conversations:
    # rebuild citations only from sources that the stored
    # assistant answer actually reported.
    # --------------------------------------------------------

    last_user = next(
        (
            m
            for m in reversed(c.messages)
            if m.role == "user"
        ),
        None,
    )

    last_ai = next(
        (
            m
            for m in reversed(c.messages)
            if m.role == "assistant"
        ),
        None,
    )

    used = (
        (last_ai.meta or {}).get("sources")
        if last_ai
        else None
    )

    if not last_user or not used:
        return []

    from app.server import get_web_agent

    out = build_citations(
        get_web_agent().retriever.retrieve(
            last_user.content
        ),
        only_files=used,
    )

    for cdata in out:
        existing = (
            db.query(ConversationCitation)
            .filter_by(
                citation_id=cdata["id"],
                conversation_id=c.id,
            )
            .first()
        )

        if not existing:
            db.add(
                ConversationCitation(
                    conversation_id=c.id,
                    message_id=last_ai.id,
                    citation_id=cdata["id"],
                    document_name=cdata["document"],
                    document_version=cdata.get(
                        "document_version"
                    ),
                    heading=cdata.get("heading"),
                    source_type=cdata.get(
                        "source_type",
                        "knowledge_base",
                    ),
                    relevant_passage=cdata.get(
                        "passage"
                    ),
                    updated_at=cdata.get(
                        "updated_at"
                    ),
                    relevance_score=cdata.get(
                        "relevance_score"
                    ),
                )
            )

    db.commit()

    return out


@router.get(
    "/citations/{citation_id}"
)
def get_citation(
    citation_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = (
        db.query(ConversationCitation)
        .filter_by(
            citation_id=citation_id
        )
        .first()
    )

    if not row:
        raise HTTPException(
            status_code=404,
            detail="Citation not found",
        )

    if not (
        user.role_names
        & {
            "support_agent",
            "admin",
            "super_admin",
        }
    ):
        c = db.get(
            Conversation,
            row.conversation_id,
        )

        if not c or c.user_id != user.id:
            raise HTTPException(
                status_code=404,
                detail="Citation not found",
            )

    return {
        "id": row.citation_id,
        "document": row.document_name,
        "heading": row.heading,
        "passage": row.relevant_passage,
        "document_version": row.document_version,
        "updated_at": row.updated_at,
        "relevance_score": (
            float(row.relevance_score)
            if row.relevance_score is not None
            else None
        ),
    }


# ============================================================
# AI QUALITY
# ============================================================

@router.get(
    "/ai-quality/conversations/{conversation_id}"
)
def quality(
    conversation_id: uuid.UUID,
    user: User = staff,
    db: Session = Depends(get_db),
):
    c = db.get(
        Conversation,
        conversation_id,
    )

    if not c:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found",
        )

    m = next(
        (
            m
            for m in reversed(c.messages)
            if m.role == "assistant"
        ),
        None,
    )

    if not m:
        return {
            "decision": "NO_RESPONSE"
        }

    q = assess(
        m.content,
        (m.meta or {}).get("sources", []),
        (m.meta or {}).get("handoff", False),
    )

    row = (
        db.query(AIQualityCheck)
        .filter_by(
            message_id=m.id
        )
        .first()
    )

    if not row:
        row = AIQualityCheck(
            conversation_id=c.id,
            message_id=m.id,
            grounding_score=q.grounding_score,
            policy_check=q.policy_check,
            pii_check=q.pii_check,
            confidence=q.confidence,
            decision=q.decision,
        )

        db.add(row)
        db.commit()

    return {
        "grounding_score": q.grounding_score,
        "policy_check": q.policy_check,
        "pii_check": q.pii_check,
        "confidence": q.confidence,
        "decision": q.decision,
    }


# ============================================================
# ANALYTICS
# ============================================================

_ISSUE_MAP = {
    "shipping": "Shipping",
    "orders": "Shipping",
    "returns": "Returns",
    "payments": "Payments",
    "products": "Products",
    "account": "Account",
}

_NEGATIVE = {
    "negative",
    "frustrated",
    "angry",
}


@router.get(
    "/analytics/ai-intelligence"
)
def ai_analytics(
    user: User = staff,
    db: Session = Depends(get_db),
    date_from: str | None = None,
    date_to: str | None = None,
    sentiment: str | None = None,
    intent: str | None = None,
    priority: str | None = None,
    topic: str | None = None,
    agent: uuid.UUID | None = None,
    status: str | None = None,
):
    """
    Aggregates over each conversation's LATEST classification.

    History rows are never modified or removed;
    filters narrow the population.
    """

    from collections import Counter

    def _d(
        v,
        end=False,
    ):
        if not v:
            return None

        try:
            dt = datetime.fromisoformat(v)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Dates must be ISO formatted "
                    "(YYYY-MM-DD)."
                ),
            )

        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=timezone.utc
            )

        if end and len(v) == 10:
            dt = dt.replace(
                hour=23,
                minute=59,
                second=59,
            )

        return dt

    d_from = _d(date_from)
    d_to = _d(
        date_to,
        True,
    )

    latest = (
        db.query(
            ConversationClassification.conversation_id.label(
                "cid"
            ),
            f.max(
                ConversationClassification.created_at
            ).label("m"),
        )
        .group_by(
            ConversationClassification.conversation_id
        )
        .subquery()
    )

    q = (
        db.query(
            ConversationClassification,
            Conversation,
        )
        .join(
            latest,
            and_(
                ConversationClassification.conversation_id
                == latest.c.cid,
                ConversationClassification.created_at
                == latest.c.m,
            ),
        )
        .join(
            Conversation,
            Conversation.id
            == ConversationClassification.conversation_id,
        )
    )

    for col, val in (
        (
            ConversationClassification.sentiment,
            sentiment,
        ),
        (
            ConversationClassification.intent,
            intent,
        ),
        (
            ConversationClassification.priority,
            priority,
        ),
        (
            ConversationClassification.topic,
            topic,
        ),
    ):
        if val:
            q = q.filter(
                col == val
            )

    if d_from:
        q = q.filter(
            Conversation.created_at >= d_from
        )

    if d_to:
        q = q.filter(
            Conversation.created_at <= d_to
        )

    has_ticket = exists().where(
        Ticket.source_conversation_id
        == Conversation.id
    )

    if agent:
        q = q.filter(
            exists().where(
                and_(
                    Ticket.source_conversation_id
                    == Conversation.id,
                    Ticket.assigned_agent_id
                    == agent,
                )
            )
        )

    if status in {
        "active",
        "archived",
    }:
        q = q.filter(
            Conversation.status == status
        )

    elif status == "handed_off":
        q = q.filter(has_ticket)

    elif status == "ai_resolved":
        q = q.filter(~has_ticket)

    elif status:
        raise HTTPException(
            status_code=400,
            detail="Unsupported status filter.",
        )

    rows = q.all()

    conv_ids = [
        c.id
        for _, c in rows
    ]

    if conv_ids:
        handed = {
            r[0]
            for r in (
                db.query(
                    Ticket.source_conversation_id
                )
                .filter(
                    Ticket.source_conversation_id.in_(
                        conv_ids
                    )
                )
                .all()
            )
        }
    else:
        handed = set()

    cls = [
        r
        for r, _ in rows
    ]

    if conv_ids:
        acts = (
            db.query(AIAction)
            .filter(
                AIAction.conversation_id.in_(
                    conv_ids
                )
            )
            .all()
        )

        qs = (
            db.query(AIQualityCheck)
            .filter(
                AIQualityCheck.conversation_id.in_(
                    conv_ids
                )
            )
            .all()
        )
    else:
        acts = []
        qs = []

    issues = Counter(
        _ISSUE_MAP.get(
            c.topic,
            "Other",
        )
        for c in cls
    )

    order = [
        "Shipping",
        "Returns",
        "Payments",
        "Products",
        "Account",
        "Other",
    ]

    return {
        "filters": {
            "date_from": date_from,
            "date_to": date_to,
            "sentiment": sentiment,
            "intent": intent,
            "priority": priority,
            "topic": topic,
            "agent": (
                str(agent)
                if agent
                else None
            ),
            "status": status,
        },

        "conversations": len(rows),

        "ai_resolved": sum(
            1
            for _, c in rows
            if c.id not in handed
        ),

        "human_handoffs": sum(
            1
            for _, c in rows
            if c.id in handed
        ),

        "negative_sentiment": sum(
            1
            for c in cls
            if c.sentiment in _NEGATIVE
        ),

        "high_priority": sum(
            1
            for c in cls
            if c.priority
            in {
                "high",
                "urgent",
            }
        ),

        "top_issues": [
            {
                "issue": k,
                "count": issues.get(k, 0),
            }
            for k in order
        ],

        "average_confidence": (
            sum(
                float(c.confidence)
                for c in cls
            )
            / len(cls)
            if cls
            else None
        ),

        "top_intents": (
            Counter(
                c.intent
                for c in cls
            ).most_common(10)
        ),

        "top_topics": (
            Counter(
                c.topic
                for c in cls
            ).most_common(10)
        ),

        "sentiment_distribution": Counter(
            c.sentiment
            for c in cls
        ),

        "tool_calls": len(acts),

        "successful_tool_calls": sum(
            1
            for a in acts
            if a.execution_status == "success"
        ),

        "failed_tool_calls": sum(
            1
            for a in acts
            if a.execution_status == "failed"
        ),

        "quality_decisions": Counter(
            q.decision
            for q in qs
        ),

        "average_grounding": (
            sum(
                float(q.grounding_score)
                for q in qs
            )
            / len(qs)
            if qs
            else None
        ),
    }