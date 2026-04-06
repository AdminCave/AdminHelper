"""Shared test fixtures — in-memory SQLite + FastAPI TestClient."""

import os
os.environ.setdefault("DATA_DIR", "/tmp/srm-test-data")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("ADMIN_PASSWORD", "testadmin")

import pytest
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.core.auth import hash_password
from app.modules.users.models import User
# Import all models so Base.metadata knows every table (foreign key resolution)
import app.modules.servers.models  # noqa: F401
import app.modules.connections.models  # noqa: F401
import app.modules.api_keys.models  # noqa: F401
import app.modules.frp.models  # noqa: F401


@pytest.fixture()
def db_session():
    """In-memory SQLite session, tables created fresh per test."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def admin_user(db_session):
    """Create an admin user in the test DB."""
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
    """Create a non-admin user in the test DB."""
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
    """FastAPI TestClient with DB dependency overridden."""
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
