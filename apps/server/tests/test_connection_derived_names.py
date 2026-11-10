# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""R-1210 (Kevin 2026-11-09, 3a and 4a): a connection of a server stores no name of its own,
only an optional own text (`label`); every client shows the display name the API hands out
as `name`: "{server} · {label}", without one "{server} · SSH|RDP|Web", over a tunnel with
" (FRP)". A rename of the server reaches all of them. A connection without a server keeps
its name. A client from before sends `name`; one that only repeats the server or the
display name it was shown stores no own text."""

import pytest

from app.modules.connections.models import Connection
from app.modules.frp.models import FrpServerConfig, FrpTunnel
from app.modules.servers.models import Server


def _headers(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def web01(db_session):
    server = Server(id="srv-web01", name="web01.kunde.example", hostname=None)
    db_session.add(server)
    db_session.commit()
    return server


def _create(client, headers, **body):
    r = client.post("/api/connections", json={"kind": "ssh", **body}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_a_connection_of_a_server_shows_the_server_and_its_kind(
    test_client, db_session, admin_user, web01
):
    created = _create(
        test_client, _headers(test_client), serverId="srv-web01", host="web01.kunde.example"
    )
    assert (created["name"], created["label"]) == ("web01.kunde.example · SSH", "")
    assert db_session.get(Connection, created["id"]).name == ""


def test_an_own_text_stands_after_the_server(test_client, db_session, admin_user, web01):
    created = _create(
        test_client, _headers(test_client), serverId="srv-web01", kind="rdp", label=" root "
    )
    assert (created["name"], created["label"]) == ("web01.kunde.example · root", "root")


@pytest.mark.parametrize(
    "sent", ["web01.kunde.example", "WEB01.kunde.example ", "web01.kunde.example · SSH"]
)
def test_an_older_client_repeating_the_server_stores_no_own_text(
    test_client, db_session, admin_user, web01, sent
):
    created = _create(test_client, _headers(test_client), serverId="srv-web01", name=sent)
    assert (created["name"], created["label"]) == ("web01.kunde.example · SSH", "")


def test_an_older_client_sending_back_the_display_name_keeps_the_own_text(
    test_client, db_session, admin_user, web01
):
    headers = _headers(test_client)
    created = _create(test_client, headers, serverId="srv-web01", label="root")
    r = test_client.put(
        f"/api/connections/{created['id']}",
        json={"name": created["name"], "port": 2222},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert (r.json()["name"], r.json()["label"], r.json()["port"]) == (
        "web01.kunde.example · root",
        "root",
        2222,
    )


def test_a_label_can_be_set_and_taken_away(test_client, db_session, admin_user, web01):
    headers = _headers(test_client)
    created = _create(test_client, headers, serverId="srv-web01")
    r = test_client.put(
        f"/api/connections/{created['id']}", json={"label": "backup"}, headers=headers
    )
    assert r.json()["name"] == "web01.kunde.example · backup"
    r = test_client.put(f"/api/connections/{created['id']}", json={"label": ""}, headers=headers)
    assert (r.json()["name"], r.json()["label"]) == ("web01.kunde.example · SSH", "")


def test_a_rename_of_the_server_reaches_every_connection(
    test_client, db_session, admin_user, web01
):
    headers = _headers(test_client)
    _create(test_client, headers, serverId="srv-web01")
    _create(test_client, headers, serverId="srv-web01", kind="web", label="Admin-UI")
    r = test_client.put(
        "/api/servers/srv-web01", json={"name": "web02.kunde.example"}, headers=headers
    )
    assert r.status_code == 200, r.text
    names = sorted(c["name"] for c in test_client.get("/api/connections", headers=headers).json())
    assert names == ["web02.kunde.example · Admin-UI", "web02.kunde.example · SSH"]


def test_a_connection_a_tunnel_leads_to_says_frp(test_client, db_session, admin_user, web01):
    headers = _headers(test_client)
    db_session.add(
        FrpServerConfig(id="cfg", name="frps", server_addr="frps.example", auth_token="t" * 16)
    )
    db_session.commit()
    r = test_client.post(
        "/api/frp/tunnels",
        json={
            "server_id": "srv-web01",
            "frp_config_id": "cfg",
            "name": "web01-ssh",
            "tunnel_type": "stcp",
            "protocol": "ssh",
            "local_port": 22,
            "auto_create_connection": True,
        },
        headers=headers,
    )
    assert r.status_code in (200, 201), r.text
    tunnel = db_session.get(FrpTunnel, r.json()["id"])
    conn = db_session.get(Connection, tunnel.connection_id)
    assert conn.name == "", "the auto-connection stores no copy of a name"
    shown = test_client.get("/api/connections", headers=headers).json()
    assert [c["name"] for c in shown] == ["web01.kunde.example · SSH (FRP)"]


def test_a_connection_without_a_server_keeps_its_name(test_client, db_session, admin_user):
    headers = _headers(test_client)
    created = _create(test_client, headers, name=" Prod-Gateway ", host="gw.example")
    assert (created["name"], created["label"]) == ("Prod-Gateway", "Prod-Gateway")
    r = test_client.post(
        "/api/connections", json={"kind": "ssh", "host": "gw.example"}, headers=headers
    )
    assert r.status_code == 422, r.text
    r = test_client.put(f"/api/connections/{created['id']}", json={"label": ""}, headers=headers)
    assert r.status_code == 422, r.text


def test_a_connection_taken_off_or_left_by_its_server_keeps_the_name_it_showed(
    test_client, db_session, admin_user, web01
):
    headers = _headers(test_client)
    moved = _create(test_client, headers, serverId="srv-web01")
    kept = _create(test_client, headers, serverId="srv-web01", label="root")
    r = test_client.put(f"/api/connections/{moved['id']}", json={"serverId": None}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "web01.kunde.example · SSH"

    r = test_client.delete("/api/servers/srv-web01", headers=headers)
    assert r.status_code == 204, r.text
    db_session.expire_all()
    left = db_session.get(Connection, kept["id"])
    assert (left.server_id, left.name) == (None, "web01.kunde.example · root")


def test_an_export_imports_back_unchanged(test_client, db_session, admin_user, web01):
    headers = _headers(test_client)
    _create(test_client, headers, serverId="srv-web01")
    _create(test_client, headers, serverId="srv-web01", label="root")
    _create(test_client, headers, name="Prod-Gateway", host="gw.example")
    exported = test_client.get("/api/connections/export", headers=headers).json()

    r = test_client.post(
        "/api/connections/import",
        json={"connections": exported, "mode": "replace"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    shown = test_client.get("/api/connections", headers=headers).json()
    assert sorted((c["name"], c["label"]) for c in shown) == sorted(
        (c["name"], c["label"]) for c in exported
    )


def test_a_hook_round_trip_keeps_the_own_text(db_session, web01):
    # A hook reads to_dict() and writes it back (connections/storage.py): the display name
    # in `name` must not become the own text.
    conn = Connection(id="c-hook", name="root", kind="ssh", server_id="srv-web01")
    db_session.add(conn)
    db_session.commit()
    data = conn.to_dict()
    assert data["name"] == "web01.kunde.example · root"
    conn.update_from_dict(data)
    assert conn.name == "root"
    assert Connection.from_dict({**data, "id": "c-copy"}).name == "root"


def test_a_hook_renaming_by_name_renames(db_session, web01):
    # The hook pattern of docs/developer/hooks.html: load_connections(), set c["name"],
    # save_connections(). The label it read along must not undo the rename.
    free = Connection(id="c-free", name="Prod-Gateway", kind="ssh")
    bound = Connection(id="c-bound", name="root", kind="ssh", server_id="srv-web01")
    db_session.add_all([free, bound])
    db_session.commit()

    data = free.to_dict()
    data["name"] = "Renamed by hook"
    free.update_from_dict(data)
    assert free.name == "Renamed by hook"

    data = bound.to_dict()
    data["name"] = "backup"
    bound.update_from_dict(data)
    assert (bound.name, bound.display_name()) == ("backup", "web01.kunde.example · backup")

    data = bound.to_dict()
    data["name"] = "web01.kunde.example"
    bound.update_from_dict(data)
    assert (bound.name, bound.display_name()) == ("", "web01.kunde.example · SSH")


def test_a_hook_emptying_the_label_of_a_free_connection_keeps_its_name(db_session):
    free = Connection(id="c-free", name="Prod-Gateway", kind="ssh")
    db_session.add(free)
    db_session.commit()
    data = free.to_dict()
    data["label"] = ""
    free.update_from_dict(data)
    assert free.name == "Prod-Gateway"


def test_a_hook_adding_a_copy_with_a_new_name_keeps_that_name(db_session):
    free = Connection(id="c-free", name="Prod-Gateway", kind="ssh")
    db_session.add(free)
    db_session.commit()
    copy = {**free.to_dict(), "id": "c-copy", "name": "Prod-Gateway 2"}
    assert Connection.from_dict(copy).name == "Prod-Gateway 2"
