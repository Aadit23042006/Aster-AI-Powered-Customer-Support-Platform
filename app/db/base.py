"""SQLAlchemy engine/session wiring for the web application layer.

This module provides the PostgreSQL engine, SQLAlchemy session factory,
declarative Base, and FastAPI database dependency.

It is intentionally kept separate from `app/session.py`, which is the
existing in-memory per-turn LLM context store used by `Agent`.
"""

from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


# ---------------------------------------------------------------------------
# Database configuration
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:postgres@localhost:5432/aster_row",
)


# ---------------------------------------------------------------------------
# SQLAlchemy engine
# ---------------------------------------------------------------------------

# pool_pre_ping=True prevents SQLAlchemy from handing out stale/dead
# connections after idle periods.

# future=True keeps SQLAlchemy's modern 2.x behavior explicit.

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    future=True,
)


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

# SessionLocal is the application's reusable database-session factory.
#
# Important:
# - autoflush=False gives application code explicit control over flushing.
# - autocommit=False means transactions are committed explicitly.
# - expire_on_commit=False prevents ORM objects from being expired after
#   db.commit(). This is important because later attribute access should
#   not trigger an implicit database reload outside the active SQLAlchemy
#   execution context.
# - future=True enables SQLAlchemy 2.x style behavior.

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    future=True,
)


# ---------------------------------------------------------------------------
# Declarative base
# ---------------------------------------------------------------------------

class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""

    pass


# ---------------------------------------------------------------------------
# FastAPI database dependency
# ---------------------------------------------------------------------------

def get_db() -> Generator[Session, None, None]:
    """Provide one SQLAlchemy database session per FastAPI request.

    The session is always closed after the request, including when the
    request raises an exception.
    """
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()