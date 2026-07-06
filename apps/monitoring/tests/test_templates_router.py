# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Template-assignment router (6.57): the template_sync functions are well tested, but the router on
top was not. Pins the read-then-insert duplicate -> 409 and, critically, the IntegrityError -> 409
mapping for the concurrent-assign race (per models.py the only race-free safeguard) — a slip there
would surface as a 500 at the server module, not a 409."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.auth import require_internal
from app.core.database import get_db
from app.models import Base, MonitorTemplate


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


def _seed_template(factory, tid="tpl-1"):
    with factory() as db:
        db.add(MonitorTemplate(id=tid, name="T", check_definitions="[]", alert_definitions="[]"))
        db.commit()
    return tid


_BODY = {"server_id": "srv-1", "hostname": "h", "server_name": "n"}


def test_assign_unknown_template_returns_404(client):
    c, _factory = client
    assert c.post("/templates/does-not-exist/assign", json=_BODY).status_code == 404


def test_duplicate_assign_returns_409(client):
    c, factory = client
    tid = _seed_template(factory)
    assert c.post(f"/templates/{tid}/assign", json=_BODY).status_code == 200
    # Second assign of the same (template, server) -> 409 via the read-then-insert check.
    assert c.post(f"/templates/{tid}/assign", json=_BODY).status_code == 409


def test_integrity_error_race_maps_to_409(client, monkeypatch):
    # Two concurrent requests both pass the read-then-insert check; one loses on the unique
    # constraint. That IntegrityError must map to 409, not bubble up as a 500.
    from sqlalchemy.exc import IntegrityError

    c, factory = client
    tid = _seed_template(factory)

    def _raise(*a, **k):
        raise IntegrityError("stmt", {}, Exception("unique constraint"))

    monkeypatch.setattr("app.routers.templates.apply_template", _raise)
    assert c.post(f"/templates/{tid}/assign", json=_BODY).status_code == 409


def test_delete_unknown_template_returns_404(client):
    c, _factory = client
    assert c.delete("/templates/does-not-exist").status_code == 404


def test_delete_template_removes_it(client):
    c, factory = client
    tid = _seed_template(factory)
    assert c.delete(f"/templates/{tid}").status_code == 204
    with factory() as db:
        assert db.query(MonitorTemplate).filter(MonitorTemplate.id == tid).first() is None
