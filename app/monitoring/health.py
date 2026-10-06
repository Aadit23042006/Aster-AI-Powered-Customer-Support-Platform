"""Health/readiness checks (Phase 3, Feature 25). Liveness never touches a
dependency (it answers instantly, purely "is the process up") -- readiness
does, since that's specifically what it's for. Neither leaks connection
strings, credentials, or stack traces; a failed check reports only the
dependency's name and "unhealthy"/"degraded"."""
from __future__ import annotations

from sqlalchemy import text

from app import config
from app.db.base import engine


def check_database() -> str:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return "healthy"
    except Exception:
        return "unhealthy"


def check_redis() -> str:
    try:
        from app.security.rate_limit import _get_client

        _get_client().ping()
        return "healthy"
    except Exception:
        return "unhealthy"


def check_workers() -> str:
    """Best-effort: asks Celery for active worker processes. Reports
    'degraded' rather than 'unhealthy' when no workers are up, since the
    API itself still functions (chat, orders, tickets) with workers down --
    only async jobs (KB reindexing, email, analytics rollups) are
    affected."""
    if not config.WORKERS_ENABLED:
        return "disabled"
    try:
        from app.workers.celery_app import celery_app

        inspector = celery_app.control.inspect(timeout=0.5)
        active = inspector.ping()
        return "healthy" if active else "degraded"
    except Exception:
        return "degraded"


def readiness_report() -> tuple[bool, dict[str, str]]:
    checks = {"database": check_database(), "redis": check_redis(), "workers": check_workers()}
    ready = checks["database"] == "healthy"  # DB is the only hard dependency; Redis/workers degrade gracefully
    return ready, checks
