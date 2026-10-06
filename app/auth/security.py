"""Password hashing and JWT access/refresh token helpers.

Kept deliberately dependency-light and framework-agnostic so it's easy to
unit test without spinning up FastAPI.
"""
from __future__ import annotations

import os
import re
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

# Never commit a real secret -- this must come from the environment in any
# non-local deployment. A dev-only fallback keeps local `pytest`/uvicorn
# runs working without extra setup.
AUTH_SECRET = os.environ.get("AUTH_SECRET", "dev-only-insecure-secret-change-me-0123456789abcdef")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TTL_MINUTES = int(os.environ.get("ACCESS_TOKEN_TTL_MINUTES", "30"))
REFRESH_TOKEN_TTL_DAYS = int(os.environ.get("REFRESH_TOKEN_TTL_DAYS", "14"))

_PASSWORD_MIN_LENGTH = 8
_PASSWORD_RE = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).+$")


class WeakPasswordError(ValueError):
    pass


def validate_password_strength(password: str) -> None:
    if len(password) < _PASSWORD_MIN_LENGTH:
        raise WeakPasswordError(f"Password must be at least {_PASSWORD_MIN_LENGTH} characters.")
    if not _PASSWORD_RE.match(password):
        raise WeakPasswordError("Password must include an uppercase letter, a lowercase letter, and a digit.")


def _bcrypt_bytes(password: str) -> bytes:
    # bcrypt's algorithm ignores anything past 72 bytes; modern versions of
    # the `bcrypt` package raise instead of silently truncating, so we
    # truncate explicitly and consistently here (both when hashing and
    # verifying) rather than passing a too-long password through.
    return password.encode("utf-8")[:72]


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_bcrypt_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(_bcrypt_bytes(password), password_hash.encode("utf-8"))


def _encode(payload: dict, ttl: timedelta) -> str:
    now = datetime.now(timezone.utc)
    to_encode = {**payload, "iat": now, "exp": now + ttl}
    return jwt.encode(to_encode, AUTH_SECRET, algorithm=JWT_ALGORITHM)


def create_access_token(user_id: str, roles: list[str]) -> str:
    return _encode({"sub": user_id, "roles": roles, "type": "access"}, timedelta(minutes=ACCESS_TOKEN_TTL_MINUTES))


def create_raw_refresh_token() -> str:
    """A refresh token is an opaque random string -- only its hash is
    stored server-side (in `sessions.refresh_token_hash`), the same way a
    password is stored, so a DB leak doesn't hand out live sessions."""
    return secrets.token_urlsafe(48)


def hash_refresh_token(raw_token: str) -> str:
    # Refresh/reset tokens are opaque random strings (secrets.token_urlsafe),
    # always well under 72 bytes, so no truncation concern here.
    return bcrypt.hashpw(raw_token.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_refresh_token(raw_token: str, token_hash: str) -> bool:
    return bcrypt.checkpw(raw_token.encode("utf-8"), token_hash.encode("utf-8"))


def decode_access_token(token: str) -> dict:
    """Raises jwt.PyJWTError (or subclasses) on any invalid/expired token --
    callers should catch that and turn it into a 401."""
    payload = jwt.decode(token, AUTH_SECRET, algorithms=[JWT_ALGORITHM])
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("not an access token")
    return payload


def refresh_token_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_TTL_DAYS)


def create_raw_reset_token() -> str:
    return secrets.token_urlsafe(32)


def reset_token_expiry(minutes: int = 30) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)
