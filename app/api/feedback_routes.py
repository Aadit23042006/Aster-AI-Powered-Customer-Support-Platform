"""Feedback routes (Phase 2, Feature 15).

Mounted at `/messages/{message_id}/feedback`, alongside the existing
`/conversations/.../messages` surface. Ownership is enforced the same way
as everywhere else in this app: a message only accepts feedback from the
user who owns the conversation it belongs to (never a client-supplied
user_id), returning 404 rather than 403 for someone else's message so a
customer can't even confirm another user's message ID exists.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import config
from app.auth.deps import get_current_user
from app.security.rate_limit_deps import rate_limit_by_user
from app.api.web_schemas import FeedbackCreateRequest, FeedbackOut, FeedbackSubmitResponse
from app.db.base import get_db
from app.db.models import Message, User
from app.services import feedback_service

router = APIRouter(prefix="/messages", tags=["feedback"])


def _get_owned_message_or_404(message_id: uuid.UUID, user: User, db: Session) -> Message:
    message = (
        db.query(Message)
        .join(Message.conversation)
        .filter(Message.id == message_id, Message.conversation.has(user_id=user.id))
        .first()
    )
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found.")
    return message


@router.post(
    "/{message_id}/feedback",
    response_model=FeedbackSubmitResponse,
    status_code=201,
    dependencies=[Depends(rate_limit_by_user("feedback", "RATE_LIMIT_FEEDBACK"))],
)
def submit_feedback(
    message_id: uuid.UUID,
    payload: FeedbackCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FeedbackSubmitResponse:
    message = _get_owned_message_or_404(message_id, user, db)
    try:
        feedback = feedback_service.submit_feedback(
            db,
            message=message,
            user_id=user.id,
            rating=payload.rating,
            reason=payload.reason,
            comment=payload.comment,
        )
    except feedback_service.FeedbackError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    suggest_handoff = (
        payload.rating == "negative"
        and feedback_service.should_suggest_handoff(db, conversation_id=message.conversation_id, user_id=user.id)
    )
    db.commit()
    db.refresh(feedback)
    return FeedbackSubmitResponse(feedback=feedback, suggest_handoff=suggest_handoff)


@router.get("/{message_id}/feedback", response_model=FeedbackOut | None)
def get_feedback(
    message_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> FeedbackOut | None:
    _get_owned_message_or_404(message_id, user, db)
    feedback = feedback_service.get_feedback(db, message_id=message_id, user_id=user.id)
    return feedback
