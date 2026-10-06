"""Idempotently ensure the local canonical Aster accounts and RBAC exist.

This script never truncates application data. It creates missing roles/permissions/users,
and repairs the canonical local account password/role assignment so a fresh Docker
installation has deterministic login credentials.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.auth.permissions import ALL_PERMISSIONS, DEFAULT_ROLE_PERMISSIONS
from app.auth.security import hash_password
from app.db.base import SessionLocal
from app.db.models import Permission, Role, RolePermission, User, UserRole

AUTHORIZED_USERS = [
    {"email": "admin@example.com", "full_name": "Alex Admin", "password": "Admin123!", "roles": ["admin"]},
    {"email": "support@example.com", "full_name": "Sam Support", "password": "Support123!", "roles": ["support_agent"]},
    {"email": "customer@example.com", "full_name": "Casey Customer", "password": "Customer123!", "roles": ["customer"]},
]
CANONICAL_ROLES = ["customer", "support_agent", "admin", "super_admin"]


def ensure_rbac(db):
    roles = {r.name: r for r in db.query(Role).all()}
    for name in CANONICAL_ROLES:
        if name not in roles:
            roles[name] = Role(name=name)
            db.add(roles[name])
            db.flush()

    permissions = {p.name: p for p in db.query(Permission).all()}
    for name, description in ALL_PERMISSIONS.items():
        if name not in permissions:
            permissions[name] = Permission(name=name, description=description)
            db.add(permissions[name])
            db.flush()

    for role_name, permission_names in DEFAULT_ROLE_PERMISSIONS.items():
        role = roles[role_name]
        existing = {rp.permission_id for rp in db.query(RolePermission).filter(RolePermission.role_id == role.id).all()}
        for permission_name in permission_names:
            permission = permissions[permission_name]
            if permission.id not in existing:
                db.add(RolePermission(role_id=role.id, permission_id=permission.id))
    db.flush()
    return roles


def ensure_users(db, roles):
    for spec in AUTHORIZED_USERS:
        user = db.query(User).filter(User.email == spec["email"]).first()
        if user is None:
            user = User(email=spec["email"], full_name=spec["full_name"], password_hash=hash_password(spec["password"]), is_active=True)
            db.add(user)
            db.flush()
        else:
            user.full_name = spec["full_name"]
            user.password_hash = hash_password(spec["password"])
            user.is_active = True

        desired_role_ids = {roles[name].id for name in spec["roles"]}
        current_links = db.query(UserRole).filter(UserRole.user_id == user.id).all()
        current_role_ids = {link.role_id for link in current_links}
        for link in current_links:
            if link.role_id not in desired_role_ids:
                db.delete(link)
        for role_id in desired_role_ids - current_role_ids:
            db.add(UserRole(user_id=user.id, role_id=role_id))


def main() -> None:
    db = SessionLocal()
    try:
        roles = ensure_rbac(db)
        ensure_users(db, roles)
        db.commit()
        print("AUTH INITIALIZATION COMPLETE")
        print("Canonical local accounts are ready; no application data was deleted.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
