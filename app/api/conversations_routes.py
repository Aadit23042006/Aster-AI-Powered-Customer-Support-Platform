from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.agent import Agent
from app import config
from app.auth.deps import get_current_user
from app.security.rate_limit_deps import rate_limit_by_user
from app.api.web_schemas import (
    ConversationCreateRequest,
    ConversationOut,
    ConversationRenameRequest,
    EditMessageRequest,
    MessageOut,
    SendMessageRequest,
    SendMessageResponse,
)
from app.db.base import get_db
from app.db.models import User
from app.services import conversation_service

router = APIRouter(prefix="/conversations", tags=["conversations"])


def get_agent_dependency() -> Agent:  # overridden in app/server.py at startup
    raise RuntimeError("Agent dependency not configured")


@router.get("", response_model=list[ConversationOut])
def list_conversations(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[ConversationOut]:
    return conversation_service.list_conversations_for_user(db, user.id)


@router.post("", response_model=ConversationOut, status_code=201)
def create_conversation(
    payload: ConversationCreateRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ConversationOut:
    conv = conversation_service.create_conversation(db, user_id=user.id, title=payload.title)
    db.commit()
    db.refresh(conv)
    return conv


class BulkDeleteRequest(BaseModel):
    """Delete several of the caller's conversations in one request.

    Send `ids` to delete specific conversations, or `all: true` to delete
    every conversation owned by the current user.
    """

    ids: list[uuid.UUID] = Field(default_factory=list, max_length=1000)
    all: bool = False


class BulkDeleteResponse(BaseModel):
    deleted: int


@router.post("/bulk-delete", response_model=BulkDeleteResponse)
def bulk_delete_conversations(
    payload: BulkDeleteRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BulkDeleteResponse:
    if not payload.all and not payload.ids:
        raise HTTPException(status_code=422, detail="No conversations selected.")
    deleted = conversation_service.delete_conversations_for_user(
        db, user.id, None if payload.all else payload.ids
    )
    db.commit()
    return BulkDeleteResponse(deleted=deleted)


def _get_conversation_or_404(conversation_id: uuid.UUID, user: User, db: Session):
    conv = conversation_service.get_conversation_for_user(db, user.id, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return conv


@router.get("/{conversation_id}", response_model=ConversationOut)
def get_conversation(conversation_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ConversationOut:
    return _get_conversation_or_404(conversation_id, user, db)


@router.patch("/{conversation_id}", response_model=ConversationOut)
def rename_conversation(
    conversation_id: uuid.UUID, payload: ConversationRenameRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ConversationOut:
    conv = _get_conversation_or_404(conversation_id, user, db)
    conversation_service.rename_conversation(conv, payload.title)
    db.commit()
    db.refresh(conv)
    return conv


@router.post("/{conversation_id}/archive", response_model=ConversationOut)
def archive_conversation(conversation_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ConversationOut:
    conv = _get_conversation_or_404(conversation_id, user, db)
    conversation_service.archive_conversation(conv)
    db.commit()
    db.refresh(conv)
    return conv


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    conv = _get_conversation_or_404(conversation_id, user, db)
    conversation_service.delete_conversation(db, conv)
    db.commit()
    return None


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
def list_messages(conversation_id: uuid.UUID, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[MessageOut]:
    conv = _get_conversation_or_404(conversation_id, user, db)
    return conv.messages


@router.patch("/{conversation_id}/messages/{message_id}", status_code=204)
def edit_user_message(
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    payload: EditMessageRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_agent_dependency),
) -> None:
    """Prepare a user question for editing.

    The selected user message and every later turn are removed. The frontend
    then submits the replacement question through the normal send endpoint,
    so the existing RAG/safety/streaming pipeline remains unchanged.
    """
    conv = _get_conversation_or_404(conversation_id, user, db)

    target = conversation_service.get_message_for_user(
        db, conversation_id=conv.id, message_id=message_id, role="user"
    )
    if target is None:
        raise HTTPException(status_code=404, detail="User message not found.")

    if not payload.message.strip():
        raise HTTPException(status_code=422, detail="Message cannot be empty.")

    conversation_service.edit_user_message(
        db, agent, conversation=conv, message_id=message_id
    )
    if not conv.messages:
        conv.title = "New conversation"
    db.commit()
    return None


@router.post(
    "/{conversation_id}/messages",
    response_model=SendMessageResponse,
    dependencies=[Depends(rate_limit_by_user("ai_chat", "RATE_LIMIT_AI_CHAT"))],
)
def send_message(
    conversation_id: uuid.UUID,
    payload: SendMessageRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_agent_dependency),
) -> SendMessageResponse:
    conv = _get_conversation_or_404(conversation_id, user, db)
    user_row, assistant_row, result, ticket_number = conversation_service.send_message(
        db, agent, conversation=conv, user_id=user.id, user_message=payload.message,
        attachment_ids=payload.attachment_ids,
    )
    db.commit()
    db.refresh(user_row)
    db.refresh(assistant_row)
    return SendMessageResponse(
        user_message=user_row,
        assistant_message=assistant_row,
        sources=result.sources,
        handoff=result.handoff,
        handoff_reason=result.handoff_reason,
        ticket_number=ticket_number,
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _chunk_text(text: str, *, chunk_size: int = 24) -> list[str]:
    """Splits the already-generated, already-validated answer into small
    word-boundary chunks for a progressive ("typewriter") reveal on the
    frontend. We deliberately do NOT ask the LLM for token-level streaming
    here: `Agent.handle_turn` (unchanged, see app/agent.py) relies on
    Gemini's structured `response_schema` output so it can enforce the
    citation/handoff/safety guarantees documented there, and that contract
    only exists once the full structured response has been parsed. Revealing
    the validated text progressively still gives the UI the "response
    appears progressively" behavior Feature 11 asks for, without weakening
    any RAG/safety/citation guarantee or duplicating the agent's answer
    logic. True model-level token streaming would require the agent to
    switch to an unstructured streaming call and re-derive citations/safety
    fields from partial output -- a larger, riskier change to protected
    Phase 1 logic than this endpoint's scope.
    """
    words = text.split(" ")
    chunks: list[str] = []
    for i in range(0, len(words), chunk_size):
        piece = " ".join(words[i : i + chunk_size])
        if i + chunk_size < len(words):
            piece += " "
        chunks.append(piece)
    return chunks or [text]


@router.post(
    "/{conversation_id}/messages/stream",
    dependencies=[Depends(rate_limit_by_user("ai_chat", "RATE_LIMIT_AI_CHAT"))],
)
def stream_message(
    conversation_id: uuid.UUID,
    payload: SendMessageRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_agent_dependency),
):
    """SSE endpoint for Feature 11 (streaming AI responses).

    The full turn -- auth, conversation ownership, RAG, order tools, safety
    checks, handoff logic, and persistence -- runs exactly as it does for
    `POST /messages` (same `conversation_service.send_message`, unchanged)
    *before* any bytes are streamed, so the DB is never left in an
    inconsistent state and a dropped connection mid-stream can never lose
    or duplicate a turn. Only the already-persisted, already-validated
    answer text is revealed progressively to the client.
    """
    conv = _get_conversation_or_404(conversation_id, user, db)
    user_row, assistant_row, result, ticket_number = conversation_service.send_message(
        db, agent, conversation=conv, user_id=user.id, user_message=payload.message,
        attachment_ids=payload.attachment_ids,
    )
    db.commit()
    db.refresh(user_row)
    db.refresh(assistant_row)

    assistant_message_out = MessageOut.model_validate(assistant_row).model_dump(mode="json")
    user_message_out = MessageOut.model_validate(user_row).model_dump(mode="json")

    def _event_stream():
        yield _sse("start", {"conversation_id": str(conversation_id), "user_message": user_message_out})
        for piece in _chunk_text(result.answer):
            yield _sse("delta", {"text": piece})
        yield _sse(
            "done",
            {
                "assistant_message": assistant_message_out,
                "sources": result.sources,
                "handoff": result.handoff,
                "handoff_reason": result.handoff_reason,
                "ticket_number": ticket_number,
            },
        )

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
