"""Notification-delivery Celery tasks (Phase 3, Feature 24). Kept off the
request path -- `app.notifications.service.create_notification` enqueues
this rather than calling the email provider inline, so a slow/flaky SMTP
call never blocks the ticket/handoff/order-update request that triggered
it.
"""
from __future__ import annotations

import logging

from app.workers.celery_app import celery_app
from app.workers.tasks.job_tracking import get_or_create_job, track_job

logger = logging.getLogger("aster_row.workers.notifications")


@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def send_notification_email(self, notification_id: str, to_email: str, subject: str, body: str) -> dict:
    """Idempotent per notification_id: a retried/duplicate submission of
    the same notification is deduped via `dedupe_key`, so a Celery retry
    (or an at-least-once redelivery) can never send the same email twice.
    """
    job, already_done = get_or_create_job(
        "send_notification_email", dedupe_key=f"notify-email:{notification_id}",
        payload={"notification_id": notification_id, "to_email": to_email, "subject": subject},
    )
    if already_done:
        return {"status": "skipped_duplicate", "job_id": str(job.id)}

    from app.monitoring.metrics import metrics
    from app.notifications.providers import EmailDeliveryError, get_email_provider

    with track_job(job.id):
        try:
            get_email_provider().send(to_email, subject, body)
        except EmailDeliveryError as exc:
            metrics.record_notification_failure()
            logger.warning("Notification email delivery failed, will retry: %s", exc)
            raise self.retry(exc=exc)
    return {"status": "sent", "job_id": str(job.id)}
