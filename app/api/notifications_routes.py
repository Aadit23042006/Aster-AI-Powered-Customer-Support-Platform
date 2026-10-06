from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.api.web_schemas import NotificationOut, UnreadCountOut
from app.db.base import get_db
from app.db.models import Notification, User
from app.notifications import service as notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationOut])
def list_my_notifications(
    page: int = 1, page_size: int = 25, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[NotificationOut]:
    items, _total = notification_service.list_notifications(db, user.id, page=page, page_size=page_size)
    return items


@router.get("/unread-count", response_model=UnreadCountOut)
def get_unread_count(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> UnreadCountOut:
    return UnreadCountOut(unread_count=notification_service.unread_count(db, user.id))


@router.post("/{notification_id}/read", response_model=NotificationOut)
def mark_notification_read(
    notification_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> NotificationOut:
    notification = db.query(Notification).filter(Notification.id == notification_id, Notification.user_id == user.id).first()
    if notification is None:
        raise HTTPException(status_code=404, detail="Notification not found.")
    notification_service.mark_read(db, notification)
    db.commit()
    db.refresh(notification)
    return notification


@router.post("/read-all")
def mark_all_read(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    count = notification_service.mark_all_read(db, user.id)
    db.commit()
    return {"marked_read": count}
