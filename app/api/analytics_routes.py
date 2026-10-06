"""Admin-only AI analytics routes (Phase 2, Feature 16)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import config
from app.auth.deps import require_roles
from app.security.rate_limit_deps import rate_limit_by_user
from app.db.base import get_db
from app.db.models import User
from app.services import analytics_service

router = APIRouter(
    prefix="/admin/analytics",
    tags=["analytics"],
    dependencies=[Depends(rate_limit_by_user("analytics", "RATE_LIMIT_ANALYTICS"))],
)

_ADMIN = require_roles("admin", "super_admin")


def _resolve_range(range_: str, start_date: str | None, end_date: str | None) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    if range_ == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now
    if range_ == "7d":
        return now - timedelta(days=7), now
    if range_ == "30d":
        return now - timedelta(days=30), now
    if range_ == "custom":
        if not start_date or not end_date:
            raise HTTPException(status_code=400, detail="custom range requires start_date and end_date (YYYY-MM-DD).")
        try:
            start = datetime.combine(date.fromisoformat(start_date), datetime.min.time(), tzinfo=timezone.utc)
            end = datetime.combine(date.fromisoformat(end_date), datetime.max.time(), tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail="start_date/end_date must be YYYY-MM-DD.")
        if end < start:
            raise HTTPException(status_code=400, detail="end_date must not be before start_date.")
        return start, end
    raise HTTPException(status_code=400, detail=f"Unknown range: {range_}")


@router.get("/summary")
def get_summary(
    range: str = "7d",
    start_date: str | None = None,
    end_date: str | None = None,
    user: User = Depends(_ADMIN),
    db: Session = Depends(get_db),
) -> dict:
    start, end = _resolve_range(range, start_date, end_date)
    return analytics_service.summary(db, start=start, end=end)


@router.get("")
def get_analytics(
    range: str = "7d",
    start_date: str | None = None,
    end_date: str | None = None,
    user: User = Depends(_ADMIN),
    db: Session = Depends(get_db),
) -> dict:
    start, end = _resolve_range(range, start_date, end_date)
    return {
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "summary": analytics_service.summary(db, start=start, end=end),
        "timeseries": analytics_service.timeseries(db, start=start, end=end),
    }
