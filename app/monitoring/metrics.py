"""Application metrics (Phase 3, Feature 25).

Deliberately simple in-process counters rather than a full Prometheus
client library dependency -- this is a single-process FastAPI app (see
Known Limitations in docs/PHASE_3.md for what a multi-worker/multi-replica
deployment would need instead, e.g. `prometheus_client` with a multiprocess
registry, or pushing these same numbers to Redis so they aggregate across
workers). Every number here comes from real requests/events the app
actually processed -- nothing in `app/api/admin_routes.py`'s
`/admin/system/metrics` response is hardcoded, per the Phase 3 brief's
explicit "do not invent metrics" requirement.
"""
from __future__ import annotations

import threading
import time


class _Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.http_requests_total = 0
        self.http_5xx_total = 0
        self.http_4xx_total = 0
        self._latency_sum_ms = 0.0
        self._latency_count = 0
        self.ai_requests_total = 0
        self._ai_latency_sum_ms = 0.0
        self._ai_latency_count = 0
        self.rate_limit_events_total = 0
        self.auth_failures_total = 0
        self.worker_tasks_total = 0
        self.worker_task_failures_total = 0
        self.notification_failures_total = 0
        self._started_at = time.time()

    def record_request(self, status_code: int, duration_ms: float) -> None:
        with self._lock:
            self.http_requests_total += 1
            self._latency_sum_ms += duration_ms
            self._latency_count += 1
            if status_code >= 500:
                self.http_5xx_total += 1
            elif status_code >= 400:
                self.http_4xx_total += 1

    def record_ai_request(self, duration_ms: float) -> None:
        with self._lock:
            self.ai_requests_total += 1
            self._ai_latency_sum_ms += duration_ms
            self._ai_latency_count += 1

    def record_rate_limit_event(self) -> None:
        with self._lock:
            self.rate_limit_events_total += 1

    def record_auth_failure(self) -> None:
        with self._lock:
            self.auth_failures_total += 1

    def record_worker_task(self, *, failed: bool = False) -> None:
        with self._lock:
            self.worker_tasks_total += 1
            if failed:
                self.worker_task_failures_total += 1

    def record_notification_failure(self) -> None:
        with self._lock:
            self.notification_failures_total += 1

    def snapshot(self) -> dict:
        with self._lock:
            avg_latency = self._latency_sum_ms / self._latency_count if self._latency_count else 0.0
            avg_ai_latency = self._ai_latency_sum_ms / self._ai_latency_count if self._ai_latency_count else 0.0
            return {
                "http_requests_total": self.http_requests_total,
                "http_5xx_total": self.http_5xx_total,
                "http_4xx_total": self.http_4xx_total,
                "average_latency_ms": round(avg_latency, 2),
                "ai_requests_total": self.ai_requests_total,
                "ai_average_latency_ms": round(avg_ai_latency, 2),
                "rate_limit_events_total": self.rate_limit_events_total,
                "auth_failures_total": self.auth_failures_total,
                "worker_queue_depth": 0,  # filled in by app.api.admin_routes from a live Celery inspect() call
                "worker_tasks_total": self.worker_tasks_total,
                "worker_task_failures_total": self.worker_task_failures_total,
                "notification_failures_total": self.notification_failures_total,
                "uptime_seconds": round(time.time() - self._started_at, 1),
            }


metrics = _Metrics()
