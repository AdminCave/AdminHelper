# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Per-user isolation for /api/connections reads (regression for the audit IDOR).

A non-admin user is assigned (user_servers) to specific servers and must only
see the connections of those servers — mirroring the FRP-visitor scoping in
frp/generate_router.py. Before the fix, GET /api/connections returned EVERY
connection (host/username/visitor-port) of every server to any non-admin.
"""

from app.core.auth import hash_api_key
from app.modules.api_keys.models import ApiKey
from app.modules.connections.models import Connection
from app.modules.servers.models import Server


def _login(client, username: str, password: str) -> str:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _seed_two_servers(db):
    db.add_all(
        [
            Server(id="srv-a", name="A", hostname="a.local"),
            Server(id="srv-b", name="B", hostname="b.local"),
            Connection(
                id="c-a", name="conn-a", kind="ssh", host="10.0.0.1", port=22, server_id="srv-a"
            ),
            Connection(
                id="c-b", name="conn-b", kind="ssh", host="10.0.0.2", port=22, server_id="srv-b"
            ),
        ]
    )
    db.commit()


def test_nonadmin_sees_only_assigned_server_connections(test_client, db_session, normal_user):
    _seed_two_servers(db_session)
    normal_user.servers.append(db_session.get(Server, "srv-a"))
    db_session.commit()

    token = _login(test_client, "viewer", "viewerpass")
    r = test_client.get("/api/connections", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    ids = {c["id"] for c in r.json()}
    assert ids == {"c-a"}, f"non-admin leaked foreign-server connections: {ids}"


def test_admin_sees_all_connections(test_client, db_session, admin_user):
    _seed_two_servers(db_session)
    token = _login(test_client, "admin", "adminpass")
    r = test_client.get("/api/connections", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert {c["id"] for c in r.json()} == {"c-a", "c-b"}


def test_nonadmin_cannot_touch_foreign_connection(test_client, db_session, normal_user):
    _seed_two_servers(db_session)
    normal_user.servers.append(db_session.get(Server, "srv-a"))
    db_session.commit()

    token = _login(test_client, "viewer", "viewerpass")
    # own server: allowed
    assert (
        test_client.post(
            "/api/connections/c-a/touch", headers={"Authorization": f"Bearer {token}"}
        ).status_code
        == 200
    )
    # foreign server: 404 (must not leak existence or set last_used)
    assert (
        test_client.post(
            "/api/connections/c-b/touch", headers={"Authorization": f"Bearer {token}"}
        ).status_code
        == 404
    )


def test_server_bound_write_key_cannot_update_foreign_connection(test_client, db_session):
    # 1.50: the write path (PUT) must scope like GET/touch. A server-bound
    # read_write key must not update a connection of another server it cannot see.
    _seed_two_servers(db_session)
    raw = "rw-srv-a-key"
    db_session.add(
        ApiKey(name="k", hashed_key=hash_api_key(raw), permission="read_write", server_id="srv-a")
    )
    db_session.commit()
    hdr = {"X-API-Key": raw}
    # own server: allowed
    assert (
        test_client.put("/api/connections/c-a", json={"name": "renamed"}, headers=hdr).status_code
        == 200
    )
    # foreign server: 404 (must not leak existence or modify)
    assert (
        test_client.put("/api/connections/c-b", json={"name": "hijack"}, headers=hdr).status_code
        == 404
    )
