"""Notification delivery provider abstraction (Phase 3, Feature 23).

`EMAIL_PROVIDER` env var selects the implementation -- `console` (default,
zero configuration, logs what would have been sent) or `smtp` (real
delivery via `smtplib`, needs SMTP_* configured). Nothing else in the
codebase hardcodes "how an email gets sent" -- everything goes through
`get_email_provider()`, so adding a third provider (e.g. an HTTP-API-based
one like SendGrid/SES) later means adding one class here, not touching
every call site.
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app import config
from app.security.pii import mask_email

logger = logging.getLogger("aster_row.notifications")


class EmailDeliveryError(Exception):
    pass


class EmailNotificationProvider:
    def send(self, to_email: str, subject: str, body: str) -> None:
        raise NotImplementedError


class ConsoleEmailProvider(EmailNotificationProvider):
    """Default provider -- no SMTP credentials needed. Logs that an email
    *would* be sent, with the recipient masked, so local dev and CI never
    need real email infrastructure but the code path is still exercised."""

    def send(self, to_email: str, subject: str, body: str) -> None:
        logger.info("Console email provider: would send to=%s subject=%r", mask_email(to_email), subject)


class SMTPEmailProvider(EmailNotificationProvider):
    def send(self, to_email: str, subject: str, body: str) -> None:
        if not config.SMTP_HOST:
            raise EmailDeliveryError("SMTP_HOST is not configured.")
        msg = EmailMessage()
        msg["From"] = config.EMAIL_FROM
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(body)
        try:
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=10) as server:
                server.starttls()
                if config.SMTP_USERNAME:
                    server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
                server.send_message(msg)
        except (smtplib.SMTPException, OSError) as exc:
            raise EmailDeliveryError(str(exc)) from exc


def get_email_provider() -> EmailNotificationProvider:
    if config.EMAIL_PROVIDER == "smtp":
        return SMTPEmailProvider()
    return ConsoleEmailProvider()
