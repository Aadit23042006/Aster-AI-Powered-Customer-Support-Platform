"""
PII and secret redaction helpers.

This module is intentionally conservative about secrets and personal
information while avoiding false positives for machine-generated values
such as ISO-8601 timestamps, order IDs, and tracking numbers.
"""

from __future__ import annotations

import re
from typing import Any


# ---------------------------------------------------------------------------
# Pattern definitions
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
)

# Phone-number detection.
#
# IMPORTANT:
# ISO timestamps can contain sequences such as:
#   2026-09-27
#   15:31:00
#   00.245753
#
# These must not be interpreted as phone numbers.
_PHONE_RE = re.compile(
    r"(?<![\dT:])"
    r"(\+?\d[\d\-. ]{7,}\d)"
    r"(?![\dT:])"
)

# ISO-8601 timestamp detection.
#
# These are application-generated timestamps and are NOT PII by
# themselves, so they must remain unchanged.
_ISO_TIMESTAMP_RE = re.compile(
    r"\b"
    r"\d{4}-\d{2}-\d{2}"
    r"T"
    r"\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?"
    r"(?:Z|[+-]\d{2}:\d{2})?"
    r"\b"
)


_SECRET_KEY_MARKERS = {
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "auth_secret",
    "access_token",
    "refresh_token",
    "jwt",
    "private_key",
    "credit_card",
    "card_number",
    "cvv",
    "ssn",
    "ban",
    "iban",
    "smtp_password",
}

_PII_KEY_MARKERS = {
    "email",
    "phone",
    "address",
    "full_name",
    "customer_name",
    "ip_address",
}


# ---------------------------------------------------------------------------
# Key classification
# ---------------------------------------------------------------------------

def _normalise_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")


def _is_secret_key(key: str) -> bool:
    normalized = _normalise_key(key)

    return (
        normalized in _SECRET_KEY_MARKERS
        or any(marker in normalized for marker in _SECRET_KEY_MARKERS)
    )


def _is_pii_key(key: str) -> bool:
    normalized = _normalise_key(key)

    return (
        normalized in _PII_KEY_MARKERS
        or any(marker in normalized for marker in _PII_KEY_MARKERS)
    )


# ---------------------------------------------------------------------------
# Email masking
# ---------------------------------------------------------------------------

def mask_email(email: str) -> str:
    """
    Mask an email address for safe logging/notification output.

    Examples:
        john@example.com -> j***@example.com
        a@example.com    -> *@example.com
        invalid          -> ***
    """

    if not isinstance(email, str):
        return "***"

    email = email.strip()

    match = _EMAIL_RE.fullmatch(email)

    if not match:
        return "***"

    local_part, domain = email.split("@", 1)

    if not local_part:
        return "***"

    if len(local_part) == 1:
        masked_local = "*"
    else:
        masked_local = local_part[0] + "***"

    return f"{masked_local}@{domain}"


# ---------------------------------------------------------------------------
# String redaction
# ---------------------------------------------------------------------------

def _redact_string(value: str) -> str:
    """
    Redact obvious email/phone values while preserving machine-generated
    identifiers such as ISO-8601 timestamps.
    """

    protected_timestamps: list[str] = []

    def _protect_timestamp(match: re.Match[str]) -> str:
        protected_timestamps.append(match.group(0))
        return f"__ISO_TIMESTAMP_{len(protected_timestamps) - 1}__"

    # Protect timestamps before phone detection.
    protected = _ISO_TIMESTAMP_RE.sub(
        _protect_timestamp,
        value,
    )

    # Redact email addresses.
    protected = _EMAIL_RE.sub(
        "[REDACTED_EMAIL]",
        protected,
    )

    # Redact phone numbers.
    protected = _PHONE_RE.sub(
        "[REDACTED_PHONE]",
        protected,
    )

    # Restore timestamps exactly as they appeared.
    for index, timestamp in enumerate(protected_timestamps):
        protected = protected.replace(
            f"__ISO_TIMESTAMP_{index}__",
            timestamp,
        )

    return protected


# ---------------------------------------------------------------------------
# Recursive PII redaction
# ---------------------------------------------------------------------------

def redact_pii(value: Any, key: str | None = None) -> Any:
    """
    Recursively redact secrets and obvious PII.

    Dictionary keys containing secret/PII markers are redacted completely.

    String values are scanned for:
      - email addresses
      - phone numbers

    ISO timestamps, order IDs, tracking numbers and status values are
    preserved.
    """

    if isinstance(value, dict):
        redacted: dict[str, Any] = {}

        for k, v in value.items():
            if _is_secret_key(k):
                redacted[k] = "[REDACTED_SECRET]"
            elif _is_pii_key(k):
                redacted[k] = "[REDACTED_PII]"
            else:
                redacted[k] = redact_pii(v, key=k)

        return redacted

    if isinstance(value, list):
        return [
            redact_pii(item, key=key)
            for item in value
        ]

    if isinstance(value, tuple):
        return tuple(
            redact_pii(item, key=key)
            for item in value
        )

    if isinstance(value, str):
        if key and _is_secret_key(key):
            return "[REDACTED_SECRET]"

        if key and _is_pii_key(key):
            return "[REDACTED_PII]"

        return _redact_string(value)

    return value


# ---------------------------------------------------------------------------
# Secret-only redaction
# ---------------------------------------------------------------------------

def redact_secrets_only(value: Any, key: str | None = None) -> Any:
    """
    Redact only explicit secret fields.

    This is useful when logging data where ordinary PII should remain
    available for debugging but credentials/secrets must never be logged.
    """

    if isinstance(value, dict):
        redacted: dict[str, Any] = {}

        for k, v in value.items():
            if _is_secret_key(k):
                redacted[k] = "[REDACTED_SECRET]"
            else:
                redacted[k] = redact_secrets_only(v, key=k)

        return redacted

    if isinstance(value, list):
        return [
            redact_secrets_only(item, key=key)
            for item in value
        ]

    if isinstance(value, tuple):
        return tuple(
            redact_secrets_only(item, key=key)
            for item in value
        )

    return value