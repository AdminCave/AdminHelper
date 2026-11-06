# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Session history of a connection (R-1068): touch begins a session, .../end ends it, the list
shows the newest ones in the scope of the connection list, and the server keeps 90 days."""

from datetime import timedelta

from app.core.time import utcnow_naive
from app.modules.connections.models import Connection, ConnectionSession
from app.modules.servers.models import Server


def _login(client, username: str, password: str) -> dict[str, str]:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _seed(db):
    db.add_all(
        [
            Server(id="srv-a", name="A", hostname="a.local"),
            Server(id="srv-b", name="B", hostname="b.local"),
            Connection(id="c-a", name="conn-a", kind="ssh", host="192.0.2.1", server_id="srv-a"),
            Connection(id="c-b", name="conn-b", kind="rdp", host="192.0.2.2", server_id="srv-b"),
        ]
    )
    db.commit()


def test_touch_begins_a_session_with_the_device_and_end_closes_it(
    test_client, db_session, admin_user
):
    _seed(db_session)
    h = _login(test_client, "admin", "adminpass")

    r = test_client.post("/api/connections/c-a/touch", json={"device": "laptop-01"}, headers=h)
    assert r.status_code == 200, r.text
    sid = r.json()["sessionId"]
    assert r.json()["id"] == "c-a" and r.json()["lastUsed"]

    listed = test_client.get("/api/connections/c-a/sessions", headers=h).json()
    assert [(s["id"], s["device"], s["endedAt"]) for s in listed] == [(sid, "laptop-01", None)]
    assert listed[0]["startedAt"].endswith("+00:00")

    r = test_client.post(f"/api/connections/c-a/sessions/{sid}/end", headers=h)
    assert r.status_code == 200, r.text
    ended = r.json()["endedAt"]
    assert ended and ended >= r.json()["startedAt"]
    # A second end keeps the first one.
    again = test_client.post(f"/api/connections/c-a/sessions/{sid}/end", headers=h).json()
    assert again["endedAt"] == ended
    row = db_session.get(ConnectionSession, sid)
    assert row.user_id == admin_user.id


def test_touch_without_a_body_still_works_and_has_no_device(test_client, db_session, admin_user):
    _seed(db_session)
    h = _login(test_client, "admin", "adminpass")
    r = test_client.post("/api/connections/c-a/touch", headers=h)
    assert r.status_code == 200, r.text
    assert db_session.get(ConnectionSession, r.json()["sessionId"]).device is None


def test_touch_refuses_a_device_with_control_characters(test_client, db_session, admin_user):
    _seed(db_session)
    h = _login(test_client, "admin", "adminpass")
    for device in ("evil\nline", "", "x" * 256):
        r = test_client.post("/api/connections/c-a/touch", json={"device": device}, headers=h)
        assert r.status_code == 422, (device, r.text)
    assert db_session.query(ConnectionSession).count() == 0


def test_list_is_newest_first_with_limit_default_five(test_client, db_session, admin_user):
    _seed(db_session)
    now = utcnow_naive()
    db_session.add_all(
        ConnectionSession(id=f"s{i}", connection_id="c-a", started_at=now - timedelta(hours=i))
        for i in range(7)
    )
    db_session.commit()
    h = _login(test_client, "admin", "adminpass")

    r = test_client.get("/api/connections/c-a/sessions", headers=h)
    assert [s["id"] for s in r.json()] == ["s0", "s1", "s2", "s3", "s4"]
    r = test_client.get("/api/connections/c-a/sessions?limit=2", headers=h)
    assert [s["id"] for s in r.json()] == ["s0", "s1"]
    for bad in ("0", "51"):
        assert (
            test_client.get(f"/api/connections/c-a/sessions?limit={bad}", headers=h).status_code
            == 422
        )


def test_sessions_older_than_90_days_are_hidden_and_purged_on_the_next_write(
    test_client, db_session, admin_user
):
    _seed(db_session)
    now = utcnow_naive()
    db_session.add_all(
        [
            ConnectionSession(id="old", connection_id="c-b", started_at=now - timedelta(days=91)),
            ConnectionSession(id="young", connection_id="c-b", started_at=now - timedelta(days=89)),
        ]
    )
    db_session.commit()
    h = _login(test_client, "admin", "adminpass")

    assert [
        s["id"] for s in test_client.get("/api/connections/c-b/sessions", headers=h).json()
    ] == ["young"]
    # A touch on another connection purges every connection's old entries.
    assert test_client.post("/api/connections/c-a/touch", headers=h).status_code == 200
    db_session.expire_all()
    assert {s.id for s in db_session.query(ConnectionSession).filter_by(connection_id="c-b")} == {
        "young"
    }


def test_scope_follows_the_connection_list(test_client, db_session, admin_user, normal_user):
    _seed(db_session)
    normal_user.servers.append(db_session.get(Server, "srv-a"))
    db_session.commit()
    viewer = _login(test_client, "viewer", "viewerpass")
    admin = _login(test_client, "admin", "adminpass")
    sid = test_client.post("/api/connections/c-b/touch", headers=admin).json()["sessionId"]

    assert test_client.get("/api/connections/c-b/sessions", headers=viewer).status_code == 404
    assert (
        test_client.post(f"/api/connections/c-b/sessions/{sid}/end", headers=viewer).status_code
        == 404
    )
    assert test_client.post("/api/connections/c-b/touch", headers=viewer).status_code == 404
    # In its own scope the viewer sees every user's sessions of the connection.
    own = test_client.post("/api/connections/c-a/touch", headers=admin).json()["sessionId"]
    listed = test_client.get("/api/connections/c-a/sessions", headers=viewer).json()
    assert [s["id"] for s in listed] == [own]


def test_only_the_user_who_began_a_session_ends_it(
    test_client, db_session, admin_user, normal_user
):
    _seed(db_session)
    normal_user.servers.append(db_session.get(Server, "srv-a"))
    db_session.commit()
    viewer = _login(test_client, "viewer", "viewerpass")
    admin = _login(test_client, "admin", "adminpass")
    sid = test_client.post("/api/connections/c-a/touch", headers=admin).json()["sessionId"]

    r = test_client.post(f"/api/connections/c-a/sessions/{sid}/end", headers=viewer)
    assert r.status_code == 404
    assert db_session.get(ConnectionSession, sid).ended_at is None
    # The session belongs to its connection: another connection's path does not reach it.
    assert (
        test_client.post(f"/api/connections/c-b/sessions/{sid}/end", headers=admin).status_code
        == 404
    )
    r = test_client.post(f"/api/connections/c-a/sessions/{sid}/end", headers=admin)
    assert r.status_code == 200, r.text

    # A session without a user (an API key's, or its user deleted) has no owner to end it.
    db_session.add(
        ConnectionSession(id="ownerless", connection_id="c-a", started_at=utcnow_naive())
    )
    db_session.commit()
    r = test_client.post("/api/connections/c-a/sessions/ownerless/end", headers=admin)
    assert r.status_code == 404


def test_deleting_the_connection_deletes_its_sessions(test_client, db_session, admin_user):
    _seed(db_session)
    h = _login(test_client, "admin", "adminpass")
    sid = test_client.post("/api/connections/c-a/touch", headers=h).json()["sessionId"]
    assert test_client.delete("/api/connections/c-a", headers=h).status_code == 204
    db_session.expire_all()
    assert db_session.get(ConnectionSession, sid) is None
