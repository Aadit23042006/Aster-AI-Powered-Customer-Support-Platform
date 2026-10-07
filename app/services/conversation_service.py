"""Persistent conversations, backed by Postgres, wired to the EXISTING
`app.agent.Agent`.

This service:

1. Creates/lists/renames/archives Conversation/Message rows.
2. Hydrates the existing Agent session from persisted messages.
3. Calls Agent.handle_turn().
4. Persists user and assistant messages.
5. Creates AI-originated Action Center proposals.
6. Never bypasses Action Center approval.
7. Prevents duplicate generic handoff tickets while approval is pending.
8. Prevents AI escalation from directly mutating tickets.

Quality Guard observability:

9. Preserves the initial Quality Guard decision.
10. Records whether wider retrieval was attempted.
11. Records retry decision and scores.
12. Records explicit fallback actions.
13. Preserves initial BLOCK when converted to HUMAN_HANDOFF.
14. Persists nested `quality_trace` in assistant metadata.
15. Preserves initial/retry/final decisions after Action Center processing.
16. Persists the same trace inside AIQualityCheck.details.

Order protection:

17. A successful authenticated database order lookup is authoritative.
18. Quality Guard must not replace a successful order result with a generic
    "couldn't verify" response.
19. Order ownership is always enforced by user_id.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.agent import Agent, TurnResult

from app.db.models import (
    Conversation,
    Message,
    ConversationClassification,
    AIQualityCheck,
    ConversationCitation,
    MediaAttachment,
    Order,
)

from app.notifications.service import create_notification
from app.services import ticket_service
from app.services.order_service import current_user_id_var

from app.enterprise.intelligence import (
    classify_message,
    CLASSIFIER_MODEL,
    CLASSIFIER_VERSION,
    CLASSIFIER_SOURCE,
)

from app.enterprise.quality import (
    assess,
    needs_clarification,
    CLARIFICATION_TEXT,
)

from app.enterprise.citations import build_citations
from app.security.pii import redact_pii


logger = logging.getLogger(__name__)


# ============================================================================
# JSON / QUALITY TRACE HELPERS
# ============================================================================


def _copy_json_dict(value):
    """Return a detached JSON-safe value."""

    if value is None:
        return None

    try:
        return json.loads(
            json.dumps(
                value,
                default=str,
            )
        )
    except Exception:
        logger.exception(
            "Failed to JSON-copy value"
        )

        if isinstance(value, dict):
            return dict(value)

        return value


def _build_quality_trace(
    *,
    initial_decision,
    initial_grounding_score,
    initial_policy_check,
    initial_pii_check,
    initial_confidence,
    initial_retrieval_score,
    initial_relevance_score,
    initial_details,
    retry_attempted,
    retry_decision,
    retry_grounding_score,
    retry_policy_check,
    retry_pii_check,
    retry_confidence,
    retry_retrieval_score,
    retry_relevance_score,
    retry_details,
    final_decision,
    fallback_action,
):
    """Build the single authoritative Quality Guard trace."""

    return {
        "initial_decision": initial_decision,
        "initial_grounding_score": initial_grounding_score,
        "initial_policy_check": initial_policy_check,
        "initial_pii_check": initial_pii_check,
        "initial_confidence": initial_confidence,
        "initial_retrieval_score": initial_retrieval_score,
        "initial_relevance_score": initial_relevance_score,
        "initial_details": _copy_json_dict(initial_details),

        "retry_attempted": retry_attempted,
        "retry_decision": retry_decision,
        "retry_grounding_score": retry_grounding_score,
        "retry_policy_check": retry_policy_check,
        "retry_pii_check": retry_pii_check,
        "retry_confidence": retry_confidence,
        "retry_retrieval_score": retry_retrieval_score,
        "retry_relevance_score": retry_relevance_score,
        "retry_details": _copy_json_dict(retry_details),

        "final_decision": final_decision,
        "fallback_action": fallback_action,
    }


def _persist_quality_trace_directly(
    db: Session,
    *,
    message_id: uuid.UUID,
    quality_trace: dict,
) -> None:
    """Persist quality_trace directly into PostgreSQL JSON metadata."""

    trace_payload = json.dumps(
        _copy_json_dict(quality_trace),
        default=str,
    )

    result = db.execute(
        text(
            """
            UPDATE messages
            SET meta = jsonb_set(
                COALESCE(meta::jsonb, '{}'::jsonb),
                '{quality_trace}',
                CAST(:quality_trace AS jsonb),
                true
            )::json
            WHERE id = :message_id
            """
        ),
        {
            "quality_trace": trace_payload,
            "message_id": str(message_id),
        },
    )

    if result.rowcount != 1:
        raise RuntimeError(
            "quality_trace persistence updated "
            f"{result.rowcount} rows for message {message_id}"
        )

    db.flush()

    logger.info(
        "QUALITY_TRACE_DB_PERSISTED "
        "message_id=%s "
        "trace_keys=%s",
        message_id,
        list(quality_trace.keys()),
    )


def _persist_final_quality_trace(
    db: Session,
    *,
    assistant_row: Message,
    quality_trace: dict,
) -> None:
    """Final authoritative persistence point."""

    trace = _copy_json_dict(quality_trace)

    assistant_meta = dict(
        assistant_row.meta or {}
    )

    assistant_meta["quality_trace"] = trace

    assistant_row.meta = assistant_meta

    flag_modified(
        assistant_row,
        "meta",
    )

    db.flush()

    logger.info(
        "QUALITY_TRACE_FINAL_ORM_FLUSH "
        "message_id=%s "
        "has_quality_trace=%s",
        assistant_row.id,
        bool(
            assistant_row.meta
            and assistant_row.meta.get(
                "quality_trace"
            )
        ),
    )

    _persist_quality_trace_directly(
        db,
        message_id=assistant_row.id,
        quality_trace=trace,
    )

    logger.info(
        "QUALITY_TRACE_FINAL_PERSISTED "
        "message_id=%s",
        assistant_row.id,
    )


# ============================================================================
# ORDER RESULT PROTECTION
# ============================================================================


_ORDER_ID_RE = re.compile(
    r"\b(?:ORD[-\s]?\d{3,6}|ORDER[-#\s]?\d{3,6}|#\d{3,6})\b",
    re.IGNORECASE,
)


def _extract_order_id(
    user_message: str,
) -> str | None:
    """Extract and normalize an explicit order ID."""

    if not user_message:
        return None

    match = _ORDER_ID_RE.search(
        user_message
    )

    if match is None:
        return None

    value = match.group(0).upper()

    value = re.sub(
        r"^ORDER[-#\s]?",
        "ORD-",
        value,
        flags=re.IGNORECASE,
    )

    value = re.sub(
        r"^#",
        "ORD-",
        value,
    )

    value = re.sub(
        r"^ORD\s+",
        "ORD-",
        value,
    )

    return value


def _repair_successful_order_answer(
    db: Session,
    *,
    user_id: uuid.UUID,
    user_message: str,
    result: TurnResult,
) -> bool:
    """Protect a successful authenticated DB order lookup.

    The Agent performs the authoritative order lookup. However, Quality Guard
    may later replace a valid order answer with a generic grounding fallback.

    This helper independently verifies the explicit order ID against the
    authenticated user's PostgreSQL orders and restores a deterministic,
    customer-safe answer when the order exists.

    It NEVER searches another user's order.
    """

    order_id = _extract_order_id(
        user_message
    )

    if order_id is None:
        return False

    try:
        order = (
            db.query(Order)
            .filter(
                Order.order_number == order_id,
                Order.user_id == user_id,
            )
            .first()
        )

        if order is None:
            return False

        status = str(
            order.status or ""
        ).strip()

        if not status:
            return False

        current_answer = (
            result.answer or ""
        ).lower()

        # If the valid order information is already present, leave the
        # Agent's richer answer untouched.
        if (
            order_id.lower() in current_answer
            or status.lower() in current_answer
        ):
            return False

        result.answer = (
            f"Order {order_id} is currently {status}."
        )

        result.handoff = False
        result.handoff_reason = None
        result.insufficient_information = False

        logger.info(
            "ORDER_RESULT_PROTECTED "
            "user_id=%s "
            "order_id=%s "
            "status=%s",
            user_id,
            order_id,
            status,
        )

        return True

    except Exception:
        logger.exception(
            "ORDER_RESULT_PROTECTION_FAILED "
            "user_id=%s "
            "order_id=%s",
            user_id,
            order_id,
        )

        return False


# ============================================================================
# CONVERSATION CRUD
# ============================================================================


def create_conversation(
    db: Session,
    *,
    user_id: uuid.UUID,
    title: str | None = None,
) -> Conversation:
    conv = Conversation(
        user_id=user_id,
        title=title or "New conversation",
    )

    db.add(conv)
    db.flush()

    return conv


def list_conversations_for_user(
    db: Session,
    user_id: uuid.UUID,
) -> list[Conversation]:
    return (
        db.query(Conversation)
        .filter(Conversation.user_id == user_id)
        .order_by(Conversation.updated_at.desc())
        .all()
    )


def get_conversation_for_user(
    db: Session,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
) -> Conversation | None:
    return (
        db.query(Conversation)
        .filter(
            Conversation.id == conversation_id,
            Conversation.user_id == user_id,
        )
        .first()
    )


def get_message_for_user(
    db: Session,
    *,
    conversation_id: uuid.UUID,
    message_id: uuid.UUID,
    role: str | None = None,
) -> Message | None:
    query = db.query(Message).filter(
        Message.id == message_id,
        Message.conversation_id == conversation_id,
    )

    if role is not None:
        query = query.filter(
            Message.role == role
        )

    return query.first()


def rename_conversation(
    conversation: Conversation,
    title: str,
) -> None:
    conversation.title = title[:200]


def archive_conversation(
    conversation: Conversation,
) -> None:
    from datetime import datetime, timezone

    conversation.status = "archived"
    conversation.archived_at = datetime.now(
        timezone.utc
    )


def delete_conversation(
    db: Session,
    conversation: Conversation,
) -> None:
    db.delete(conversation)


def delete_conversations_for_user(
    db: Session,
    user_id: uuid.UUID,
    conversation_ids: list[uuid.UUID] | None,
) -> int:
    """Delete conversations owned by user_id."""

    query = db.query(Conversation).filter(
        Conversation.user_id == user_id
    )

    if conversation_ids is not None:
        query = query.filter(
            Conversation.id.in_(conversation_ids)
        )

    rows = query.all()

    for row in rows:
        db.delete(row)

    return len(rows)


# ============================================================================
# MESSAGE EDITING / SESSION HYDRATION
# ============================================================================


def edit_user_message(
    db: Session,
    agent: Agent,
    *,
    conversation: Conversation,
    message_id: uuid.UUID,
) -> Message:
    target = (
        db.query(Message)
        .filter(
            Message.id == message_id,
            Message.conversation_id == conversation.id,
            Message.role == "user",
        )
        .first()
    )

    if target is None:
        raise ValueError(
            "User message not found."
        )

    messages_to_remove = (
        db.query(Message)
        .filter(
            Message.conversation_id == conversation.id,
            Message.created_at >= target.created_at,
        )
        .order_by(Message.created_at.asc())
        .all()
    )

    for message in messages_to_remove:
        db.delete(message)

    db.flush()

    agent.sessions.reset(
        str(conversation.id)
    )

    return target


def _auto_title(first_message: str) -> str:
    cleaned = " ".join(
        first_message.split()
    )

    return cleaned[:60] + (
        "…" if len(cleaned) > 60 else ""
    )


def hydrate_agent_session(
    agent: Agent,
    conversation_id: uuid.UUID,
    db_messages: list[Message],
) -> None:
    session = agent.sessions.get_or_create(
        str(conversation_id)
    )

    if not session.turns and db_messages:
        for message in db_messages:
            session.add(
                role=message.role,
                content=message.content,
            )


# ============================================================================
# ACTION CENTER DETECTION
# ============================================================================


def _is_explicit_ticket_request(
    user_message: str,
) -> bool:
    if not user_message:
        return False

    return bool(
        re.search(
            r"\b("
            r"create|open|raise|make|submit|start"
            r")\b.{0,80}\b("
            r"support\s+ticket|ticket|case|support\s+request"
            r")\b",
            user_message,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )


def _is_explicit_escalation_request(
    user_message: str,
) -> bool:
    if not user_message:
        return False

    direct_match = re.search(
        r"\b("
        r"escalate|escalation|prioritize|priority"
        r")\b.{0,100}\b("
        r"support\s+ticket|ticket|case|support\s+request"
        r")\b",
        user_message,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if direct_match:
        return True

    reverse_match = re.search(
        r"\b("
        r"ticket|support\s+ticket|case|support\s+request"
        r")\b.{0,100}\b("
        r"escalat\w*|priorit\w*"
        r")\b",
        user_message,
        flags=re.IGNORECASE | re.DOTALL,
    )

    return bool(reverse_match)


def _propose_create_support_ticket(
    db: Session,
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    user_message: str,
    explicit_request: bool,
) -> dict | None:
    try:
        from app import config as _cfg
        from app.db.models import User as _User
        from app.enterprise import actions as _actions

        if not _cfg.AI_AGENT_ACTIONS_ENABLED:
            return None

        customer = db.get(
            _User,
            user_id,
        )

        if customer is None:
            return None

        if explicit_request:
            subject = "Delivery help for order"
            reason = (
                "Customer explicitly requested a support ticket; "
                "AI proposes the ticket through the Action Center."
            )
        else:
            subject = "Possible delayed order"
            reason = (
                "Customer reported a possibly delayed order; "
                "AI proposes a support ticket."
            )

        action_result = _actions.execute(
            db,
            customer,
            "create_support_ticket",
            {
                "subject": subject,
                "description": redact_pii(
                    user_message
                )[:1000],
                "category": "shipping",
                "priority": "high",
            },
            conversation_id,
            origin="ai",
            commit=False,
            reason=reason,
        )

        logger.info(
            "AI support-ticket proposal created: %s",
            action_result,
        )

        return action_result

    except Exception:
        logger.exception(
            "AI support-ticket proposal failed"
        )
        return None


def _propose_escalate_ticket(
    db: Session,
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    user_message: str,
) -> dict | None:
    try:
        from app import config as _cfg
        from app.db.models import (
            User as _User,
            Ticket as _Ticket,
        )
        from app.enterprise import actions as _actions

        if not _cfg.AI_AGENT_ACTIONS_ENABLED:
            return None

        customer = db.get(
            _User,
            user_id,
        )

        if customer is None:
            return None

        match = re.search(
            r"\b(AR-\d{3,20})\b",
            user_message,
            flags=re.IGNORECASE,
        )

        if match is None:
            return None

        ticket_number = match.group(1).upper()

        ticket = (
            db.query(_Ticket)
            .filter(
                _Ticket.ticket_number == ticket_number,
                _Ticket.user_id == user_id,
            )
            .first()
        )

        if ticket is None:
            return None

        current_status = str(
            ticket.status or ""
        ).lower()

        if current_status in {
            "resolved",
            "closed",
        }:
            return None

        reason = (
            "Customer explicitly requested escalation of support "
            f"ticket {ticket_number}; AI proposes escalation "
            "through the Action Center."
        )

        action_result = _actions.execute(
            db,
            customer,
            "escalate_ticket",
            {
                "ticket_id": str(ticket.id),
            },
            conversation_id,
            origin="ai",
            commit=False,
            reason=reason,
        )

        logger.info(
            "AI ticket escalation proposal created: %s",
            action_result,
        )

        return action_result

    except Exception:
        logger.exception(
            "AI ticket escalation proposal failed"
        )
        return None


def _action_requires_approval(
    action_result: dict | None,
) -> bool:
    if not action_result:
        return False

    approval_status = str(
        action_result.get("approval_status")
        or action_result.get("approval")
        or ""
    ).lower()

    execution_status = str(
        action_result.get("execution_status")
        or action_result.get("status")
        or ""
    ).lower()

    return (
        approval_status
        in {
            "pending",
            "approval_required",
        }
        or execution_status
        in {
            "approval_required",
            "pending_approval",
        }
    )


def _set_pending_ticket_response(
    result: TurnResult,
) -> None:
    result.answer = (
        "Your request has been prepared as a support-ticket action "
        "for human approval. The request is currently waiting for "
        "approval in the Action Center. The support ticket has not "
        "been created yet."
    )

    result.handoff = False
    result.handoff_reason = None


def _set_pending_escalation_response(
    result: TurnResult,
    ticket_number: str | None = None,
) -> None:
    if ticket_number:
        result.answer = (
            f"Your request to escalate support ticket "
            f"{ticket_number} has been prepared and is waiting "
            "for human approval in the Action Center. The ticket "
            "has not been escalated yet."
        )
    else:
        result.answer = (
            "Your escalation request has been prepared and is "
            "waiting for human approval in the Action Center. "
            "The ticket has not been escalated yet."
        )

    result.handoff = False
    result.handoff_reason = None


def _extract_ticket_number(
    user_message: str,
) -> str | None:
    if not user_message:
        return None

    match = re.search(
        r"\b(AR-\d{3,20})\b",
        user_message,
        flags=re.IGNORECASE,
    )

    if match is None:
        return None

    return match.group(1).upper()


# ============================================================================
# SEND MESSAGE
# ============================================================================


def send_message(
    db: Session,
    agent: Agent,
    *,
    conversation: Conversation,
    user_id: uuid.UUID,
    user_message: str,
    attachment_ids: list[uuid.UUID] | None = None,
) -> tuple[
    Message,
    Message,
    TurnResult,
    str | None,
]:
    """Run one full turn and persist all enterprise observability."""

    if (
        conversation.title == "New conversation"
        and not conversation.messages
    ):
        conversation.title = _auto_title(
            user_message
        )

    hydrate_agent_session(
        agent,
        conversation.id,
        conversation.messages,
    )

    # ------------------------------------------------------------------------
    # ATTACHMENTS
    # ------------------------------------------------------------------------

    attachment_query = (
        db.query(MediaAttachment)
        .filter(
            MediaAttachment.user_id == user_id,
            MediaAttachment.conversation_id == conversation.id,
            MediaAttachment.message_id.is_(None),
            MediaAttachment.analysis_status == "completed",
        )
    )

    if attachment_ids:
        attachment_query = attachment_query.filter(
            MediaAttachment.id.in_(attachment_ids)
        )

    pending_attachments = attachment_query.order_by(
        MediaAttachment.created_at.asc()
    ).all()

    agent_user_message = user_message

    if pending_attachments:
        context_blocks = []

        for attachment in pending_attachments:
            context_blocks.append(
                f"Attached file: {attachment.filename}\n"
                f"Type: {attachment.content_type}\n"
                "Extracted/vision context:\n"
                f"{attachment.analysis_text or 'No extractable text or analysis is available.'}"
            )

        agent_user_message = (
            f"User question:\n{user_message}\n\n"
            "The user attached the following file(s). Use them as evidence "
            "when answering the question and do not invent details:\n\n"
            + "\n\n---\n\n".join(context_blocks)
        )

    from app import config as _cfg

    from app.llm_usage import (
        UsageCollector,
        model_override_var,
        usage_collector_var,
    )

    from app.enterprise import model_router as _router

    explicit_ticket_request = (
        _is_explicit_ticket_request(
            user_message
        )
    )

    explicit_escalation_request = (
        _is_explicit_escalation_request(
            user_message
        )
    )

    token = current_user_id_var.set(
        user_id
    )

    collector = UsageCollector()

    collector_token = usage_collector_var.set(
        collector
    )

    decision = None
    override_token = None
    turn_ok = True
    started_at = time.time()

    try:
        if (
            _cfg.MODEL_ROUTER_ENABLED
            and not _cfg.USE_MOCK_LLM
        ):
            decision = _router.route(
                _router.classify_request(
                    user_message
                )
            )

            if (
                not decision.fallback_used
                and decision.model
                and decision.model != _cfg.CHAT_MODEL
            ):
                override_token = (
                    model_override_var.set(
                        decision.model
                    )
                )

        try:
            result: TurnResult = agent.handle_turn(
                str(conversation.id),
                agent_user_message,
            )

            from app.monitoring.metrics import metrics

            latency_ms = (
                time.time() - started_at
            ) * 1000

            metrics.record_ai_request(
                latency_ms
            )

        except Exception:
            turn_ok = False
            raise

    finally:
        if override_token is not None:
            model_override_var.reset(
                override_token
            )

        usage_collector_var.reset(
            collector_token
        )

        current_user_id_var.reset(
            token
        )

        if decision is not None:
            try:
                from app.db.models import (
                    ModelRoutingEvent,
                )

                with db.begin_nested():
                    db.add(
                        ModelRoutingEvent(
                            user_id=user_id,
                            conversation_id=conversation.id,
                            routing_category=decision.category,
                            model_used=(
                                collector.models[0]
                                if collector.models
                                else (
                                    decision.model
                                    or _cfg.CHAT_MODEL
                                )
                            ),
                            routing_reason=decision.reason,
                            latency_ms=round(
                                (
                                    time.time()
                                    - started_at
                                ) * 1000,
                                2,
                            ),
                            token_usage={
                                "input_tokens":
                                    collector.input_tokens,
                                "output_tokens":
                                    collector.output_tokens,
                            },
                            success=turn_ok,
                        )
                    )

            except Exception:
                logger.exception(
                    "model routing event persistence failed"
                )

    # =========================================================================
    # IMPORTANT ORDER PROTECTION
    # =========================================================================
    #
    # Agent.handle_turn() already performed the authoritative DB order lookup.
    #
    # However, Quality Guard operates after Agent.handle_turn() and can replace
    # a successful order answer with a generic grounding fallback.
    #
    # Verify the explicit order ID against the authenticated user's own DB
    # orders here before Quality Guard runs.
    #
    # This is deliberately ownership-scoped and cannot expose another user's
    # order.
    # =========================================================================

    order_result_protected = _repair_successful_order_answer(
        db,
        user_id=user_id,
        user_message=user_message,
        result=result,
    )

    if order_result_protected:
        logger.info(
            "ORDER_RESULT_PROTECTION_APPLIED "
            "conversation_id=%s",
            conversation.id,
        )

    # =========================================================================
    # INITIAL MESSAGE PERSISTENCE
    # =========================================================================

    user_row = Message(
        conversation_id=conversation.id,
        role="user",
        content=user_message,
    )

    assistant_row = Message(
        conversation_id=conversation.id,
        role="assistant",
        content=result.answer,
        meta={
            "sources": result.sources,
            "handoff": result.handoff,
            "handoff_reason":
                result.handoff_reason,
            "insufficient_information":
                result.insufficient_information,
        },
    )

    db.add(user_row)
    db.add(assistant_row)
    db.flush()

    # Bind attachments.
    if pending_attachments:
        user_row.meta = {
            "attachments": [
                {
                    "id": str(attachment.id),
                    "filename": attachment.filename,
                    "content_type": attachment.content_type,
                    "size_bytes": attachment.size_bytes,
                    "url": (
                        "/api/v1/chat/attachments/"
                        f"{attachment.id}/content"
                    ),
                }
                for attachment in pending_attachments
            ]
        }

        for attachment in pending_attachments:
            attachment.message_id = user_row.id

        db.flush()

    # =========================================================================
    # INTELLIGENCE
    # =========================================================================

    classification = classify_message(
        user_message
    )

    if _cfg.SENTIMENT_ANALYSIS_ENABLED:
        db.add(
            ConversationClassification(
                conversation_id=conversation.id,
                intent=classification.intent,
                sentiment=classification.sentiment,
                priority=classification.priority,
                topic=classification.topic,
                risk_level=classification.risk_level,
                confidence=classification.confidence,
                model=CLASSIFIER_MODEL,
                model_version=CLASSIFIER_VERSION,
                source=CLASSIFIER_SOURCE,
            )
        )

    automatic_delay_proposal = (
        _cfg.SENTIMENT_ANALYSIS_ENABLED
        and classification.intent == "order_delay"
    )

    action_result = None

    # =========================================================================
    # QUALITY GUARD
    # =========================================================================

    eligible_quality = bool(
        _cfg.QUALITY_GUARD_ENABLED
    )

    try:
        retrieval = (
            agent.retriever.retrieve(
                user_message
            )
            if (
                result.sources
                and (
                    eligible_quality
                    or _cfg.RAG_CITATIONS_ENABLED
                )
            )
            else None
        )
    except Exception:
        logger.exception(
            "initial retrieval failed"
        )
        retrieval = None

    def evidence_for(r):
        used = set(
            result.sources or []
        )

        return [
            h.chunk.text
            for h in (
                r.hits if r else []
            )
            if h.chunk.source_file in used
        ]

    def best_score(r):
        used = set(
            result.sources or []
        )

        scores = [
            float(h.score)
            for h in (
                r.hits if r else []
            )
            if h.chunk.source_file in used
        ]

        return (
            max(scores)
            if scores
            else None
        )

    use_evidence = retrieval is not None

    qr = assess(
        result.answer,
        result.sources,
        result.handoff,
        eligible=eligible_quality,
        question=user_message,
        evidence=(
            evidence_for(retrieval)
            if use_evidence
            else None
        ),
        retrieval_score=(
            best_score(retrieval)
            if use_evidence
            else None
        ),
        allow_general_knowledge=result.general_question,
    )

    # =========================================================================
    # INITIAL QUALITY VALUES
    # =========================================================================

    initial_decision = qr.decision
    initial_grounding = qr.grounding_score
    initial_policy = qr.policy_check
    initial_pii = qr.pii_check
    initial_confidence = qr.confidence
    initial_retrieval = qr.retrieval_score
    initial_relevance = qr.relevance_score
    initial_details = _copy_json_dict(
        qr.details or None
    )

    retry_attempted = False
    retry_decision = None
    retry_grounding = None
    retry_policy = None
    retry_pii = None
    retry_confidence = None
    retry_retrieval = None
    retry_relevance = None
    retry_details = None

    fallback_action = None

    # =========================================================================
    # ORDER LOOKUPS ARE AUTHORITATIVE
    # =========================================================================
    #
    # A successfully verified customer-owned order must never enter the
    # generic RETRY_RETRIEVAL -> "couldn't verify" path.
    #
    # We already verified the order immediately after Agent.handle_turn().
    # Re-checking the explicit order here makes this protection independent
    # from model-provided metadata.
    # =========================================================================

    order_is_authoritative = bool(
        order_result_protected
    )

    if order_is_authoritative:
        fallback_action = "authoritative_order_lookup"

        # The answer came from an authenticated DB lookup, so it is already
        # grounded customer data. Do not replace it with generic RAG fallback.
        result.handoff = False
        result.handoff_reason = None
        result.insufficient_information = False

        qr = assess(
            result.answer,
            result.sources,
            False,
            eligible=False,
            question=user_message,
        )

    # =========================================================================
    # MODEL HANDOFF
    # =========================================================================

    elif (
        eligible_quality
        and result.handoff
        and qr.decision == "HUMAN_HANDOFF"
    ):
        fallback_action = "model_handoff"

    # =========================================================================
    # BLOCK -> HUMAN HANDOFF
    # =========================================================================

    elif (
        eligible_quality
        and qr.decision == "BLOCK"
    ):
        result.answer = (
            "I couldn't provide that information safely. "
            "Please contact a support specialist."
        )

        result.handoff = True
        result.handoff_reason = (
            "Quality Guard blocked the generated response."
        )

        fallback_action = "human_handoff"

        try:
            qr = assess(
                result.answer,
                result.sources,
                True,
                eligible=True,
                question=user_message,
                evidence=(
                    evidence_for(retrieval)
                    if use_evidence
                    else None
                ),
                retrieval_score=(
                    best_score(retrieval)
                    if use_evidence
                    else None
                ),
            )
        except Exception:
            logger.exception(
                "quality reassessment after BLOCK failed"
            )

    # =========================================================================
    # RETRY RETRIEVAL
    # =========================================================================

    elif (
        eligible_quality
        and qr.decision == "RETRY_RETRIEVAL"
        and not result.handoff
        and not result.general_question
    ):
        retry_attempted = True

        qr2 = None
        wider = None

        try:
            retry_top_k = (
                _cfg.TOP_K
                * max(
                    1,
                    _cfg.QUALITY_RETRY_TOP_K_MULTIPLIER,
                )
            )

            wider = agent.retriever.retrieve(
                user_message,
                top_k=retry_top_k,
            )

            wider_hits = list(
                wider.hits or []
            )

            texts = [
                h.chunk.text
                for h in wider_hits
            ]

            best = max(
                [
                    float(h.score)
                    for h in wider_hits
                ],
                default=None,
            )

            wider_sources = list(
                dict.fromkeys(
                    h.chunk.source_file
                    for h in wider_hits
                    if h.chunk.source_file
                )
            )

            if wider_sources:
                result.sources = wider_sources

            qr2 = assess(
                result.answer,
                result.sources,
                False,
                eligible=True,
                question=user_message,
                evidence=texts,
                retrieval_score=best,
            )

            retry_decision = qr2.decision
            retry_grounding = qr2.grounding_score
            retry_policy = qr2.policy_check
            retry_pii = qr2.pii_check
            retry_confidence = qr2.confidence
            retry_retrieval = qr2.retrieval_score
            retry_relevance = qr2.relevance_score
            retry_details = _copy_json_dict(
                qr2.details or None
            )

        except Exception:
            logger.exception(
                "QUALITY_GUARD_RETRY_ERROR"
            )

            qr2 = None
            wider = None

        if (
            qr2 is not None
            and qr2.decision == "ALLOW"
        ):
            retrieval = wider
            use_evidence = True
            qr = qr2
            fallback_action = "search_again"

        elif needs_clarification(
            user_message
        ):
            result.answer = CLARIFICATION_TEXT

            qr = assess(
                result.answer,
                [],
                False,
                eligible=False,
            )

            qr.decision = "ASK_CLARIFICATION"
            qr.confidence = "LOW"

            fallback_action = (
                "ask_clarification"
            )

        else:
            #
            # The order lookup is authoritative transactional data. The
            # authenticated DB order tool has already:
            #
            #   1. validated the order ID,
            #   2. identified the authenticated user,
            #   3. enforced order ownership,
            #   4. returned customer-safe order data.
            #
            # Therefore the generic RAG grounding fallback must never
            # overwrite a successful order response merely because there
            # are no Knowledge Base citations.
            # --------------------------------------------------------------

            order_lookup_match = re.search(
                r"\b(?:ORD[-\s]?\d{3,6}|ORDER[-#\s]?\d{3,6}|#\d{3,6})\b",
                user_message or "",
                flags=re.IGNORECASE,
            )

            if order_lookup_match is not None:
                fallback_action = "order_lookup_preserved"

                result.handoff = False
                result.handoff_reason = None
                result.insufficient_information = False

                qr = assess(
                    result.answer,
                    result.sources,
                    False,
                    eligible=False,
                )

            else:
                result.answer = (
                    "I couldn't verify that information reliably "
                    "from the available sources. A support specialist "
                    "can confirm it for you."
                )

                result.handoff = True
                result.handoff_reason = (
                    "AI response failed the grounding quality check "
                    "after wider retrieval."
                )

                qr = assess(
                    result.answer,
                    result.sources,
                    True,
                    eligible=True,
                )

                fallback_action = "human_handoff"
    # =========================================================================
    # ACTION CENTER
    # =========================================================================

    if _cfg.AI_AGENT_ACTIONS_ENABLED:

        if explicit_escalation_request:
            action_result = _propose_escalate_ticket(
                db,
                user_id=user_id,
                conversation_id=conversation.id,
                user_message=user_message,
            )

        elif (
            automatic_delay_proposal
            or explicit_ticket_request
        ):
            action_result = (
                _propose_create_support_ticket(
                    db,
                    user_id=user_id,
                    conversation_id=conversation.id,
                    user_message=user_message,
                    explicit_request=(
                        explicit_ticket_request
                    ),
                )
            )

    action_waiting_for_approval = (
        (
            explicit_ticket_request
            or explicit_escalation_request
        )
        and _action_requires_approval(
            action_result
        )
    )

    # =========================================================================
    # APPROVAL-PENDING RESPONSE
    # =========================================================================

    if (
        explicit_ticket_request
        and not explicit_escalation_request
        and action_waiting_for_approval
    ):
        _set_pending_ticket_response(
            result
        )

        fallback_action = (
            "action_center_approval_required"
        )

        qr = assess(
            result.answer,
            result.sources,
            False,
            eligible=False,
        )

    elif (
        explicit_escalation_request
        and action_waiting_for_approval
    ):
        _set_pending_escalation_response(
            result,
            ticket_number=_extract_ticket_number(
                user_message
            ),
        )

        fallback_action = (
            "action_center_approval_required"
        )

        qr = assess(
            result.answer,
            result.sources,
            False,
            eligible=False,
        )

    # =========================================================================
    # FINAL QUALITY TRACE
    # =========================================================================

    final_decision = qr.decision

    quality_trace = _build_quality_trace(
        initial_decision=initial_decision,
        initial_grounding_score=initial_grounding,
        initial_policy_check=initial_policy,
        initial_pii_check=initial_pii,
        initial_confidence=initial_confidence,
        initial_retrieval_score=initial_retrieval,
        initial_relevance_score=initial_relevance,
        initial_details=initial_details,

        retry_attempted=retry_attempted,
        retry_decision=retry_decision,
        retry_grounding_score=retry_grounding,
        retry_policy_check=retry_policy,
        retry_pii_check=retry_pii,
        retry_confidence=retry_confidence,
        retry_retrieval_score=retry_retrieval,
        retry_relevance_score=retry_relevance,
        retry_details=retry_details,

        final_decision=final_decision,
        fallback_action=fallback_action,
    )

    quality_trace = _copy_json_dict(
        quality_trace
    )

    logger.info(
        "QUALITY_TRACE_RUNTIME "
        "conversation_id=%s "
        "keys=%s",
        conversation.id,
        list(quality_trace.keys()),
    )

    # =========================================================================
    # ASSISTANT METADATA
    # =========================================================================

    assistant_row.content = result.answer

    assistant_row.meta = {
        **(
            assistant_row.meta or {}
        ),

        "quality": {
            "grounding_score":
                qr.grounding_score,

            "policy_check":
                qr.policy_check,

            "pii_check":
                qr.pii_check,

            "confidence":
                qr.confidence,

            "decision":
                final_decision,

            "final_decision":
                final_decision,

            "fallback_action":
                fallback_action,

            "initial_decision":
                initial_decision,

            "initial_grounding_score":
                initial_grounding,

            "initial_policy_check":
                initial_policy,

            "initial_pii_check":
                initial_pii,

            "initial_confidence":
                initial_confidence,

            "initial_retrieval_score":
                initial_retrieval,

            "initial_relevance_score":
                initial_relevance,

            "initial_details":
                _copy_json_dict(
                    initial_details
                ),

            "retry_attempted":
                retry_attempted,

            "retry_decision":
                retry_decision,

            "retry_grounding_score":
                retry_grounding,

            "retry_policy_check":
                retry_policy,

            "retry_pii_check":
                retry_pii,

            "retry_confidence":
                retry_confidence,

            "retry_retrieval_score":
                retry_retrieval,

            "retry_relevance_score":
                retry_relevance,

            "retry_details":
                _copy_json_dict(
                    retry_details
                ),
        },

        "quality_trace":
            _copy_json_dict(
                quality_trace
            ),

        "sources":
            result.sources,

        "handoff":
            result.handoff,

        "handoff_reason":
            result.handoff_reason,

        "insufficient_information":
            result.insufficient_information,

        "classification": {
            "intent":
                classification.intent,

            "sentiment":
                classification.sentiment,

            "priority":
                classification.priority,

            "topic":
                classification.topic,

            "confidence":
                classification.confidence,
        },

        "action_center": {
            "explicit_ticket_request":
                explicit_ticket_request,

            "explicit_escalation_request":
                explicit_escalation_request,

            "action_created":
                action_result is not None,

            "approval_required":
                action_waiting_for_approval,
        },
    }

    flag_modified(
        assistant_row,
        "meta",
    )

    db.flush()

    # =========================================================================
    # AI QUALITY CHECK
    # =========================================================================

    if _cfg.QUALITY_GUARD_ENABLED:

        quality_details = _copy_json_dict(
            qr.details or {}
        )

        if not isinstance(
            quality_details,
            dict,
        ):
            quality_details = {}

        quality_details[
            "quality_trace"
        ] = _copy_json_dict(
            quality_trace
        )

        quality_details[
            "quality_trace_version"
        ] = 3

        quality_details.update(
            {
                "initial_decision":
                    initial_decision,

                "initial_grounding_score":
                    initial_grounding,

                "initial_policy_check":
                    initial_policy,

                "initial_pii_check":
                    initial_pii,

                "initial_confidence":
                    initial_confidence,

                "initial_retrieval_score":
                    initial_retrieval,

                "initial_relevance_score":
                    initial_relevance,

                "initial_details":
                    _copy_json_dict(
                        initial_details
                    ),

                "retry_attempted":
                    retry_attempted,

                "retry_decision":
                    retry_decision,

                "retry_grounding_score":
                    retry_grounding,

                "retry_policy_check":
                    retry_policy,

                "retry_pii_check":
                    retry_pii,

                "retry_confidence":
                    retry_confidence,

                "retry_retrieval_score":
                    retry_retrieval,

                "retry_relevance_score":
                    retry_relevance,

                "retry_details":
                    _copy_json_dict(
                        retry_details
                    ),

                "final_decision":
                    final_decision,

                "fallback_action":
                    fallback_action,
            }
        )

        quality_check = AIQualityCheck(
            conversation_id=conversation.id,
            message_id=assistant_row.id,
            grounding_score=qr.grounding_score,
            policy_check=qr.policy_check,
            pii_check=qr.pii_check,
            confidence=qr.confidence,
            decision=final_decision,
            retrieval_score=qr.retrieval_score,
            relevance_score=qr.relevance_score,
            fallback_action=fallback_action,
            details=quality_details,
        )

        db.add(
            quality_check
        )

        db.flush()

        logger.info(
            "QUALITY_CHECK_PERSISTED "
            "message_id=%s "
            "trace_version=%s",
            assistant_row.id,
            quality_details.get(
                "quality_trace_version"
            ),
        )

    # =========================================================================
    # RAG CITATIONS
    # =========================================================================

    try:
        if (
            _cfg.RAG_CITATIONS_ENABLED
            and result.sources
            and final_decision == "ALLOW"
        ):
            citations = (
                build_citations(
                    retrieval,
                    only_files=result.sources,
                )
                if retrieval is not None
                else []
            )

            for citation in citations:
                db.add(
                    ConversationCitation(
                        conversation_id=conversation.id,
                        message_id=assistant_row.id,
                        citation_id=citation["id"],
                        document_name=citation["document"],
                        document_version=citation.get(
                            "document_version"
                        ),
                        heading=citation.get(
                            "heading"
                        ),
                        source_type=citation.get(
                            "source_type",
                            "knowledge_base",
                        ),
                        relevant_passage=citation.get(
                            "passage"
                        ),
                        updated_at=citation.get(
                            "updated_at"
                        ),
                        relevance_score=citation.get(
                            "relevance_score"
                        ),
                    )
                )

    except Exception:
        logger.exception(
            "citation persistence failed"
        )

    # =========================================================================
    # USAGE
    # =========================================================================

    from app.enterprise.usage import (
        record_usage
    )

    record_usage(
        db,
        user_id=user_id,
        conversation_id=conversation.id,
        model=(
            "mock-llm"
            if getattr(
                _cfg,
                "USE_MOCK_LLM",
                False,
            )
            else (
                collector.models[0]
                if collector.models
                else _cfg.CHAT_MODEL
            )
        ),
        feature="chat",
        endpoint="conversations.message",
        latency_ms=latency_ms,
        status="success",
        input_tokens=collector.input_tokens,
        output_tokens=collector.output_tokens,
        metadata={
            "routing_category": (
                decision.category
                if decision
                else None
            ),
            "routing_fallback": (
                decision.fallback_used
                if decision
                else False
            ),
            "llm_attempts": collector.attempts,
            "llm_retry_count": collector.retry_count,
            "llm_fallback_used": collector.fallback_used,
            "llm_fallback_models": list(
                collector.fallback_models
            ),
            "llm_transient_errors": collector.transient_errors,
            "llm_failover_exhausted": collector.failover_exhausted,
        },
    )

    # =========================================================================
    # HUMAN HANDOFF
    # =========================================================================

    ticket_number = None

    if (
        result.handoff
        and not action_waiting_for_approval
    ):
        ticket = (
            ticket_service.create_ticket_from_handoff(
                db,
                user_id=user_id,
                conversation_id=conversation.id,
                handoff_reason=(
                    result.handoff_reason
                    or (
                        "The assistant recommended "
                        "human follow-up."
                    )
                ),
                last_user_message=user_message,
            )
        )

        ticket_number = (
            ticket.ticket_number
        )

        create_notification(
            db,
            user_id=user_id,
            type="handoff_requested",
            title=(
                f"Support ticket "
                f"#{ticket.ticket_number} opened"
            ),
            message=(
                "A support specialist has been "
                "looped in on your conversation."
            ),
            data={
                "ticket_id":
                    str(ticket.id),

                "ticket_number":
                    ticket.ticket_number,

                "conversation_id":
                    str(conversation.id),
            },
        )

    # =========================================================================
    # FINAL ORM FLUSH
    # =========================================================================

    db.flush()

    # =========================================================================
    # FINAL QUALITY TRACE PERSISTENCE
    # =========================================================================

    if _cfg.QUALITY_GUARD_ENABLED:
        _persist_final_quality_trace(
            db,
            assistant_row=assistant_row,
            quality_trace=quality_trace,
        )

    # =========================================================================
    # FINAL RETURN
    # =========================================================================

    return (
        user_row,
        assistant_row,
        result,
        ticket_number,
    )
