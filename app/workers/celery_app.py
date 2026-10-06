"""Celery application (Phase 3, Feature 24).

Redis is used as both broker and result backend -- it's already a hard
dependency for rate limiting (Feature 20), so this doesn't introduce a
second piece of infrastructure. `task_always_eager` is turned on
automatically under pytest (`PYTEST_CURRENT_TEST` is set by pytest itself
for the duration of a test run) so the test suite can assert on task
behavior without a separate worker process or broker connection -- the
task body still runs for real, just synchronously and in-process.

Existing Phase 2 async work (knowledge-base indexing, evaluation runs)
deliberately keeps its own execution model rather than being moved onto
Celery -- both were already-tested, already-justified design choices (see
the docstrings on `app/services/indexing_service.py` and
`evaluation_service.run_evaluation`, the latter explicitly explaining why
it's synchronous: a deferred BackgroundTask result can't be reflected in
the response that scheduled it). Moving them would be exactly the kind of
"replace working functionality to introduce a new framework" the Phase 3
brief says not to do. Celery here is used for the two genuinely new
categories of async work Phase 3 adds: notification delivery and periodic
maintenance.
"""
from __future__ import annotations

import os

from celery import Celery

from app import config

_EAGER = bool(os.environ.get("PYTEST_CURRENT_TEST")) or not config.WORKERS_ENABLED

celery_app = Celery(
    "aster_row",
    broker=config.CELERY_BROKER_URL,
    backend=config.CELERY_RESULT_BACKEND,
    include=[
        "app.workers.tasks.notification_tasks",
        "app.workers.tasks.maintenance_tasks",
        "app.workers.tasks.analytics_tasks",
    ],
)

celery_app.conf.update(
    task_always_eager=_EAGER,
    task_eager_propagates=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_retry_delay=5,
    broker_connection_retry_on_startup=True,
    timezone="UTC",
)

celery_app.conf.beat_schedule = {
    "cleanup-expired-auth-records-hourly": {
        "task": "app.workers.tasks.maintenance_tasks.cleanup_expired_auth_records",
        "schedule": 3600.0,
    },
}
