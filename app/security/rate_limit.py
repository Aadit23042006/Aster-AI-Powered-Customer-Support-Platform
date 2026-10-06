"""Redis-backed rate limiting (Phase 3, Feature 20).

Fixed-window counters, incremented atomically via a small Lua script (one
round trip, no read-then-write race between concurrent requests hitting
the same key). Each bucket (login, signup, ai_chat, ticket_create,
feedback, kb_upload, analytics, general) has its own configurable
(count, window_seconds) pair -- see app/config.py -- and its own Redis key
namespace, so a burst against one endpoint never eats into another
endpoint's budget.

Fails OPEN, not closed: if Redis is unreachable, requests are allowed
through rather than taking the whole API down over a rate-limiter outage.
This is a deliberate availability-over-strictness choice for a support
platform (better to risk some extra load than to lock out every customer
because Redis had a blip) -- logged, not silent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import redis

from app import config


logger = logging.getLogger("aster_row.rate_limit")


# ============================================================================
# ATOMIC REDIS RATE-LIMIT SCRIPT
# ============================================================================
# Increment the counter atomically.
#
# If this is the first request in the window, set the expiration.
# Return both the current counter value and remaining TTL.
_INCR_AND_EXPIRE_IF_NEW = """
local current = redis.call("INCR", KEYS[1])
if tonumber(current) == 1 then
    redis.call("EXPIRE", KEYS[1], ARGV[1])
end
local ttl = redis.call("TTL", KEYS[1])
return {current, ttl}
"""


# ============================================================================
# REDIS CLIENT
# ============================================================================
# The Redis client is cached during normal application operation.
#
# IMPORTANT:
# Docker application:
#     redis://redis:6379/0
#
# Windows pytest:
#     redis://localhost:6379/0
#
# The URL can therefore differ between the Docker application and the
# Windows test process.
#
# `_client_url` tracks which URL was used to create the cached client.
# If config.REDIS_URL changes, the client is automatically recreated.
_client: redis.Redis | None = None
_client_url: str | None = None


def _get_client() -> redis.Redis:
    """Return a Redis client for the currently configured Redis URL.

    The client is cached for normal application operation.

    If `config.REDIS_URL` changes, a new Redis client is created. This is
    important for the test suite because pytest runs directly on Windows
    while the application normally runs inside Docker.

    Docker:
        redis://redis:6379/0

    Windows pytest:
        redis://localhost:6379/0
    """

    global _client
    global _client_url

    current_url = config.REDIS_URL

    # Create the client for the first request, or recreate it if the
    # configured Redis URL has changed since the previous client was created.
    if _client is None or _client_url != current_url:
        _client = redis.Redis.from_url(
            current_url,
            decode_responses=True,
            # 0.5s was too tight in practice: under real load (e.g. the
            # full test suite's Postgres-heavy work running alongside the
            # rest of the Docker stack -- backend/worker/scheduler all
            # sharing the same Redis instance -- an occasional round trip
            # through Docker Desktop's networking layer on Windows can
            # take longer than 500ms even though Redis itself is healthy).
            # A slow-but-alive Redis would then get treated as "down" and
            # silently fail open, defeating the rate limiter for real
            # traffic too, not just in tests. 2s is still fast enough to
            # fail open quickly for an actually-unreachable Redis without
            # false-triggering on ordinary load spikes.
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )

        _client_url = current_url

    return _client


# ============================================================================
# RESULT MODEL
# ============================================================================
@dataclass
class RateLimitResult:
    """Result returned by the rate limiter."""

    allowed: bool
    limit: int
    remaining: int
    reset_after_seconds: int


# ============================================================================
# RATE-LIMIT REQUEST
# ============================================================================
def hit(
    bucket: str,
    identity: str,
    limit: int,
    window_seconds: int,
) -> RateLimitResult:
    """Record one request against `bucket:identity`.

    Returns whether the request is still within the configured limit.

    `identity` is an IP address for unauthenticated buckets such as login
    and signup, or a user ID for authenticated buckets such as ai_chat,
    ticket_create, feedback, kb_upload, and analytics.

    See:
        app/security/rate_limit_deps.py
    """

    # ------------------------------------------------------------------------
    # Rate limiting disabled.
    # ------------------------------------------------------------------------
    if not config.RATE_LIMIT_ENABLED:
        return RateLimitResult(
            allowed=True,
            limit=limit,
            remaining=limit,
            reset_after_seconds=0,
        )

    # ------------------------------------------------------------------------
    # Build the Redis key.
    # ------------------------------------------------------------------------
    key = f"ratelimit:{bucket}:{identity}"

    try:
        # --------------------------------------------------------------------
        # Get the currently configured Redis client.
        # --------------------------------------------------------------------
        client = _get_client()

        # --------------------------------------------------------------------
        # Execute the atomic increment + expiry Lua script.
        # --------------------------------------------------------------------
        current, ttl = client.eval(
            _INCR_AND_EXPIRE_IF_NEW,
            1,
            key,
            window_seconds,
        )

        current = int(current)
        ttl = int(ttl)

    except redis.RedisError:
        # --------------------------------------------------------------------
        # Deliberate fail-open behavior.
        #
        # If Redis is unavailable, the API continues working rather than
        # rejecting every request because the rate limiter is unavailable.
        # --------------------------------------------------------------------
        logger.warning(
            "Rate limiter Redis unavailable -- failing open for bucket=%s",
            bucket,
        )

        return RateLimitResult(
            allowed=True,
            limit=limit,
            remaining=limit,
            reset_after_seconds=0,
        )

    # ------------------------------------------------------------------------
    # Calculate remaining requests.
    # ------------------------------------------------------------------------
    remaining = max(limit - current, 0)

    # ------------------------------------------------------------------------
    # Return the final rate-limit result.
    # ------------------------------------------------------------------------
    return RateLimitResult(
        allowed=current <= limit,
        limit=limit,
        remaining=remaining,
        reset_after_seconds=max(ttl, 0),
    )


# ============================================================================
# RESET RATE LIMIT
# ============================================================================
def reset(
    bucket: str,
    identity: str,
) -> None:
    """Test/admin helper -- clear one identity's counter for a bucket.

    Example:
        reset("login", "testclient")
    """

    try:
        _get_client().delete(
            f"ratelimit:{bucket}:{identity}"
        )

    except redis.RedisError:
        # Reset is intentionally best-effort. A Redis outage should not
        # cause unrelated application/test code to crash.
        pass