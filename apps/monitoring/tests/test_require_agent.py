# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""require_agent auth flow (6.54): every endpoint suite overrides require_agent, so the real flow —
SHA-256 hash lookup in monitor_agent_keys, the internal-key passthrough as '__internal__', and 401 on
a missing/wrong key — was untested. test_auth.py only covers the _key_matches building block. A
regression comparing the raw key instead of hash_key would lock out every real agent (or worse, break
the key/server binding), and nothing would go red. Tested by calling require_agent directly against a
real sqlite DB and a fake request."""

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core import auth
from app.core.auth import require_agent
from app.models import Base, MonitorAgentKey


class _Req:
    def __init__(self, api_key=None):
        self.headers = {"X-API-Key": api_key} if api_key is not None else {}


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _seed_key(db, raw="test-raw-key", server_id="srv-1"):
    db.add(MonitorAgentKey(id="k1", server_id=server_id, hashed_key=MonitorAgentKey.hash_key(raw)))
    db.commit()
    return raw


def test_valid_agent_key_binds_to_its_server(db):
    raw = _seed_key(db)
    # The hashed lookup must resolve the raw key back to its bound server_id.
    assert require_agent(_Req(raw), db) == "srv-1"


def test_missing_key_is_401(db):
    with pytest.raises(HTTPException) as exc:
        require_agent(_Req(), db)
    assert exc.value.status_code == 401


def test_wrong_key_is_401(db):
    _seed_key(db)
    with pytest.raises(HTTPException) as exc:
        require_agent(_Req("not-the-key"), db)
    assert exc.value.status_code == 401


def test_internal_key_passes_through_as_internal(db, monkeypatch):
    monkeypatch.setattr(auth, "INTERNAL_API_KEY", "internal-secret")
    assert require_agent(_Req("internal-secret"), db) == "__internal__"
