"""Fixtures for the Phase 1 web-app test suite.

Runs against a REAL PostgreSQL database, not SQLite.

The test suite can run in either of these environments:

1. Directly on the host:
       PostgreSQL -> 127.0.0.1:15432
       Redis      -> 127.0.0.1:6379

2. Inside the Docker backend container:
       PostgreSQL -> postgres:5432
       Redis      -> redis:6379

IMPORTANT:
All environment variables must be configured BEFORE importing any
`app.*` module because application configuration/database modules may
read environment variables during import.

IMPORTANT FOR HOST PYTEST:
Docker service names such as `postgres` and `redis` are NOT resolvable
from Windows. Therefore host pytest ALWAYS uses the published localhost
ports.
"""

from __future__ import annotations

import os


# ===========================================================================
# TEST DATABASE CONFIGURATION
# ===========================================================================
#
# HOST:
#     PostgreSQL -> 127.0.0.1:15432
#
# DOCKER:
#     PostgreSQL -> postgres:5432
#
# IMPORTANT:
# On Windows / host pytest we intentionally DO NOT inherit DATABASE_URL or
# TEST_DATABASE_URL because either may contain the Docker-only hostname
# "postgres".
#
# This prevents errors such as:
#
#     could not translate host name "postgres"
#
# Docker uses the service hostname "postgres".
# Windows uses the published host port 15432.
#

if os.path.exists("/.dockerenv"):
    TEST_DATABASE_URL = (
        os.environ.get("TEST_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or (
            "postgresql+psycopg2://"
            "postgres:postgres@postgres:5432/"
            "aster_row_test"
        )
    )
else:
    # Windows / host pytest must ALWAYS use localhost.
    TEST_DATABASE_URL = (
        "postgresql+psycopg2://"
        "postgres:postgres@127.0.0.1:15432/"
        "aster_row_test"
    )

os.environ["DATABASE_URL"] = TEST_DATABASE_URL


# ===========================================================================
# REDIS CONFIGURATION
# ===========================================================================
#
# HOST:
#     redis://127.0.0.1:6379/0
#
# DOCKER:
#     redis://redis:6379/0
#
# IMPORTANT:
# On Windows / host pytest we intentionally do NOT inherit a Docker Redis
# hostname such as "redis".
#

if os.path.exists("/.dockerenv"):
    TEST_REDIS_URL = (
        os.environ.get("TEST_REDIS_URL")
        or os.environ.get("REDIS_URL")
        or "redis://redis:6379/0"
    )
else:
    # Windows / host pytest must ALWAYS use localhost.
    TEST_REDIS_URL = "redis://127.0.0.1:6379/0"

os.environ["REDIS_URL"] = TEST_REDIS_URL


# ===========================================================================
# GENERAL TEST CONFIGURATION
# ===========================================================================
#
# The web test suite must use the deterministic mock LLM instead of making
# real Gemini/API requests.
#

os.environ["USE_MOCK_LLM"] = "1"

# Web tests intentionally create temporary accounts.
# Production signup remains disabled in normal application configuration.
os.environ["SELF_SIGNUP_ENABLED"] = "true"
os.environ["LOGIN_ALLOWLIST_ENABLED"] = "false"


# ===========================================================================
# TEST AUTH SECRET
# ===========================================================================
#
# Deterministic test-only authentication secret.
#
# This is intentionally NOT suitable for production.
#
# The value is 32+ bytes so the JWT library does not emit an insecure-key
# length warning during tests.
#

os.environ["AUTH_SECRET"] = "test-secret-not-for-production-32!"


# ===========================================================================
# RATE LIMITING
# ===========================================================================
#
# General web tests do not need to consume rate-limit buckets.
#
# Dedicated rate-limit tests explicitly enable the limiter through their
# own monkeypatching/configuration.
#

os.environ["RATE_LIMIT_ENABLED"] = "false"


# ===========================================================================
# SYNCHRONIZE ALREADY-IMPORTED APPLICATION CONFIGURATION
# ===========================================================================
#
# IMPORTANT:
# During a combined pytest run, another conftest.py may import application
# modules before this conftest.py is processed.
#
# app.db.base creates its SQLAlchemy engine at IMPORT TIME:
#
#     DATABASE_URL = os.environ.get(...)
#     engine = create_engine(DATABASE_URL, ...)
#
# Therefore changing os.environ["DATABASE_URL"] after app.db.base has already
# been imported does NOT change the existing SQLAlchemy engine.
#
# We therefore synchronize:
#
#   1. app.config.DATABASE_URL
#   2. app.config.REDIS_URL
#   3. app.db.base.DATABASE_URL
#   4. app.db.base.engine
#   5. app.db.base.SessionLocal
#   6. cached rate-limit Redis client
#

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import config as app_config
from app.db import base as app_db_base


# ---------------------------------------------------------------------------
# Synchronize application configuration.
# ---------------------------------------------------------------------------

app_config.DATABASE_URL = TEST_DATABASE_URL
app_config.REDIS_URL = TEST_REDIS_URL


# ---------------------------------------------------------------------------
# Recreate the SQLAlchemy engine using the correct test database.
# ---------------------------------------------------------------------------
#
# app.db.base.engine may already have been created using a Docker hostname.
# Dispose the old engine first and then replace it.
#

try:
    app_db_base.engine.dispose()
except Exception:
    pass


app_db_base.DATABASE_URL = TEST_DATABASE_URL

app_db_base.engine = create_engine(
    TEST_DATABASE_URL,
    pool_pre_ping=True,
    future=True,
)


# ---------------------------------------------------------------------------
# Rebind SessionLocal to the corrected engine.
# ---------------------------------------------------------------------------

app_db_base.SessionLocal = sessionmaker(
    bind=app_db_base.engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


# ---------------------------------------------------------------------------
# Reset cached Redis client.
# ---------------------------------------------------------------------------
#
# This guarantees that the rate limiter uses the corrected host/Docker
# Redis URL rather than a client created earlier with the wrong hostname.
#

from app.security import rate_limit as _rate_limit

_rate_limit._client = None
_rate_limit._client_url = None


# ===========================================================================
# APPLICATION IMPORTS
# ===========================================================================
#
# These imports intentionally happen AFTER environment configuration and
# database/Redis synchronization.
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

        1. Clear Redis rate-limit state.
        2. Drop all tables.
        3. Recreate all tables.
        4. Create the standard roles.
        5. Create the standard permissions.
        6. Attach default permissions to roles.

    After each test:

        7. Drop all tables.

    This prevents test state from leaking between tests.
    """

    # -----------------------------------------------------------------------
    # Clear Redis rate-limit state.
    #
    # Rate-limit tests intentionally modify Redis counters. Without clearing
    # Redis between tests, a previous test/run can leave a signup/login
    # counter behind and cause a fresh test to receive HTTP 429 immediately.
    #
    # Redis failures must not make unrelated database setup fail because the
    # application's rate limiter is designed to fail open.
    # -----------------------------------------------------------------------

    try:
        redis_client = _rate_limit._get_client()
        redis_client.flushdb()
    except Exception:
        pass

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