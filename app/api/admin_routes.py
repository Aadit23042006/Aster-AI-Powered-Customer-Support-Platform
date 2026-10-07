"""Admin-only routes for Phase 3: audit log viewing (Feature 21) and
user/role management (Feature 19). Gated by the new fine-grained
`require_permission` dependency, not the coarser `require_roles` used by
Phase 1/2 admin routes -- see `app/auth/permissions.py` for why these are
additive, not a replacement.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.web_schemas import (
    AdminUserOut,
    AuditEventOut,
    ErrorEventOut,
    PaginatedAdminUsers,
    PaginatedAuditEvents,
    PaginatedErrorEvents,
    RoleUpdateRequest,
    SystemHealthOut,
    SystemMetricsOut,
)
from app.auth.deps import require_permission
from app.db.base import get_db
from app.db.models import ErrorEvent, Role, User, UserRole
from app.services import audit_service

router = APIRouter(prefix="/admin", tags=["admin"])

# Granting either of these roles requires system.manage (super_admin only).
# This prevents an admin holding users.update from promoting a user to
# another admin or super_admin.
_ELEVATED_ROLES = {"admin", "super_admin"}


@router.get("/audit-logs", response_model=PaginatedAuditEvents)
def list_audit_logs(
    page: int = 1,
    page_size: int = 25,
    actor_email: str | None = None,
    event_type: str | None = None,
    resource_type: str | None = None,
    success: bool | None = None,
    since: str | None = None,
    until: str | None = None,
    user: User = Depends(require_permission("audit_logs.read")),
    db: Session = Depends(get_db),
) -> PaginatedAuditEvents:
    items, total = audit_service.list_events(
        db,
        page=page,
        page_size=page_size,
        actor_email=actor_email,
        event_type=event_type,
        resource_type=resource_type,
        success=success,
        since=since,
        until=until,
    )

    return PaginatedAuditEvents(
        items=[AuditEventOut.model_validate(event) for event in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/users", response_model=PaginatedAdminUsers)
def list_users(
    page: int = 1,
    page_size: int = 25,
    search: str | None = None,
    user: User = Depends(require_permission("users.read")),
    db: Session = Depends(get_db),
) -> PaginatedAdminUsers:
    query = db.query(User)

    if search:
        query = query.filter(User.email.ilike(f"%{search}%"))

    total = query.count()

    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)

    rows = (
        query.order_by(User.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = [
        AdminUserOut(
            id=target.id,
            email=target.email,
            full_name=target.full_name,
            roles=sorted(target.role_names),
            is_active=target.is_active,
            created_at=target.created_at,
        )
        for target in rows
    ]

    return PaginatedAdminUsers(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.patch("/users/{target_user_id}/role", response_model=AdminUserOut)
def update_user_role(
    target_user_id: uuid.UUID,
    payload: RoleUpdateRequest,
    request: Request,
    user: User = Depends(require_permission("users.update")),
    db: Session = Depends(get_db),
) -> AdminUserOut:
    target = db.get(User, target_user_id)

    if target is None:
        raise HTTPException(
            status_code=404,
            detail="User not found.",
        )

    requested_roles = set(payload.roles)

    valid_roles = {
        role.name
        for role in db.query(Role).all()
    }

    unknown = requested_roles - valid_roles

    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown role(s): {', '.join(sorted(unknown))}",
        )

    # Privilege-escalation guard:
    # granting or retaining admin/super_admin requires system.manage.
    wants_elevated = bool(
        requested_roles & _ELEVATED_ROLES
    )

    if (
        wants_elevated
        and "system.manage" not in user.permission_names
    ):
        raise HTTPException(
            status_code=403,
            detail=(
                "Only a super_admin can grant admin or "
                "super_admin roles."
            ),
        )

    # Prevent an administrator from modifying their own roles and
    # potentially escalating or locking themselves out.
    if (
        target.id == user.id
        and requested_roles != target.role_names
    ):
        raise HTTPException(
            status_code=403,
            detail="You cannot change your own roles.",
        )

    before_roles = sorted(target.role_names)

    db.query(UserRole).filter(
        UserRole.user_id == target.id
    ).delete()

    db.flush()

    for role_name in requested_roles:
        role = (
            db.query(Role)
            .filter(Role.name == role_name)
            .first()
        )

        if role is not None:
            db.add(
                UserRole(
                    user_id=target.id,
                    role_id=role.id,
                )
            )

    audit_service.log_event(
        db,
        event_type="ROLE_CHANGED",
        user=user,
        resource_type="user",
        resource_id=str(target.id),
        detail={
            "before": before_roles,
            "after": sorted(requested_roles),
        },
        request=request,
    )

    db.commit()
    db.refresh(target)

    return AdminUserOut(
        id=target.id,
        email=target.email,
        full_name=target.full_name,
        roles=sorted(target.role_names),
        is_active=target.is_active,
        created_at=target.created_at,
    )


@router.delete("/users/{target_user_id}", status_code=204)
def delete_user(
    target_user_id: uuid.UUID,
    request: Request,
    user: User = Depends(require_permission("users.update")),
    db: Session = Depends(get_db),
) -> None:
    """Permanently remove a managed account.

    Safety rules:
    - Admin, Support and Super Admin core accounts are protected.
    - Customer accounts may be deleted by an authorized admin.
    - Nobody can delete their own account from this endpoint.
    - Protection is enforced server-side, not only in the UI.

    User-owned private data follows the model's existing CASCADE/SET NULL
    relationships, while business history that intentionally survives user
    deletion remains attached without the deleted account.
    """

    target = db.get(User, target_user_id)

    if target is None:
        raise HTTPException(
            status_code=404,
            detail="User not found.",
        )

    if target.id == user.id:
        raise HTTPException(
            status_code=403,
            detail=(
                "You cannot delete your own account "
                "from User Management."
            ),
        )

    target_roles = target.role_names

    # Core administrative/support accounts are protected from permanent
    # deletion. Customer accounts are intentionally NOT protected because
    # authorized admins are allowed to delete customer users.
    protected_roles = {
        "support_agent",
        "admin",
        "super_admin",
    }

    if target_roles & protected_roles:
        raise HTTPException(
            status_code=403,
            detail=(
                "Core Admin, Support and Super Admin "
                "accounts are protected and cannot be deleted."
            ),
        )

    before = {
        "email": target.email,
        "full_name": target.full_name,
        "roles": sorted(target_roles),
    }

    audit_service.log_event(
        db,
        event_type="USER_DELETED",
        user=user,
        resource_type="user",
        resource_id=str(target.id),
        detail=before,
        request=request,
    )

    db.delete(target)
    db.commit()


# ---------------------------------------------------------------------------
# Feature 25/26: system health, metrics, errors
# ---------------------------------------------------------------------------


@router.get(
    "/system/health",
    response_model=SystemHealthOut,
)
def system_health(
    user: User = Depends(
        require_permission(
            "system.read",
            "system.manage",
        )
    ),
) -> SystemHealthOut:
    from app.monitoring.health import readiness_report

    ready, checks = readiness_report()

    return SystemHealthOut(
        status="ok" if ready else "degraded",
        checks=checks,
    )


@router.get(
    "/system/metrics",
    response_model=SystemMetricsOut,
)
def system_metrics(
    user: User = Depends(
        require_permission(
            "system.read",
            "system.manage",
        )
    ),
) -> SystemMetricsOut:
    from app.monitoring.metrics import metrics

    snapshot = metrics.snapshot()

    # Live worker queue depth, best-effort. A Celery inspect() call can
    # legitimately fail/timeout if no worker is up, which must degrade to
    # "0 known" rather than break the whole endpoint.
    try:
        from app.workers.celery_app import celery_app

        inspector = celery_app.control.inspect(timeout=0.5)
        active = inspector.active() or {}

        snapshot["worker_queue_depth"] = sum(
            len(tasks)
            for tasks in active.values()
        )
    except Exception:
        pass

    return SystemMetricsOut(
        **{
            key: value
            for key, value in snapshot.items()
            if key in SystemMetricsOut.model_fields
        }
    )


@router.get(
    "/errors",
    response_model=PaginatedErrorEvents,
)
def list_errors(
    page: int = 1,
    page_size: int = 25,
    user: User = Depends(
        require_permission(
            "system.read",
            "system.manage",
        )
    ),
    db: Session = Depends(get_db),
) -> PaginatedErrorEvents:
    query = (
        db.query(ErrorEvent)
        .order_by(ErrorEvent.created_at.desc())
    )

    total = query.count()

    page = max(page, 1)
    page_size = min(max(page_size, 1), 100)

    rows = (
        query
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return PaginatedErrorEvents(
        items=[
            ErrorEventOut.model_validate(event)
            for event in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )