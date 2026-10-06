"""FastAPI dependency factories wrapping `app.security.rate_limit.hit()`
for each endpoint category in the Phase 3 brief's rate-limit table. Two
identity strategies:

- `rate_limit_by_ip` -- for pre-authentication endpoints (login, signup)
  where there's no user yet to key on.
- `rate_limit_by_user` -- for authenticated endpoints; requires
  `get_current_user` to have already run (raises 401 first if the token is
  missing/invalid, same as any other protected route -- rate limiting
  never bypasses authentication).

A 429 response always carries the required `Retry-After` header (FastAPI/
Starlette lower-cases response header names, but HTTP header names are
case-insensitive so this is spec-compliant) plus the informational
`X-RateLimit-*` headers, and a JSON body matching the brief's example
shape exactly.
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from app import config
from app.auth.deps import get_current_user
from app.db.models import User
from app.security import rate_limit
from app.security.net import client_ip


def _raise_429(result: rate_limit.RateLimitResult) -> None:
    raise HTTPException(
        status_code=429,
        detail={
            "error": "rate_limit_exceeded",
            "message": "Too many requests. Please try again later.",
            "retry_after": result.reset_after_seconds,
        },
        headers={
            "Retry-After": str(result.reset_after_seconds),
            "X-RateLimit-Limit": str(result.limit),
            "X-RateLimit-Remaining": str(result.remaining),
            "X-RateLimit-Reset": str(result.reset_after_seconds),
        },
    )


def rate_limit_by_ip(bucket: str, config_attr: str):
    """`config_attr` names a `(limit, window_seconds)` tuple attribute on
    `app.config` (e.g. "RATE_LIMIT_LOGIN"), read via getattr() on every
    request rather than unpacked once at route-decoration time -- so
    changing the config value (or a test's `monkeypatch.setattr(config,
    ...)`) takes effect immediately, with no app restart and no stale
    closure over the old numbers."""

    def _dep(request: Request) -> None:
        limit, window_seconds = getattr(config, config_attr)
        result = rate_limit.hit(bucket, client_ip(request), limit, window_seconds)
        if not result.allowed:
            _raise_429(result)

    return _dep


def rate_limit_by_user(bucket: str, config_attr: str):
    def _dep(request: Request, user: User = Depends(get_current_user)) -> User:
        limit, window_seconds = getattr(config, config_attr)
        result = rate_limit.hit(bucket, str(user.id), limit, window_seconds)
        if not result.allowed:
            _raise_429(result)
        return user

    return _dep
