"""Shared client-IP resolution, used by both the audit log (Phase 3,
Feature 21) and the rate limiter (Feature 20) -- one implementation, so the
"don't trust a client-supplied header blindly" rule can't drift between
the two call sites.
"""
from __future__ import annotations

from fastapi import Request


def is_trusted_proxy(host: str) -> bool:
    # In this deployment the only thing that ever sits in front of uvicorn
    # is the Docker Compose network's own reverse-proxy-less setup (ports
    # published directly) or a local dev run -- so "trusted proxy" here
    # just means loopback/private ranges, not the public internet. A real
    # multi-hop production deployment behind a CDN/load balancer would
    # configure this from an explicit allowlist instead.
    return host in ("127.0.0.1", "::1", "testclient") or host.startswith(("10.", "172.", "192.168."))


def client_ip(request: Request) -> str:
    """Trusts X-Forwarded-For only when the immediate peer is a trusted
    proxy -- never a client-supplied header taken at face value, which
    would let anyone spoof their rate-limit/audit-log identity."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and request.client and is_trusted_proxy(request.client.host):
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
