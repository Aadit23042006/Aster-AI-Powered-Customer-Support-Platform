"""Shared `background_jobs` row helpers, used by every Celery task module
so job status tracking (queued/running/success/failed/retrying) and
idempotency (via `dedupe_key`) work identically everywhere instead of each
task module reinventing it."""
from __future__ import annotations

from contextlib import contextmanager

from app.db.base import SessionLocal
from app.db.models import BackgroundJob


def get_or_create_job(task_name: str, dedupe_key: str | None, payload: dict | None = None) -> tuple[BackgroundJob, bool]:
    """Returns (job, already_done). If a job with this dedupe_key already
    reached 'success', the caller should skip re-doing the work --
    that's the idempotency guarantee for a retried/duplicate submission of
    the same logical job (e.g. "send this exact notification")."""
    db = SessionLocal()
    try:
        job = None
        if dedupe_key:
            job = db.query(BackgroundJob).filter(BackgroundJob.dedupe_key == dedupe_key).first()
        if job is not None:
            already_done = job.status == "success"
            return job, already_done
        job = BackgroundJob(task_name=task_name, dedupe_key=dedupe_key, payload=payload, status="queued")
        db.add(job)
        db.commit()
        db.refresh(job)
        return job, False
    finally:
        db.close()


@contextmanager
def track_job(job_id):
    """Marks the job 'running' on entry, 'success' on clean exit, 'failed'
    (with the exception message) if the task body raises -- re-raising
    afterwards so Celery's own retry machinery still sees the failure."""
    db = SessionLocal()
    try:
        job = db.get(BackgroundJob, job_id)
        job.status = "running"
        job.attempts += 1
        db.commit()
        try:
            yield job
            job.status = "success"
            db.commit()
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)[:2000]
            db.commit()
            raise
    finally:
        db.close()
