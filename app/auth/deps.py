"""FastAPI dependencies for authentication and authorization.

Every protected route depends on `get_current_user`, which independently
validates the JWT on the backend -- the frontend hiding a nav link is never
treated as access control. Role checks (`require_roles`) and resource
ownership checks happen server-side too; a client-supplied `user_id` is
never trusted (see `app/api/orders_routes.py` / `tickets_routes.py` for the
ownership-filtering pattern this enables).
"""
from __future__ import annotations

import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.security import decode_access_token
from app.db.base import get_db
from app.db.models import User

_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject")

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


def require_roles(*allowed_roles: str):
    """Usage: `Depends(require_roles('support_agent', 'admin'))`.
    Distinct from `get_current_user` so route signatures make the
    authorization requirement explicit and testable on its own."""

    def _checker(user: User = Depends(get_current_user)) -> User:
        if not (user.role_names & set(allowed_roles)):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user

    return _checker


def require_permission(*any_of: str):
    """Phase 3 (Feature 19): fine-grained permission check, additive to
    `require_roles` above -- existing Phase 1/2 routes keep using
    `require_roles` unchanged (zero regression risk); new Phase 3 admin
    surfaces (audit logs, system health/metrics, notification admin) use
    this instead, so which roles can reach them is data (`role_permissions`,
    seeded from `app.auth.permissions.DEFAULT_ROLE_PERMISSIONS`) rather than
    a hardcoded role list in every route. Passes if the user holds ANY of
    the listed permissions (same OR semantics as `require_roles`)."""

    def _checker(user: User = Depends(get_current_user)) -> User:
        if not (user.permission_names & set(any_of)):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user

    return _checker
