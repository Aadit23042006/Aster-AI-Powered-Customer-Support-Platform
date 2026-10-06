"""Notification service (Phase 3, Feature 23): creates the in-app
`notifications` row (always, synchronously -- the bell/unread-count must
reflect it immediately) and, if `NOTIFICATIONS_ENABLED`, enqueues an email
delivery task via Celery (see `app/workers/tasks/notification_tasks.py`)
so a slow/flaky SMTP call never blocks the request that triggered the
notification (a ticket being created, a handoff firing, etc.).

Extends rather than replaces: this is the first real notification service
in the codebase (Phase 1/2 had no notification system at all), so there is
nothing to preserve here -- this IS the implementation the Phase 3 brief
asks for the future to extend.
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app import config
from app.db.models import Notification, User

_VALID_TYPES = {
    "ticket_created", "ticket_assigned", "ticket_updated", "ticket_resolved",
    "handoff_requested", "human_agent_replied", "order_status_changed",
    "ai_response_requires_attention", "kb_indexing_completed", "kb_indexing_failed",
    "evaluation_completed", "security_alert", "rate_limit_warning", "system_incident",
}


def create_notification(
    db: Session,
    *,
    user_id: uuid.UUID,
    type: str,
    title: str,
    message: str,
    data: dict | None = None,
    send_email: bool = True,
) -> Notification:
    notification = Notification(
        user_id=user_id,
        type=type if type in _VALID_TYPES else "system_incident",
        title=title[:200],
        message=message,
        data=data,
    )
    db.add(notification)
    db.flush()

    if send_email and config.NOTIFICATIONS_ENABLED:
        # Deferred import: avoids importing Celery (and connecting to
        # Redis) for every request that merely imports this service --
        # only requests that actually create a notification pay that cost.
        from app.workers.tasks.notification_tasks import send_notification_email

        user = db.get(User, user_id)
        if user is not None:
            send_notification_email.delay(str(notification.id), user.email, title, message)

    return notification


def list_notifications(db: Session, user_id: uuid.UUID, *, page: int = 1, page_size: int = 25) -> tuple[list[Notification], int]:
    query = db.query(Notification).filter(Notification.user_id == user_id).order_by(Notification.created_at.desc())
    total = query.count()
    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return rows, total


def unread_count(db: Session, user_id: uuid.UUID) -> int:
    return db.query(Notification).filter(Notification.user_id == user_id, Notification.read_at.is_(None)).count()


def mark_read(db: Session, notification: Notification) -> None:
    from datetime import datetime, timezone

    if notification.read_at is None:
        notification.read_at = datetime.now(timezone.utc)


def mark_all_read(db: Session, user_id: uuid.UUID) -> int:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    result = (
        db.query(Notification)
        .filter(Notification.user_id == user_id, Notification.read_at.is_(None))
        .update({"read_at": now}, synchronize_session=False)
    )
    return result
