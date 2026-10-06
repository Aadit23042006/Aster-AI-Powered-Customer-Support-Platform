"""Centralized audit logging (Phase 3, Feature 21).

Extends the existing `AuditEvent` table (originally added in Phase 1 for
login/signup events) rather than creating a second, competing audit
system. Every call goes through `log_event()` here so:

1. PII/secrets never reach `detail` -- run through
   `app.security.pii.redact_pii` before being written.
2. The richer Phase 3 fields (actor_role, resource_type/id, ip_address,
   user_agent, success, request_id) get filled in consistently, instead of
   each call site remembering to set them itself.
"""
from __future__ import annotations

import uuid

from fastapi import Request
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.db.models import AuditEvent, User
from app.security.net import client_ip
from app.security.pii import redact_pii


def log_event(
    db: Session,
    *,
    event_type: str,
    user: User | None = None,
    user_id: uuid.UUID | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    success: bool = True,
    detail: dict | None = None,
    request: Request | None = None,
) -> AuditEvent:
    """Queues an AuditEvent row (caller still owns the commit, same as the
    rest of this codebase's service-layer functions -- see
    app/services/conversation_service.py for the same pattern) so one
    request's audit write shares a transaction with the action it's
    logging: if the action rolls back, so does the log entry for it."""
    actor_id = user.id if user is not None else user_id
    actor_role = ",".join(sorted(user.role_names)) if user is not None else None
    ip_address = None
    user_agent = None
    req_id = None
    if request is not None:
        ip_address = client_ip(request)
        user_agent = request.headers.get("user-agent")
        req_id = getattr(request.state, "request_id", None)

    event = AuditEvent(
        user_id=actor_id,
        actor_role=actor_role,
        event_type=event_type,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        ip_address=ip_address,
        user_agent=user_agent,
        success=success,
        detail=redact_pii(detail) if detail else None,
        request_id=req_id,
    )
    db.add(event)
    return event


def list_events(
    db: Session,
    *,
    page: int = 1,
    page_size: int = 25,
    actor_email: str | None = None,
    event_type: str | None = None,
    resource_type: str | None = None,
    success: bool | None = None,
    since: str | None = None,
    until: str | None = None,
) -> tuple[list[AuditEvent], int]:
    query = select(AuditEvent).order_by(AuditEvent.created_at.desc())
    conditions = []
    if event_type:
        conditions.append(AuditEvent.event_type == event_type)
    if resource_type:
        conditions.append(AuditEvent.resource_type == resource_type)
    if success is not None:
        conditions.append(AuditEvent.success == success)
    if since:
        conditions.append(AuditEvent.created_at >= since)
    if until:
        conditions.append(AuditEvent.created_at <= until)
    if actor_email:
        matching_ids = [u.id for u in db.query(User).filter(User.email.ilike(f"%{actor_email}%")).all()]
        conditions.append(AuditEvent.user_id.in_(matching_ids) if matching_ids else AuditEvent.id.is_(None))
    if conditions:
        query = query.where(and_(*conditions))

    total = len(db.execute(query).all())
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    rows = db.execute(query.offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return list(rows), total
