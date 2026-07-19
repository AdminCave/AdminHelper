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


class TestTagAssignments:
    """T9: template→tag bindings — CRUD only; materialization is tag_sync's job."""

    def _mk_template(self, c):
        r = c.post("/templates", json={"name": "T", "check_definitions": []})
        assert r.status_code == 201
        return r.json()["id"]

    def test_assign_and_list(self, client):
        client, _factory = client
        tid = self._mk_template(client)
        r = client.post(f"/templates/{tid}/assign-tag", json={"tag": "web"})
        assert r.status_code == 201
        assert r.json() == {"id": r.json()["id"], "templateId": tid, "tag": "web"}

        listed = {t["id"]: t for t in client.get("/templates").json()}
        assert [ta["tag"] for ta in listed[tid]["tagAssignments"]] == ["web"]
        assert client.get(f"/templates/{tid}").json()["tagAssignments"][0]["tag"] == "web"

    def test_duplicate_tag_is_409(self, client):
        client, _factory = client
        tid = self._mk_template(client)
        assert client.post(f"/templates/{tid}/assign-tag", json={"tag": "web"}).status_code == 201
        assert client.post(f"/templates/{tid}/assign-tag", json={"tag": "web"}).status_code == 409

    def test_blank_tag_is_422(self, client):
        client, _factory = client
        tid = self._mk_template(client)
        assert client.post(f"/templates/{tid}/assign-tag", json={"tag": "  "}).status_code == 422

    def test_unknown_template_is_404(self, client):
        client, _factory = client
        assert client.post("/templates/nope/assign-tag", json={"tag": "web"}).status_code == 404

    def test_unassign_tag(self, client):
        client, _factory = client
        tid = self._mk_template(client)
        client.post(f"/templates/{tid}/assign-tag", json={"tag": "web"})
        assert client.delete(f"/templates/{tid}/assign-tag/web").status_code == 204
        assert client.delete(f"/templates/{tid}/assign-tag/web").status_code == 404
        assert client.get(f"/templates/{tid}").json()["tagAssignments"] == []

    def test_server_assignment_carries_manual_source(self, client):
        client, _factory = client
        tid = self._mk_template(client)
        r = client.post(
            f"/templates/{tid}/assign",
            json={"server_id": "srv-1", "hostname": "h", "server_name": "n"},
        )
        assert r.status_code == 200
        assignments = client.get(f"/templates/{tid}").json()["assignments"]
        assert assignments[0]["source"] == "manual"

    def test_tag_with_slash_is_rejected_at_the_boundary(self, client):
        client, _factory = client
        tid = self._mk_template(client)
        # '/' would make the DELETE path unmatchable (percent-decoding happens
        # before routing) — the binding could never be removed again.
        assert (
            client.post(f"/templates/{tid}/assign-tag", json={"tag": "env/prod"}).status_code == 422
        )

    def test_tag_with_space_round_trips(self, client):
        client, _factory = client
        tid = self._mk_template(client)
        assert (
            client.post(f"/templates/{tid}/assign-tag", json={"tag": "web prod"}).status_code == 201
        )
        assert client.delete(f"/templates/{tid}/assign-tag/web%20prod").status_code == 204

    def test_tag_sync_endpoint_502_when_hub_unavailable(self, client, monkeypatch):
        client, _factory = client
        import app.routers.templates as templates_mod

        monkeypatch.setattr(templates_mod, "sync_tag_assignments", lambda db: None)
        assert client.post("/templates/tag-sync").status_code == 502

    def test_tag_sync_endpoint_returns_counts(self, client, monkeypatch):
        client, _factory = client
        import app.routers.templates as templates_mod

        monkeypatch.setattr(
            templates_mod, "sync_tag_assignments", lambda db: {"created": 2, "removed": 1}
        )
        r = client.post("/templates/tag-sync")
        assert r.status_code == 200
        assert r.json() == {"created": 2, "removed": 1}

    def test_assign_tag_triggers_sync(self, client, monkeypatch):
        client, _factory = client
        import app.routers.templates as templates_mod

        calls = {"n": 0}
        monkeypatch.setattr(
            templates_mod,
            "sync_tag_assignments",
            lambda db: calls.__setitem__("n", calls["n"] + 1) or {"created": 0, "removed": 0},
        )
        tid = self._mk_template(client)
        client.post(f"/templates/{tid}/assign-tag", json={"tag": "web"})
        client.delete(f"/templates/{tid}/assign-tag/web")
        assert calls["n"] == 2

    def test_assign_tag_survives_a_raising_sync(self, client, monkeypatch):
        # Best-effort guarantee: a sync that raises must not fail the CRUD call.
        client, _factory = client
        import app.routers.templates as templates_mod

        def boom(db):
            raise RuntimeError("sync exploded")

        monkeypatch.setattr(templates_mod, "sync_tag_assignments", boom)
        tid = self._mk_template(client)
        assert client.post(f"/templates/{tid}/assign-tag", json={"tag": "web"}).status_code == 201
        assert client.delete(f"/templates/{tid}/assign-tag/web").status_code == 204
