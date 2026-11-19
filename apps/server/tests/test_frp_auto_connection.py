# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The connection a tunnel leads to (R-1540): a web tunnel's auto-connection carries scheme and
path in its URL instead of a user, and a change of protocol or tunnel type takes the linked
connection along, a hand-linked one too."""

import pytest

from app.modules.connections.models import Connection
from app.modules.frp.models import FrpServerConfig, FrpTunnel
from app.modules.servers.models import Server


def _login(client, username: str, password: str) -> dict:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def h(test_client, db_session, admin_user):
    db_session.add(
        FrpServerConfig(
            id="cfg-1",
            name="Default",
            server_addr="frps.example.net",
            bind_port=7000,
            auth_token="secret-frps-auth",
        )
    )
    db_session.add(Server(id="srv-a", name="serverA", hostname="a.example.test"))
    db_session.commit()
    return _login(test_client, "admin", "adminpass")


def _body(**over) -> dict:
    body = {
        "server_id": "srv-a",
        "frp_config_id": "cfg-1",
        "tunnel_type": "stcp",
        "protocol": "web",
        "local_port": 8006,
        "visitor_port": 6100,
        "auto_create_connection": True,
    }
    body.update(over)
    return body


def _create(client, h, **over) -> dict:
    r = client.post("/api/frp/tunnels", json=_body(**over), headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _conn(db, tunnel: dict) -> Connection:
    db.expire_all()
    conn = db.get(Connection, tunnel["connectionId"])
    assert conn is not None
    return conn


def test_web_auto_connection_carries_scheme_and_path_not_a_user(test_client, db_session, h):
    t = _create(
        test_client,
        h,
        auto_connection_scheme="https",
        auto_connection_path="/ui/?lang=de",
        auto_connection_username="root",
    )
    conn = _conn(db_session, t)
    assert conn.kind == "web"
    assert conn.url == "https://127.0.0.1:6100/ui/?lang=de"
    assert (conn.host, conn.port) == ("127.0.0.1", 6100)
    assert conn.username == ""


def test_a_client_from_before_gets_http_without_a_path(test_client, db_session, h):
    conn = _conn(db_session, _create(test_client, h))
    assert conn.url == "http://127.0.0.1:6100"


def test_ssh_auto_connection_keeps_its_user_and_has_no_url(test_client, db_session, h):
    t = _create(
        test_client,
        h,
        protocol="ssh",
        local_port=22,
        auto_connection_username="root",
        auto_connection_scheme="https",
    )
    conn = _conn(db_session, t)
    assert (conn.kind, conn.username, conn.url) == ("ssh", "root", "")


@pytest.mark.parametrize("path", ["ui", "/a b", "/a#b", "/a\nb", "/" + "a" * 255])
def test_a_bad_path_is_422(test_client, h, path):
    r = test_client.post("/api/frp/tunnels", json=_body(auto_connection_path=path), headers=h)
    assert r.status_code == 422, r.text


def test_an_unknown_scheme_is_422(test_client, h):
    r = test_client.post("/api/frp/tunnels", json=_body(auto_connection_scheme="ftp"), headers=h)
    assert r.status_code == 422, r.text


def _put(client, h, tunnel_id: str, **body) -> dict:
    r = client.put(f"/api/frp/tunnels/{tunnel_id}", json=body, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_protocol_change_takes_the_auto_connection_along(test_client, db_session, h):
    t = _create(test_client, h, protocol="ssh", local_port=22, auto_connection_username="root")

    _put(test_client, h, t["id"], protocol="web", auto_connection_scheme="https")
    conn = _conn(db_session, t)
    assert (conn.kind, conn.url) == ("web", "https://127.0.0.1:6100")

    _put(test_client, h, t["id"], protocol="rdp")
    conn = _conn(db_session, t)
    assert (conn.kind, conn.url, conn.host, conn.port) == ("rdp", "", "127.0.0.1", 6100)


def test_a_web_connection_keeps_scheme_and_path_through_a_type_change(test_client, db_session, h):
    t = _create(test_client, h, auto_connection_scheme="https", auto_connection_path="/pve")

    _put(test_client, h, t["id"], tunnel_type="https", custom_domains="pve.example.test")
    conn = _conn(db_session, t)
    assert conn.url == "https://pve.example.test/pve"

    _put(test_client, h, t["id"], tunnel_type="stcp")
    conn = _conn(db_session, t)
    tunnel = db_session.get(FrpTunnel, t["id"])
    assert conn.url == f"https://127.0.0.1:{tunnel.visitor_port}/pve"


def test_a_hand_linked_connection_follows_too(test_client, db_session, h):
    db_session.add(
        Connection(id="c-hand", name="pve", kind="ssh", host="192.0.2.10", port=22, username="u")
    )
    db_session.commit()
    t = _create(
        test_client,
        h,
        protocol="ssh",
        local_port=22,
        auto_create_connection=False,
        connection_id="c-hand",
    )

    _put(test_client, h, t["id"], protocol="web")
    conn = _conn(db_session, t)
    assert (conn.kind, conn.host, conn.port) == ("web", "127.0.0.1", 6100)
    assert conn.url == "http://127.0.0.1:6100"
    assert conn.username == "u"


def test_an_unchanged_protocol_leaves_the_connection_alone(test_client, db_session, h):
    t = _create(test_client, h, auto_connection_scheme="https")
    conn = _conn(db_session, t)
    conn.url = "https://127.0.0.1:6100/own"
    db_session.commit()

    _put(test_client, h, t["id"], protocol="web", local_port=8007, auto_connection_scheme="http")
    assert _conn(db_session, t).url == "https://127.0.0.1:6100/own"


@pytest.mark.parametrize(
    "old_url",
    ["x:@evil.example/a", "evil.example/a", "https://h.example/a b", "ftp://h.example/a"],
)
def test_an_old_url_never_moves_the_host_of_the_new_one(test_client, db_session, h, old_url):
    t = _create(test_client, h)
    conn = _conn(db_session, t)
    conn.url = old_url
    db_session.commit()

    _put(test_client, h, t["id"], tunnel_type="https", custom_domains="tun.example.test")
    assert _conn(db_session, t).url == "https://tun.example.test"


def test_a_c1_control_character_in_the_path_is_422(test_client, h):
    r = test_client.post(
        "/api/frp/tunnels", json=_body(auto_connection_path="/a\u0080b"), headers=h
    )
    assert r.status_code == 422, r.text
