"""Feature 16: AI analytics.

Every number here comes from a real source: Postgres (conversations,
messages, tickets, feedback) for anything conversation/ticket-shaped, and
the existing per-turn trace log (`logs/trace.jsonl`, see
`app/logging_utils.py`) for retrieval/performance/safety signals that
aren't persisted anywhere else -- there is no separate fabricated metrics
store. Where this app genuinely doesn't track a concept the brief names
(e.g. a dedicated PII-leak detector), the corresponding field says so in
`app/api/analytics_routes.py`'s response rather than inventing a number.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import AIFeedback, Conversation, Message, Ticket
from app.logging_utils import TraceLogger


def _percentile(sorted_values: list[float], pct: float) -> float | None:
    if not sorted_values:
        return None
    k = (len(sorted_values) - 1) * pct
    f, c = int(k), min(int(k) + 1, len(sorted_values) - 1)
    if f == c:
        return round(sorted_values[f], 1)
    return round(sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f), 1)


def _trace_rows_in_range(start: datetime, end: datetime) -> list[dict]:
    rows = TraceLogger().read_all()
    start_ts, end_ts = start.timestamp(), end.timestamp()
    return [r for r in rows if start_ts <= r.get("timestamp", 0) <= end_ts]


def summary(db: Session, *, start: datetime, end: datetime) -> dict:
    conversations_q = db.query(Conversation).filter(Conversation.created_at >= start, Conversation.created_at <= end)
    total_conversations = conversations_q.count()
    active_conversations = conversations_q.filter(Conversation.status == "active").count()

    assistant_messages = (
        db.query(Message)
        .filter(Message.role == "assistant", Message.created_at >= start, Message.created_at <= end)
        .all()
    )
    ai_resolved = sum(1 for m in assistant_messages if not (m.meta or {}).get("handoff"))
    human_handoff = sum(1 for m in assistant_messages if (m.meta or {}).get("handoff"))
    no_source_responses = sum(1 for m in assistant_messages if not (m.meta or {}).get("sources"))

    unresolved_tickets = (
        db.query(Ticket)
        .filter(Ticket.status.in_(["open", "in_progress", "waiting_for_customer"]), Ticket.created_at >= start, Ticket.created_at <= end)
        .count()
    )

    feedback_q = db.query(AIFeedback).filter(AIFeedback.created_at >= start, AIFeedback.created_at <= end)
    positive_feedback = feedback_q.filter(AIFeedback.rating == "positive").count()
    negative_feedback = feedback_q.filter(AIFeedback.rating == "negative").count()
    total_feedback = positive_feedback + negative_feedback
    satisfaction_rate = round(positive_feedback / total_feedback, 3) if total_feedback else None

    trace_rows = _trace_rows_in_range(start, end)
    total_ms_values = sorted(r["durations_ms"]["total_ms"] for r in trace_rows if r.get("durations_ms", {}).get("total_ms") is not None)
    avg_response_ms = round(sum(total_ms_values) / len(total_ms_values), 1) if total_ms_values else None

    retrieval_attempts = len(trace_rows)
    retrieval_hits = sum(1 for r in trace_rows if r.get("retrieved"))
    low_confidence_queries = retrieval_attempts - retrieval_hits
    doc_counter: Counter[str] = Counter()
    for r in trace_rows:
        for chunk in r.get("retrieved", []):
            doc_counter[chunk["source_file"]] += 1
    top_documents = [{"source_file": f, "count": c} for f, c in doc_counter.most_common(10)]

    injection_attempts = sum(1 for r in trace_rows if r.get("injection_patterns_flagged"))
    policy_conflicts = sum(1 for r in trace_rows if r.get("conflict_detected"))

    return {
        "conversations": {
            "total": total_conversations,
            "active": active_conversations,
            "new": total_conversations,  # every conversation in-range is "new" for that range by definition
        },
        "resolution": {
            "ai_resolved": ai_resolved,
            "human_handoff": human_handoff,
            "unresolved": unresolved_tickets,
        },
        "feedback": {
            "positive": positive_feedback,
            "negative": negative_feedback,
            "satisfaction_rate": satisfaction_rate,
        },
        "performance": {
            "average_response_ms": avg_response_ms,
            "p50_ms": _percentile(total_ms_values, 0.5),
            "p95_ms": _percentile(total_ms_values, 0.95),
            # This app streams an already-fully-computed answer (see
            # app/api/conversations_routes.py's /messages/stream docstring)
            # rather than generating tokens progressively, so a streamed
            # turn's total compute time is the same turn the trace log
            # already measures -- there's no second, distinct "streaming
            # completion time" number this app actually produces.
            "streaming_completion_ms": avg_response_ms,
        },
        "rag": {
            "retrieval_success": retrieval_hits,
            "retrieval_attempts": retrieval_attempts,
            "low_confidence_queries": low_confidence_queries,
            "no_source_responses": no_source_responses,
            "top_retrieved_documents": top_documents,
        },
        "safety": {
            # This app has no separate output-blocking layer -- unsafe asks
            # are refused via the agent's prompted rules (see
            # app/agent.py's BASE_SYSTEM_PROMPT), not hard-blocked before
            # reaching the model. The closest real signal to "blocked
            # requests" is how many turns tripped the injection-pattern
            # detector in app/safety.py.
            "blocked_requests": injection_attempts,
            "prompt_injection_attempts": injection_attempts,
            # PII is prevented structurally by the field-allowlist in
            # app/services/order_service.py (a customer can never receive
            # fields outside that allowlist), not detected/logged at
            # request time, so there is no per-event count to report here.
            "pii_protection_events": 0,
            "policy_conflicts": policy_conflicts,
        },
    }


def timeseries(db: Session, *, start: datetime, end: datetime) -> dict:
    """Daily buckets for the chart section (Feature 16: "Conversations over
    time", "AI vs Human resolution", "Feedback trend", "Handoff trend")."""
    days = []
    cursor = start.date()
    while cursor <= end.date():
        days.append(cursor)
        cursor += timedelta(days=1)

    conv_rows = db.query(func.date(Conversation.created_at), func.count(Conversation.id)).filter(
        Conversation.created_at >= start, Conversation.created_at <= end
    ).group_by(func.date(Conversation.created_at)).all()
    conv_by_day = {d: c for d, c in conv_rows}

    msg_rows = (
        db.query(func.date(Message.created_at), Message.meta)
        .filter(Message.role == "assistant", Message.created_at >= start, Message.created_at <= end)
        .all()
    )
    ai_by_day: Counter = Counter()
    handoff_by_day: Counter = Counter()
    for d, meta in msg_rows:
        if (meta or {}).get("handoff"):
            handoff_by_day[d] += 1
        else:
            ai_by_day[d] += 1

    fb_rows = db.query(func.date(AIFeedback.created_at), AIFeedback.rating).filter(
        AIFeedback.created_at >= start, AIFeedback.created_at <= end
    ).all()
    positive_by_day: Counter = Counter()
    negative_by_day: Counter = Counter()
    for d, rating in fb_rows:
        (positive_by_day if rating == "positive" else negative_by_day)[d] += 1

    return {
        "days": [d.isoformat() for d in days],
        "conversations": [conv_by_day.get(d, 0) for d in days],
        "ai_resolved": [ai_by_day.get(d, 0) for d in days],
        "human_handoff": [handoff_by_day.get(d, 0) for d in days],
        "positive_feedback": [positive_by_day.get(d, 0) for d in days],
        "negative_feedback": [negative_by_day.get(d, 0) for d in days],
    }
