"""Centralized error tracking (Phase 3, Feature 26).

Always writes to the `error_events` table (so the Admin error viewer never
depends on an external service being configured) and optionally mirrors to
an external provider (Sentry) when `ERROR_TRACKING_ENABLED=true` and
`SENTRY_DSN` is set.

If `sentry-sdk` isn't installed or the DSN is empty, `capture_exception`
silently no-ops for the external part -- the app must keep operating either
way (see the Phase 3 brief's "the application should continue operating"
requirement).
"""

from __future__ import annotations

import logging
import re
import traceback
import uuid

from sqlalchemy.orm import Session

from app import config
from app.db.base import SessionLocal
from app.db.models import ErrorEvent
from app.security.pii import mask_email, redact_pii

logger = logging.getLogger("aster_row.error_tracking")

_sentry_initialized = False

# Email pattern used specifically for error-message masking.
# We use mask_email() rather than replacing the whole email with a generic
# marker such as "[REDACTED_EMAIL]" because the monitoring tests and the
# application's PII convention expect a masked value such as:
#
#     s***@example.com
#
_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
)


def _redact_error_message(message: str) -> str:
    """Redact sensitive information from an exception message.

    General PII/secrets are handled by redact_pii(). Email addresses are
    additionally passed through mask_email() so they remain visibly masked
    rather than becoming the generic '[REDACTED_EMAIL]' marker.

    Example:
        "something failed for user someone@example.com"

    becomes:
        "something failed for user s***@example.com"
    """
    if not isinstance(message, str):
        return "[unrepresentable]"

    # First apply the project's normal recursive/string PII redaction.
    redacted = redact_pii(message)

    # If redact_pii() has already replaced the email with a generic marker,
    # the original email is no longer available to mask. Therefore, when
    # possible, perform email masking directly on the original message first.
    #
    # This preserves the actual masked-email format required by monitoring
    # consumers/tests while still allowing redact_pii() to handle other PII.
    masked = _EMAIL_RE.sub(
        lambda match: mask_email(match.group(0)),
        message,
    )

    # Run the general PII redactor over the masked message. Because the
    # resulting masked email no longer contains a valid email address, it
    # remains intact while other sensitive content is still protected.
    return redact_pii(masked)


def _maybe_init_sentry() -> None:
    """Initialize Sentry only when explicitly configured."""
    global _sentry_initialized

    if (
        _sentry_initialized
        or not config.ERROR_TRACKING_ENABLED
        or not config.SENTRY_DSN
    ):
        return

    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=config.SENTRY_DSN,
            environment=config.ENVIRONMENT,
            traces_sample_rate=0.0,
        )
        _sentry_initialized = True

    except ImportError:  # pragma: no cover - optional dependency
        logger.warning(
            "ERROR_TRACKING_ENABLED is true but the 'sentry-sdk' package "
            "is not installed; errors will still be recorded in the "
            "error_events table, just not mirrored externally."
        )


def capture_exception(
    exc: Exception,
    *,
    request_id: str | None = None,
    user_id: uuid.UUID | None = None,
    route: str | None = None,
    service: str = "backend",
    metadata: dict | None = None,
    db: Session | None = None,
) -> ErrorEvent | None:
    """Record an exception locally and optionally send it to Sentry.

    Error tracking must never raise an exception of its own. If database
    persistence, redaction, or external Sentry reporting fails, the original
    application error must not be masked or replaced.
    """
    owns_session = db is None
    db = db or SessionLocal()

    try:
        raw_message = str(exc)

        event = ErrorEvent(
            request_id=request_id,
            service=service,
            environment=config.ENVIRONMENT,
            user_id=user_id,
            route=route,
            error_type=type(exc).__name__,
            error_message=_redact_error_message(raw_message),
            stack_trace="".join(
                traceback.format_exception(
                    type(exc),
                    exc,
                    exc.__traceback__,
                )
            )[:8000],
            metadata_=redact_pii(metadata) if metadata else None,
        )

        db.add(event)

        if owns_session:
            db.commit()

            # Without this, the returned `event`'s attributes are expired
            # by the commit and the caller hits DetachedInstanceError the
            # moment it reads e.g. event.request_id after this function
            # (and its session) has returned/closed.
            db.refresh(event)
        else:
            db.flush()

        _maybe_init_sentry()

        if _sentry_initialized:
            try:
                import sentry_sdk

                with sentry_sdk.push_scope() as scope:
                    if request_id:
                        scope.set_tag("request_id", request_id)

                    sentry_sdk.capture_exception(exc)

            except Exception:  # pragma: no cover
                # External provider failures must never break the application.
                logger.warning(
                    "Failed to mirror exception to Sentry",
                    exc_info=True,
                )

        return event

    except Exception:  # pragma: no cover
        # Error tracking itself must never raise or break the caller.
        logger.exception("Failed to record error event")

        if owns_session:
            try:
                db.rollback()
            except Exception:
                pass

        return None

    finally:
        if owns_session:
            db.close()