# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""GET /api/servers/summary: id, name and host name of every server, sorted by name, for
the server assignment in the web panel's user dialog; admin only (R-0723)."""

from app.modules.connections.models import Connection
from app.modules.servers.models import Server


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_admin_gets_id_name_and_hostname_sorted_by_name(test_client, db_session, admin_user):
    for sid, name in (("s-b", "web-01"), ("s-a", "db-01")):
        db_session.add(Server(id=sid, name=name, hostname=f"{name}.example"))
        db_session.add(
            Connection(
                id=f"c-{sid}", name=f"conn-{sid}", kind="ssh", host="h", port=22, server_id=sid
            )
        )
    db_session.commit()

    r = test_client.get(
        "/api/servers/summary", headers=_auth(_login(test_client, "admin", "adminpass"))
    )

    assert r.status_code == 200, r.text
    assert r.json() == [
        {"id": "s-a", "name": "db-01", "hostname": "db-01.example"},
        {"id": "s-b", "name": "web-01", "hostname": "web-01.example"},
    ]


def test_an_empty_inventory_is_an_empty_list(test_client, db_session, admin_user):
    r = test_client.get(
        "/api/servers/summary", headers=_auth(_login(test_client, "admin", "adminpass"))
    )
    assert r.status_code == 200, r.text
    assert r.json() == []


def test_a_non_admin_gets_403(test_client, db_session, normal_user):
    r = test_client.get(
        "/api/servers/summary", headers=_auth(_login(test_client, "viewer", "viewerpass"))
    )
    assert r.status_code == 403, r.text


def test_without_a_token_it_is_401(test_client, db_session):
    r = test_client.get("/api/servers/summary")
    assert r.status_code == 401, r.text
