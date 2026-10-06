"""Background analytics aggregation (Phase 3, Feature 24).

The existing Phase 2 `/analytics` endpoint (`app/services/analytics_service.py`)
computes its numbers on demand, synchronously, straight from the
`messages`/`ai_feedback`/`tickets` tables -- that's deliberately unchanged
here (a working, already-tested read path). What's genuinely new async
work is a periodic pre-aggregation pass a future dashboard could read from
instead of recomputing on every request; this task is the seam for that,
kept minimal since Phase 2's on-demand queries are still what the live
`/analytics` route uses today.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.workers.celery_app import celery_app
from app.workers.tasks.job_tracking import get_or_create_job, track_job

logger = logging.getLogger("aster_row.workers.analytics")


@celery_app.task
def aggregate_daily_analytics(day: str | None = None) -> dict:
    """Recomputes and logs the same summary `app.services.analytics_service
    .get_summary` already exposes synchronously, for the given UTC day
    (defaults to today). Deduped per day so re-running it is a no-op."""
    day = day or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    job, already_done = get_or_create_job("aggregate_daily_analytics", dedupe_key=f"analytics-agg:{day}", payload={"day": day})
    if already_done:
        return {"status": "skipped_duplicate", "job_id": str(job.id)}

    result = {}
    with track_job(job.id):
        from datetime import timedelta

        from app.db.base import SessionLocal
        from app.services import analytics_service

        db = SessionLocal()
        try:
            start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            end = start + timedelta(days=1)
            summary = analytics_service.summary(db, start=start, end=end)
            result = {"day": day, "summary": summary}
            logger.info("Daily analytics aggregated for %s", day)
        finally:
            db.close()
    return {"status": "done", "job_id": str(job.id), **result}
