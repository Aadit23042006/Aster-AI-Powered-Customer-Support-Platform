"""Feature 17: AI Trace Viewer, read-only over the existing per-turn trace
log (`logs/trace.jsonl`, see `app/logging_utils.py`) -- no new trace
storage is introduced; the log already written on every turn (for both the
CLI and the web app, since `app.agent.Agent.handle_turn` is shared) is the
single source of truth.

Safety: `app.logging_utils.TurnTrace` already never records the system
prompt, hidden reasoning, or secrets (see its module docstring) -- this
module additionally never surfaces `history_included` in the *list* view
(only in one trace's detail view, where it's exactly the prior turns of
that same conversation an admin reviewing this trace would need, not
hidden model reasoning).
"""
from __future__ import annotations

from datetime import datetime, timezone

from app import config
from app.logging_utils import TraceLogger

MODEL_IDENTIFIER = config.CHAT_MODEL


def _final_status(row: dict) -> str:
    if row.get("error"):
        return "error"
    if row.get("insufficient_information"):
        return "insufficient_information"
    if row.get("handoff"):
        return "handoff"
    return "answered"


def _safety_event(row: dict) -> bool:
    return bool(row.get("injection_patterns_flagged")) or bool(row.get("conflict_detected"))


def _retrieval_outcome(row: dict) -> str:
    hits = row.get("retrieved") or []
    if not hits:
        return "none"
    return "success"


def to_summary(row: dict) -> dict:
    """Safe, list-view fields only (Feature 17: 'safe execution metadata',
    no history_included / no full retrieved chunk text)."""
    durations = row.get("durations_ms") or {}
    return {
        "trace_id": row.get("trace_id") or "",
        "request_id": row.get("trace_id") or "",
        "conversation_id": row.get("session_id"),
        "timestamp": row.get("timestamp"),
        "timestamp_iso": datetime.fromtimestamp(row["timestamp"], tz=timezone.utc).isoformat() if row.get("timestamp") else None,
        "duration_ms": durations.get("total_ms"),
        "model": MODEL_IDENTIFIER,
        "retrieval_count": len(row.get("retrieved") or []),
        "retrieval_outcome": _retrieval_outcome(row),
        "tool_calls": len(row.get("tool_calls") or []),
        "safety_event": _safety_event(row),
        "handoff": bool(row.get("handoff")),
        "status": _final_status(row),
    }


def to_detail(row: dict) -> dict:
    """Everything from `to_summary` plus the per-stage timeline and safe
    conversational content -- still never the system prompt (that's never
    written to the log at all, see `app.logging_utils.TurnTrace`)."""
    durations = row.get("durations_ms") or {}
    total = durations.get("total_ms") or 0
    timeline = []
    t = row.get("timestamp", 0)
    stage_order = [
        ("request_received", 0.0),
        ("safety_check", durations.get("retrieval_ms", 0) * 0.01),  # safety check runs before retrieval, effectively instant
        ("retrieval_completed", durations.get("retrieval_ms", 0)),
        ("tool_calls_completed", durations.get("retrieval_ms", 0) + durations.get("tool_ms", 0)),
        ("generation_completed", durations.get("retrieval_ms", 0) + durations.get("tool_ms", 0) + durations.get("generation_ms", 0)),
        ("response_finalized", total),
    ]
    for label, offset_ms in stage_order:
        timeline.append({"stage": label, "offset_ms": round(offset_ms, 2)})

    summary = to_summary(row)
    return {
        **summary,
        "durations_ms": durations,
        "timeline": timeline,
        "user_message": row.get("user_message"),
        "final_response": row.get("final_response"),
        "retrieved_sources": [
            {"source_file": c["source_file"], "heading": c.get("heading"), "score": c.get("score"), "is_active_official": c.get("is_active_official")}
            for c in (row.get("retrieved") or [])
        ],
        "tool_call_details": [
            {"name": tc["name"], "success": "error" not in (tc.get("result") or {})}
            for tc in (row.get("tool_calls") or [])
        ],
        "injection_patterns_flagged": row.get("injection_patterns_flagged") or [],
        "conflict_detected": bool(row.get("conflict_detected")),
        "handoff_reason": row.get("handoff_reason"),
        "insufficient_information": bool(row.get("insufficient_information")),
        "error": row.get("error"),
        "history_turns": len(row.get("history_included") or []),
    }


def list_traces(
    *,
    trace_id: str | None = None,
    conversation_id: str | None = None,
    status: str | None = None,
    handoff: bool | None = None,
    safety_event: bool | None = None,
    retrieval_outcome: str | None = None,
    min_latency_ms: float | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    page: int = 1,
    page_size: int = 25,
) -> tuple[list[dict], int]:
    rows = TraceLogger().read_all()
    rows.sort(key=lambda r: r.get("timestamp", 0), reverse=True)

    def matches(row: dict) -> bool:
        if trace_id and row.get("trace_id") != trace_id:
            return False
        if conversation_id and row.get("session_id") != conversation_id:
            return False
        if start and row.get("timestamp", 0) < start.timestamp():
            return False
        if end and row.get("timestamp", 0) > end.timestamp():
            return False
        summary = to_summary(row)
        if status and summary["status"] != status:
            return False
        if handoff is not None and summary["handoff"] != handoff:
            return False
        if safety_event is not None and summary["safety_event"] != safety_event:
            return False
        if retrieval_outcome and summary["retrieval_outcome"] != retrieval_outcome:
            return False
        if min_latency_ms is not None and (summary["duration_ms"] or 0) < min_latency_ms:
            return False
        return True

    filtered = [r for r in rows if matches(r)]
    total = len(filtered)
    page_size = min(max(page_size, 1), 100)
    start_idx = (page - 1) * page_size
    page_rows = filtered[start_idx : start_idx + page_size]
    return [to_summary(r) for r in page_rows], total


def get_trace(trace_id: str) -> dict | None:
    for row in TraceLogger().read_all():
        if row.get("trace_id") == trace_id:
            return to_detail(row)
    return None
