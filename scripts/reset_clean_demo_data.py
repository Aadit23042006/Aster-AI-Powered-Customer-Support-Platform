"""Reset the local Aster & Row database to three clean authorized accounts.

This removes all application/runtime data from the database and recreates only
roles, permissions, and the three canonical accounts. No orders, conversations,
tickets, messages, sessions, feedback, notifications, media, AI usage/test
records, or other user-owned/application records are seeded.

Run inside the backend container:
    python scripts/reset_clean_demo_data.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import inspect, text

RESET_SCRIPT_VERSION = "2026-10-05-live-schema-v2"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Import models so every mapped table is registered in Base.metadata.
from app.auth.permissions import ALL_PERMISSIONS, DEFAULT_ROLE_PERMISSIONS
from app.auth.security import hash_password
from app.db.base import Base, SessionLocal
from app.db import models  # noqa: F401
from app.db.models import Permission, Role, RolePermission, User, UserRole

AUTHORIZED_USERS = [
    {
        "email": "admin@example.com",
        "full_name": "Alex Admin",
        "password": "Admin123!",
        "roles": ["admin"],
    },
    {
        "email": "support@example.com",
        "full_name": "Sam Support",
        "password": "Support123!",
        "roles": ["support_agent"],
    },
    {
        "email": "customer@example.com",
        "full_name": "Casey Customer",
        "password": "Customer123!",
        "roles": ["customer"],
    },
]

CANONICAL_ROLES = ["customer", "support_agent", "admin", "super_admin"]


def _truncate_application_data(db) -> None:
    """Delete every existing application row except stable roles/permissions.

    The ORM metadata can contain tables from retired features whose migration
    has already removed those tables from the actual database. Therefore this
    reset uses PostgreSQL's live table list instead of blindly truncating every
    SQLAlchemy model table. This keeps the reset safe across migration history
    changes (for example, retired ``voice_sessions``).
    """
    keep = {"roles", "permissions", "alembic_version"}
    inspector = inspect(db.get_bind())
    existing_tables = inspector.get_table_names(schema="public")
    table_names = [name for name in existing_tables if name not in keep]
    if not table_names:
        return

    # PostgreSQL CASCADE handles FK-dependent application rows while the
    # stable role/permission tables and Alembic migration marker remain intact.
    identifiers = ", ".join(f'"{name}"' for name in sorted(table_names))
    db.execute(text(f"TRUNCATE TABLE {identifiers} RESTART IDENTITY CASCADE"))


def _rebuild_roles_and_permissions(db):
    # Role/permission rows are configuration, not user-owned data. Rebuild
    # them deterministically so stale custom links/configuration cannot remain.
    db.query(RolePermission).delete(synchronize_session=False)
    db.query(Role).delete(synchronize_session=False)
    db.query(Permission).delete(synchronize_session=False)
    db.flush()

    roles = {}
    for name in CANONICAL_ROLES:
        role = Role(name=name)
        db.add(role)
        db.flush()
        roles[name] = role

    permissions = {}
    for name, description in ALL_PERMISSIONS.items():
        permission = Permission(name=name, description=description)
        db.add(permission)
        db.flush()
        permissions[name] = permission

    for role_name, permission_names in DEFAULT_ROLE_PERMISSIONS.items():
        role = roles[role_name]
        for permission_name in permission_names:
            db.add(
                RolePermission(
                    role_id=role.id,
                    permission_id=permissions[permission_name].id,
                )
            )

    db.flush()
    return roles


def _create_authorized_users(db, roles) -> None:
    for spec in AUTHORIZED_USERS:
        user = User(
            email=spec["email"],
            full_name=spec["full_name"],
            password_hash=hash_password(spec["password"]),
        )
        db.add(user)
        db.flush()
        for role_name in spec["roles"]:
            db.add(UserRole(user_id=user.id, role_id=roles[role_name].id))


def main() -> None:
    db = SessionLocal()
    try:
        _truncate_application_data(db)
        roles = _rebuild_roles_and_permissions(db)
        _create_authorized_users(db, roles)
        db.commit()

        print(f"CLEAN RESET COMPLETE ({RESET_SCRIPT_VERSION})")
        print("Authorized accounts:")
        for spec in AUTHORIZED_USERS:
            print(f"  - {spec['email']}")
        print("No demo orders, conversations, messages, tickets, feedback,")
        print("notifications, sessions, media, AI usage/test data, organizations,")
        print("products/catalog, recommendations, API keys, webhooks, personas,")
        print("or other application/user-owned records were seeded.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
