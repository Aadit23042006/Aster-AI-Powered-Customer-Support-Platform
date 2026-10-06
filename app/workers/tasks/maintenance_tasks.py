"""Scheduled maintenance tasks (Phase 3, Feature 24). Run via Celery beat
(see the `beat_schedule` in `app/workers/celery_app.py`) rather than inline
in a request -- cleanup work should never compete with customer-facing
request latency.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.db.base import SessionLocal
from app.db.models import AuthSession, PasswordResetToken
from app.workers.celery_app import celery_app
from app.workers.tasks.job_tracking import get_or_create_job, track_job

logger = logging.getLogger("aster_row.workers.maintenance")


@celery_app.task
def cleanup_expired_auth_records() -> dict:
    """Deletes refresh-token sessions and password-reset tokens that are
    already expired. Nothing time-sensitive depends on this -- an expired
    token is already rejected by `app/api/auth_routes.py` regardless of
    whether its row still exists -- this is pure housekeeping so those
    tables don't grow forever. Deduped per hour so re-running the beat
    schedule (or a retry) within the same hour is a no-op."""
    dedupe_key = f"auth-cleanup:{datetime.now(timezone.utc).strftime('%Y-%m-%d-%H')}"
    job, already_done = get_or_create_job("cleanup_expired_auth_records", dedupe_key=dedupe_key)
    if already_done:
        return {"status": "skipped_duplicate", "job_id": str(job.id)}

    result = {}
    with track_job(job.id):
        db = SessionLocal()
        try:
            cutoff = datetime.now(timezone.utc)
            sessions_deleted = db.query(AuthSession).filter(AuthSession.expires_at < cutoff).delete(synchronize_session=False)
            tokens_deleted = db.query(PasswordResetToken).filter(PasswordResetToken.expires_at < cutoff).delete(synchronize_session=False)
            db.commit()
            result = {"sessions_deleted": sessions_deleted, "reset_tokens_deleted": tokens_deleted}
            logger.info("Auth cleanup: %s", result)
        finally:
            db.close()
    return {"status": "done", "job_id": str(job.id), **result}
