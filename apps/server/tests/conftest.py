# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared test fixtures: Postgres via testcontainers (local) or GitLab services (CI),
SAVEPOINT-based transaction-rollback pattern for test isolation."""

import os

# Set test defaults BEFORE app modules are imported.
os.environ.setdefault("DATA_DIR", "/tmp/adminhelper-test-data")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("ADMIN_PASSWORD", "testadmin")

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

import app.modules.ansible.models  # noqa: F401
import app.modules.api_keys.models  # noqa: F401
import app.modules.audit.models  # noqa: F401
import app.modules.connections.models  # noqa: F401
import app.modules.enrollment.models  # noqa: F401
import app.modules.frp.models  # noqa: F401
import app.modules.hooks.models  # noqa: F401
import app.modules.notifications.models  # noqa: F401

# Explicitly import all models — otherwise Base.metadata does not know about them.
import app.modules.servers.models  # noqa: F401
from app.core.auth import hash_password
from app.core.database import Base, get_db
from app.modules.users.models import User


def _normalize_postgres_url(raw_url: str) -> str:
    """Forces the psycopg3 driver — testcontainers provides
    'postgresql+psycopg2://' by default, GitLab services provide 'postgresql://',
    both must be rewritten to 'postgresql+psycopg://' so that SQLAlchemy does
    not try to import the non-installed psycopg2."""
    for old in ("postgresql+psycopg2://", "postgresql+asyncpg://", "postgresql://"):
        if raw_url.startswith(old):
            return "postgresql+psycopg://" + raw_url[len(old) :]
    return raw_url


@pytest.fixture(scope="session")
def pg_engine():
    """Postgres engine for the entire test session.

    - If the DATABASE_URL env is set (CI mode with GitLab services
      or dev setup with local Postgres) -> use that URL.
    - Otherwise -> testcontainers starts a Postgres 17-alpine container.

    Create the schema once per session via Base.metadata.create_all
    (faster than alembic upgrade head; Alembic drift is checked separately
    against the models set in test_alembic_consistency.py).
    """
    env_url = os.environ.get("DATABASE_URL", "").strip()
    if env_url:
        url = _normalize_postgres_url(env_url)
        engine = create_engine(url)
        Base.metadata.create_all(bind=engine)
        try:
            yield engine
        finally:
            Base.metadata.drop_all(bind=engine)
            engine.dispose()
        return

    # Local: testcontainers
    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("postgres:17-alpine") as pg:
        url = _normalize_postgres_url(pg.get_connection_url())
        engine = create_engine(url)
        Base.metadata.create_all(bind=engine)
        try:
            yield engine
        finally:
            engine.dispose()


@pytest.fixture()
def db_session(pg_engine):
    """A dedicated connection with an outer transaction per test.

    SAVEPOINT pattern: each test may call 'commit()', which only lands in
    the inner SAVEPOINT. At the end of the test the outer transaction rolls
    everything back — no DROP/CREATE per test, no data interference.
    """
    connection = pg_engine.connect()
    outer = connection.begin()

    SessionLocal = sessionmaker(bind=connection, autoflush=False, autocommit=False)
    session = SessionLocal()

    # Inner SAVEPOINT that is restarted on every session.commit().
    nested = connection.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def restart_savepoint(sess, trans):
        nonlocal nested
        if not nested.is_active:
            nested = connection.begin_nested()

    try:
        yield session
    finally:
        session.close()
        if outer.is_active:
            outer.rollback()
        connection.close()


@pytest.fixture()
def admin_user(db_session):
    user = User(
        username="admin",
        hashed_password=hash_password("adminpass"),
        is_admin=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def normal_user(db_session):
    user = User(
        username="viewer",
        hashed_password=hash_password("viewerpass"),
        is_admin=False,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def test_client(db_session):
    """FastAPI TestClient with an overridden DB dependency."""
    from fastapi.testclient import TestClient

    from app.main import app

    def _override_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_db
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()
