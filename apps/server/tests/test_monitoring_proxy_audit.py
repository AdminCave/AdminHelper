# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Writes through the monitoring proxy land one audit row each: method, path and the
monitoring's status, never the request body or query. An error after sending lands an
`error` row; reads, refused paths and forwards that were never sent write none. Every
forward names the acting admin in X-AH-Actor-Id/-Name, built from the session and never
from a client's header (R-1636)."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.auth import hash_password
from app.core.request_context import Actor
from app.modules.audit.models import AuditLog
from app.modules.monitoring_proxy import router as mp
from app.modules.users.models import User


def _headers(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _monitoring(monkeypatch, status=200):
    """The monitoring service in-process; returns the (method, raw path) it was asked for."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.raw_path))
        return httpx.Response(status, json={"answer": status})

    monkeypatch.setattr(mp, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return seen


def _rows(db, action):
    return db.query(AuditLog).filter(AuditLog.action == action).all()


def _proxy_rows(db):
    return db.query(AuditLog).filter(AuditLog.action.like("monitoring.%")).all()


def _cells(row):
    return [str(getattr(row, col.key)) for col in AuditLog.__table__.columns]


def test_put_is_audited_without_body_or_query(test_client, db_session, admin_user, monkeypatch):
    seen = _monitoring(monkeypatch, 200)
    r = test_client.put(
        "/api/monitoring/checks/c1?server_id=s1",
        json={"smtp_password": "pw-3c9d"},
        headers=_headers(test_client),
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"answer": 200}  # the browser still gets the monitoring's answer
    assert seen == [("PUT", b"/checks/c1?server_id=s1")]

    rows = _rows(db_session, "monitoring.put")
    assert len(rows) == 1
    row = rows[0]
    assert (row.actor_type, row.actor_label) == ("user", "admin")
    assert (row.object_type, row.object_label) == ("monitoring", "checks/c1")
    assert row.detail == "status=200"
    assert row.status == "success"
    for cell in _cells(row):
        assert "pw-3c9d" not in cell
        assert "server_id" not in cell


def test_post_with_error_status_is_a_failure(test_client, db_session, admin_user, monkeypatch):
    _monitoring(monkeypatch, 404)
    r = test_client.post("/api/monitoring/checks/c1/toggle", headers=_headers(test_client))
    assert r.status_code == 404, r.text

    rows = _rows(db_session, "monitoring.post")
    assert len(rows) == 1
    assert rows[0].object_label == "checks/c1/toggle"
    assert rows[0].status == "failure"
    assert rows[0].detail == "status=404"


def test_delete_keeps_the_encoded_path(test_client, db_session, admin_user, monkeypatch):
    _monitoring(monkeypatch, 200)
    r = test_client.delete(
        "/api/monitoring/templates/tpl-1/assign-tag/web%231%3Fx", headers=_headers(test_client)
    )
    assert r.status_code == 200, r.text

    rows = _rows(db_session, "monitoring.delete")
    assert len(rows) == 1
    assert rows[0].object_label == "templates/tpl-1/assign-tag/web%231%3Fx"
    assert rows[0].status == "success"


def test_get_is_not_audited(test_client, db_session, admin_user, monkeypatch):
    # The same route writes for PUT/POST/DELETE (tests above); a read forwards and writes none.
    seen = _monitoring(monkeypatch, 200)
    h = _headers(test_client)
    before = db_session.query(AuditLog).count()

    r = test_client.get("/api/monitoring/status", headers=h)
    assert r.status_code == 200, r.text
    assert seen == [("GET", b"/status")]
    assert db_session.query(AuditLog).count() == before


def test_refused_path_is_not_audited(test_client, db_session, admin_user, monkeypatch):
    seen = _monitoring(monkeypatch, 200)
    r = test_client.put("/api/monitoring/admin/keys", json={}, headers=_headers(test_client))
    assert r.status_code == 400, r.text
    assert seen == []
    assert _proxy_rows(db_session) == []


def _failing_monitoring(monkeypatch, error):
    def handler(request: httpx.Request) -> httpx.Response:
        raise error("transport-msg-7b2e", request=request)

    monkeypatch.setattr(mp, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize(
    "error",
    [httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout, httpx.UnsupportedProtocol],
)
def test_unsent_forward_is_not_audited(test_client, db_session, admin_user, monkeypatch, error):
    # Nothing reached the monitoring, so nothing changed: no row, however the proxy answers
    # the browser (500 today; R-0655 may turn it into a 502). Counterpart: the test below.
    _failing_monitoring(monkeypatch, error)
    client = TestClient(test_client.app, raise_server_exceptions=False)
    r = client.put("/api/monitoring/checks/c1", json={}, headers=_headers(client))
    assert r.status_code >= 500, r.text
    assert _proxy_rows(db_session) == []


@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.ReadError, httpx.RemoteProtocolError])
def test_error_after_sending_is_audited(test_client, db_session, admin_user, monkeypatch, error):
    # The monitoring may have applied the change before the error: one `error` row, with the
    # type name only.
    _failing_monitoring(monkeypatch, error)
    client = TestClient(test_client.app, raise_server_exceptions=False)
    r = client.put("/api/monitoring/checks/c1", json={}, headers=_headers(client))
    assert r.status_code >= 500, r.text

    rows = _rows(db_session, "monitoring.put")
    assert len(rows) == 1
    row = rows[0]
    assert (row.actor_type, row.actor_label) == ("user", "admin")
    assert (row.object_type, row.object_label) == ("monitoring", "checks/c1")
    assert row.status == "error"
    assert row.detail == f"error={error.__name__}"
    for cell in _cells(row):
        assert "transport-msg-7b2e" not in cell
        assert mp._MONITOR_BASE not in cell


def test_the_admin_proxy_closes_its_session_before_the_forward(
    test_client, db_session, admin_user, monkeypatch
):
    """R-1695: the admin proxy hands back the session of its auth checks before it waits on
    the monitoring; the audit row afterwards still lands."""
    from sqlalchemy.orm import Session, sessionmaker

    from app.core import database
    from app.main import app

    opened: list[Session] = []
    closed: list[Session] = []

    class _Tracked(Session):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            opened.append(self)

        def close(self):
            closed.append(self)
            super().close()

    factory = sessionmaker(bind=db_session.connection(), autoflush=False, class_=_Tracked)

    def _get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[database.get_db] = _get_db
    headers = _headers(test_client)
    open_at_forward: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        open_at_forward.append(len(opened) - len(closed))
        return httpx.Response(200, json={"answer": 200})

    monkeypatch.setattr(mp, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    r = test_client.put("/api/monitoring/checks/c1", json={}, headers=headers)

    assert r.status_code == 200, r.text
    assert open_at_forward == [0]
    assert len(_rows(db_session, "monitoring.put")) == 1


def _monitoring_headers(monkeypatch):
    """The monitoring service in-process; returns the headers of each request it got."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers)
        return httpx.Response(200, json={})

    monkeypatch.setattr(mp, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return seen


def test_the_forward_names_the_admin_not_the_client(
    test_client, db_session, admin_user, monkeypatch
):
    seen = _monitoring_headers(monkeypatch)
    forged = {"X-AH-Actor-Id": "user:999", "X-AH-Actor-Name": "mallory"}
    r = test_client.post(
        "/api/monitoring/exceptions", json={}, headers={**_headers(test_client), **forged}
    )
    assert r.status_code == 200, r.text
    assert seen[0].get_list("x-ah-actor-id") == [f"user:{admin_user.id}"]
    assert seen[0].get_list("x-ah-actor-name") == ["admin"]


def test_a_name_beyond_ascii_arrives_percent_encoded(test_client, db_session, monkeypatch):
    db_session.add(
        User(username="jürgen", hashed_password=hash_password("pw-jürgen"), is_admin=True)
    )
    db_session.commit()
    seen = _monitoring_headers(monkeypatch)
    login = test_client.post(
        "/api/auth/login", json={"username": "jürgen", "password": "pw-jürgen"}
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    r = test_client.get("/api/monitoring/exceptions", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert seen[0]["x-ah-actor-name"] == "j%C3%BCrgen"


def test_without_a_bound_actor_the_forward_names_none(
    test_client, db_session, admin_user, monkeypatch
):
    seen = _monitoring_headers(monkeypatch)
    headers = _headers(test_client)
    # Every route of the proxy binds an admin; this stands for a caller that binds none.
    monkeypatch.setattr(mp, "actor_from_request", lambda request: Actor())
    r = test_client.get(
        "/api/monitoring/exceptions", headers={**headers, "X-AH-Actor-Id": "user:999"}
    )
    assert r.status_code == 200, r.text
    assert "x-ah-actor-id" not in seen[0] and "x-ah-actor-name" not in seen[0]
