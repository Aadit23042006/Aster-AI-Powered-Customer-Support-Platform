"""Fixtures for the Phase 1 web-app test suite.

Runs against a REAL PostgreSQL database, not SQLite.

The test suite can run in either of these environments:

1. Directly on the host:
       PostgreSQL -> localhost:5432
       Redis      -> localhost:6379

2. Inside the Docker backend container:
       PostgreSQL -> postgres:5432
       Redis      -> redis:6379

IMPORTANT:
All environment variables must be configured BEFORE importing any
`app.*` module because application configuration/database modules may
read environment variables during import.
"""

from __future__ import annotations

import os


# ===========================================================================
# TEST DATABASE CONFIGURATION
# ===========================================================================
#
# There are two supported execution environments.
#
# HOST:
#     localhost:5432
#
# DOCKER:
#     postgres:5432
#
# Docker Compose normally injects DATABASE_URL into the backend container.
# Therefore we MUST NOT overwrite an existing DATABASE_URL with localhost.
#
# Priority:
#
#   1. TEST_DATABASE_URL
#   2. Existing DATABASE_URL
#   3. Localhost fallback
#
# This fixes the situation where pytest is executed with:
#
#     docker compose exec backend python -m pytest ...
#
# In that case `localhost` means the backend container itself, while the
# PostgreSQL service is reachable using the Docker service name `postgres`.
#
os.environ["DATABASE_URL"] = (
    os.environ.get("TEST_DATABASE_URL")
    or os.environ.get("DATABASE_URL")
    or (
        "postgresql+psycopg2://"
        "postgres:postgres@localhost:5432/"
        "aster_row_test"
    )
)


# ===========================================================================
# REDIS CONFIGURATION
# ===========================================================================
#
# HOST:
#     redis://localhost:6379/0
#
# DOCKER:
#     redis://redis:6379/0
#
# Docker Compose normally injects REDIS_URL into the backend container.
# Preserve that value instead of forcing localhost.
#
# Priority:
#
#   1. TEST_REDIS_URL
#   2. Existing REDIS_URL
#   3. Localhost fallback
#
os.environ["REDIS_URL"] = (
    os.environ.get("TEST_REDIS_URL")
    or os.environ.get("REDIS_URL")
    or "redis://localhost:6379/0"
)


# ===========================================================================
# GENERAL TEST CONFIGURATION
# ===========================================================================
#
# The web test suite must use the deterministic mock LLM instead of making
# real Gemini/API requests.
#
os.environ["USE_MOCK_LLM"] = "1"

# Web tests intentionally create temporary accounts; production signup remains disabled.
os.environ["SELF_SIGNUP_ENABLED"] = "true"
os.environ["LOGIN_ALLOWLIST_ENABLED"] = "false"


# ===========================================================================
# TEST AUTH SECRET
# ===========================================================================
#
# Use a deterministic test-only authentication secret.
#
# This MUST NOT be used in production.
#
os.environ["AUTH_SECRET"] = "test-secret-not-for-production"


# ===========================================================================
# RATE LIMITING
# ===========================================================================
#
# General web tests do not need to consume rate-limit buckets.
#
# Dedicated rate-limit tests explicitly enable the limiter by monkeypatching
# the application's RATE_LIMIT_ENABLED configuration.
#
# IMPORTANT:
# Do not modify the application's fail-open Redis behavior.
#
os.environ["RATE_LIMIT_ENABLED"] = "false"


# ===========================================================================
# APPLICATION IMPORTS
# ===========================================================================
#
# These imports intentionally happen AFTER environment configuration.
#
import pytest
from fastapi.testclient import TestClient

from app.db.base import Base, SessionLocal, engine
from app.auth.permissions import (
    ALL_PERMISSIONS,
    DEFAULT_ROLE_PERMISSIONS,
)
from app.db.models import (
    Permission,
    Role,
    RolePermission,
)


# ===========================================================================
# DATABASE ISOLATION
# ===========================================================================
@pytest.fixture(autouse=True)
def _clean_db():
    """Give every test a clean PostgreSQL database schema.

    Before each test:

        1. Drop all tables.
        2. Recreate all tables.
        3. Create the standard roles.
        4. Create the standard permissions.
        5. Attach default permissions to roles.

    After each test:

        6. Drop all tables.

    This prevents test state from leaking between tests.
    """

    # -----------------------------------------------------------------------
    # Start with a completely clean schema.
    # -----------------------------------------------------------------------
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    session = SessionLocal()

    try:
        # -------------------------------------------------------------------
        # Create standard roles.
        # -------------------------------------------------------------------
        roles: dict[str, Role] = {}

        for role_name in (
            "customer",
            "support_agent",
            "admin",
            "super_admin",
        ):
            role = Role(name=role_name)

            session.add(role)

            roles[role_name] = role

        session.flush()

        # -------------------------------------------------------------------
        # Create all application permissions.
        # -------------------------------------------------------------------
        permissions: dict[str, Permission] = {}

        for permission_name, description in ALL_PERMISSIONS.items():
            permission = Permission(
                name=permission_name,
                description=description,
            )

            session.add(permission)

            permissions[permission_name] = permission

        session.flush()

        # -------------------------------------------------------------------
        # Attach default permissions to each role.
        # -------------------------------------------------------------------
        for role_name, permission_names in DEFAULT_ROLE_PERMISSIONS.items():
            role = roles[role_name]

            for permission_name in permission_names:
                permission = permissions[permission_name]

                session.add(
                    RolePermission(
                        role_id=role.id,
                        permission_id=permission.id,
                    )
                )

        session.commit()

    finally:
        session.close()

    yield

    # -----------------------------------------------------------------------
    # Remove all test data after the test.
    # -----------------------------------------------------------------------
    Base.metadata.drop_all(bind=engine)


# ===========================================================================
# TRACE LOG ISOLATION + MOCK LLM
# ===========================================================================
@pytest.fixture(autouse=True)
def _isolated_trace_log(tmp_path, monkeypatch):
    """Give every test its own isolated trace log and test agent.

    This prevents tests from writing into the repository's real
    logs/trace.jsonl file.

    It also ensures that a cached production/Gemini agent cannot leak from
    one test into another test.
    """

    from app import config
    from app import server
    from app.logging_utils import TraceLogger

    trace_path = tmp_path / "trace.jsonl"

    # -----------------------------------------------------------------------
    # Force the application configuration to use the mock LLM.
    # -----------------------------------------------------------------------
    monkeypatch.setattr(
        config,
        "USE_MOCK_LLM",
        True,
    )

    # -----------------------------------------------------------------------
    # Reset the cached web agent.
    #
    # server.get_web_agent() may cache an Agent instance. If that instance
    # was created before USE_MOCK_LLM was patched, it could still contain
    # a real Gemini client.
    # -----------------------------------------------------------------------
    server._web_agent = None

    # -----------------------------------------------------------------------
    # Create a fresh test agent using the mock LLM.
    # -----------------------------------------------------------------------
    test_agent = server.get_web_agent()

    # -----------------------------------------------------------------------
    # Patch the configured trace-log location.
    # -----------------------------------------------------------------------
    monkeypatch.setattr(
        config,
        "LOG_PATH",
        trace_path,
    )

    # -----------------------------------------------------------------------
    # Replace the agent's trace logger with the isolated test logger.
    # -----------------------------------------------------------------------
    test_agent._trace = TraceLogger(trace_path)


# ===========================================================================
# DATABASE SESSION FIXTURE
# ===========================================================================
@pytest.fixture()
def db_session():
    """Provide a database session for an individual test."""

    session = SessionLocal()

    try:
        yield session

    finally:
        session.close()


# ===========================================================================
# FASTAPI TEST CLIENT
# ===========================================================================
@pytest.fixture()
def client():
    """Return a FastAPI TestClient using the test configuration.

    The `_isolated_trace_log` autouse fixture runs before this fixture,
    ensuring that the cached web agent is reset and the MockLLM is used.
    """

    from app.server import app

    with TestClient(app) as test_client:
        yield test_client


# ===========================================================================
# AUTHENTICATION HELPERS
# ===========================================================================
def signup_and_login(
    client,
    email: str = "alice@example.com",
    password: str = "Password123!",
    full_name: str = "Alice Test",
) -> dict:
    """Create a user and return access/refresh tokens."""

    response = client.post(
        "/auth/signup",
        json={
            "full_name": full_name,
            "email": email,
            "password": password,
            "confirm_password": password,
        },
    )

    assert response.status_code == 201, response.text

    data = response.json()

    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
    }


def auth_headers(tokens: dict) -> dict:
    """Build Authorization headers for an authenticated request."""

    return {
        "Authorization": f"Bearer {tokens['access_token']}",
    }


# ===========================================================================
# ADMIN HELPER
# ===========================================================================
def make_admin(client, tokens: dict) -> None:
    """Grant the admin role to an existing test user.

    This helper is used by tests that need administrative permissions.
    """

    from app.db.base import SessionLocal
    from app.db.models import Role, UserRole

    # -----------------------------------------------------------------------
    # Get the authenticated user's ID.
    # -----------------------------------------------------------------------
    response = client.get(
        "/auth/me",
        headers=auth_headers(tokens),
    )

    assert response.status_code == 200, response.text

    user_id = response.json()["id"]

    # -----------------------------------------------------------------------
    # Find the admin role.
    # -----------------------------------------------------------------------
    db = SessionLocal()

    try:
        role = (
            db.query(Role)
            .filter(Role.name == "admin")
            .first()
        )

        if role is None:
            raise RuntimeError(
                "Admin role was not found in the test database."
            )

        # -------------------------------------------------------------------
        # Avoid creating a duplicate role assignment if the user is already
        # an admin.
        # -------------------------------------------------------------------
        existing = (
            db.query(UserRole)
            .filter(
                UserRole.user_id == user_id,
                UserRole.role_id == role.id,
            )
            .first()
        )

        if existing is None:
            db.add(
                UserRole(
                    user_id=user_id,
                    role_id=role.id,
                )
            )

            db.commit()

    finally:
        db.close()