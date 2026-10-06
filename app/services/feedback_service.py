"""Feature 15: thumbs-up/down feedback on assistant messages.

One feedback row per (user, message) -- see the `uq_feedback_user_message`
constraint on `AIFeedback`. Submitting feedback again for the same message
updates the existing row (rating/reason/comment) instead of creating a
second one, which is both "prevent duplicate feedback" (Feature 15) and a
better UX than rejecting a changed mind outright.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.db.models import AIFeedback, Message

VALID_RATINGS = {"positive", "negative"}
VALID_REASONS = {"incorrect_answer", "didnt_solve_problem", "missing_information", "needed_human", "other"}

# Feature 15: "If a customer repeatedly marks responses as unhelpful, the
# application may suggest... talk to a specialist." Deliberately a simple,
# explainable, deterministic rule (not a model call) in the same spirit as
# the agent's own deterministic handoff rules in app/agent.py -- consistent
# behavior the frontend can rely on, and nothing that silently opens a
# ticket on its own (Feature 15: "Do not automatically create unnecessary
# tickets" -- this only ever returns a suggestion flag).
NEGATIVE_STREAK_THRESHOLD = 2
NEGATIVE_STREAK_WINDOW = timedelta(hours=2)


class FeedbackError(Exception):
    pass


def submit_feedback(
    db: Session,
    *,
    message: Message,
    user_id: uuid.UUID,
    rating: str,
    reason: str | None,
    comment: str | None,
) -> AIFeedback:
    if rating not in VALID_RATINGS:
        raise FeedbackError(f"Invalid rating: {rating}")
    if reason is not None and reason not in VALID_REASONS:
        raise FeedbackError(f"Invalid reason: {reason}")
    if message.role != "assistant":
        raise FeedbackError("Feedback can only be left on an assistant message.")

    existing = (
        db.query(AIFeedback)
        .filter(AIFeedback.user_id == user_id, AIFeedback.message_id == message.id)
        .first()
    )
    if existing:
        existing.rating = rating
        existing.reason = reason
        existing.comment = comment
        db.flush()
        return existing

    feedback = AIFeedback(
        user_id=user_id,
        conversation_id=message.conversation_id,
        message_id=message.id,
        rating=rating,
        reason=reason,
        comment=comment,
    )
    db.add(feedback)
    db.flush()
    return feedback


def get_feedback(db: Session, *, message_id: uuid.UUID, user_id: uuid.UUID) -> AIFeedback | None:
    return (
        db.query(AIFeedback)
        .filter(AIFeedback.user_id == user_id, AIFeedback.message_id == message_id)
        .first()
    )


def should_suggest_handoff(db: Session, *, conversation_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """True once the user has left `NEGATIVE_STREAK_THRESHOLD`+ negative
    ratings in this conversation within `NEGATIVE_STREAK_WINDOW`."""
    since = datetime.now(timezone.utc) - NEGATIVE_STREAK_WINDOW
    count = (
        db.query(AIFeedback)
        .filter(
            AIFeedback.conversation_id == conversation_id,
            AIFeedback.user_id == user_id,
            AIFeedback.rating == "negative",
            AIFeedback.created_at >= since,
        )
        .count()
    )
    return count >= NEGATIVE_STREAK_THRESHOLD
