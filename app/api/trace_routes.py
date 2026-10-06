"""Admin-only AI Trace Viewer routes (Phase 2, Feature 17).

Never exposes chain-of-thought, the system prompt, or secrets -- see
`app/services/trace_service.py`'s module docstring for exactly what is and
isn't in the underlying trace log this reads from.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.deps import require_roles
from app.db.base import get_db
from app.db.models import User
from app.services import trace_service

router = APIRouter(prefix="/admin/traces", tags=["traces"])

_ADMIN = require_roles("admin", "super_admin")


@router.get("")
def list_traces(
    trace_id: str | None = None,
    conversation_id: str | None = None,
    status: str | None = None,
    handoff: bool | None = None,
    safety_event: bool | None = None,
    retrieval_outcome: str | None = None,
    min_latency_ms: float | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = 1,
    page_size: int = 25,
    user: User = Depends(_ADMIN),
    db: Session = Depends(get_db),
) -> dict:
    start = end = None
    try:
        if date_from:
            start = datetime.combine(date.fromisoformat(date_from), datetime.min.time(), tzinfo=timezone.utc)
        if date_to:
            end = datetime.combine(date.fromisoformat(date_to), datetime.max.time(), tzinfo=timezone.utc)
    except ValueError:
        raise HTTPException(status_code=400, detail="date_from/date_to must be YYYY-MM-DD.")

    items, total = trace_service.list_traces(
        trace_id=trace_id,
        conversation_id=conversation_id,
        status=status,
        handoff=handoff,
        safety_event=safety_event,
        retrieval_outcome=retrieval_outcome,
        min_latency_ms=min_latency_ms,
        start=start,
        end=end,
        page=page,
        page_size=page_size,
    )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/{trace_id}")
def get_trace(trace_id: str, user: User = Depends(_ADMIN), db: Session = Depends(get_db)) -> dict:
    trace = trace_service.get_trace(trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail="Trace not found.")
    return trace
