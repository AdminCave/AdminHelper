# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Admin router agent-key regeneration (6.57): POST regenerates — the old key is deleted and a fresh
raw key is returned exactly once, while the DB only ever holds the hash. A slip could leave two live
keys or fail to return/rotate the raw key. Untested until now."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.auth import require_internal
from app.core.database import get_db
from app.models import Base, MonitorAgentKey


@pytest.fixture()
def client(monkeypatch):
    from app.main import app

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_internal] = lambda: None
    yield TestClient(app), factory
    app.dependency_overrides.clear()


def test_agent_key_regeneration_returns_a_new_raw_key_once(client):
    c, factory = client
    r1 = c.post("/agent-keys/srv-1")
    assert r1.status_code == 200, r1.text
    key1 = r1.json()["apiKey"]
    assert key1

    # Regenerate: the old key is replaced and a NEW raw key is returned.
    r2 = c.post("/agent-keys/srv-1")
    assert r2.status_code == 200, r2.text
    key2 = r2.json()["apiKey"]
    assert key2 and key2 != key1, "regeneration must return a fresh raw key"

    with factory() as db:
        rows = db.query(MonitorAgentKey).filter(MonitorAgentKey.server_id == "srv-1").all()
        assert len(rows) == 1, "old key must be replaced, not accumulated"
        assert rows[0].hashed_key != key2, "DB stores only the hash, never the raw key"
