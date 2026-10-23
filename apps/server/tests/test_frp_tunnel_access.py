# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Who may use the FRP tunnel routes (/api/frp/tunnels) and what they get back: an admin lists
every tunnel in the full shape with the secret masked; a non-admin, even one the tunnel's server
is assigned to, gets 403 on the single-tunnel read and on every write, and nothing changes."""

import pytest

from app.modules.frp.models import FrpServerConfig, FrpTunnel
from app.modules.servers.models import Server

# FrpTunnel.to_dict(): the shape an admin reads from the list.
_FULL_FIELDS = {
    "id",
    "serverId",
    "frpConfigId",
    "name",
    "tunnelType",
    "protocol",
    "localIp",
    "localPort",
    "secretKey",
    "customDomains",
    "visitorPort",
    "connectionId",
    "enabled",
    "extraConfig",
    "tags",
    "createdAt",
}


def _login(client, username: str, password: str) -> dict:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_tunnel(db, *, tid: str, server_id: str, name: str, visitor_port: int) -> None:
    db.add(
        FrpTunnel(
            id=tid,
            server_id=server_id,
            frp_config_id="cfg-1",
            name=name,
            tunnel_type="stcp",
            protocol="ssh",
            local_port=22,
            secret_key=f"secret-of-{tid}-do-not-leak",
            visitor_port=visitor_port,
            enabled=True,
        )
    )


@pytest.fixture()
def tunnels(db_session):
    db_session.add(
        FrpServerConfig(
            id="cfg-1",
            name="Default",
            server_addr="frps.example",
            bind_port=7000,
            auth_token="secret-frps-auth",
        )
    )
    db_session.add(Server(id="srv-a", name="serverA", hostname="a.example"))
    db_session.add(Server(id="srv-b", name="serverB", hostname="b.example"))
    _make_tunnel(db_session, tid="t-a", server_id="srv-a", name="a-ssh", visitor_port=6000)
    _make_tunnel(db_session, tid="t-b", server_id="srv-b", name="b-ssh", visitor_port=6001)
    db_session.commit()


def _stored_tunnels(db) -> dict[str, dict]:
    # Unmasked, so a write that only touched the secret would show as well.
    db.expire_all()
    return {t.id: t.to_dict() for t in db.query(FrpTunnel).all()}


def test_admin_lists_every_tunnel_in_the_full_shape_without_secret(
    test_client, db_session, admin_user, tunnels
):
    h = _login(test_client, "admin", "adminpass")
    r = test_client.get("/api/frp/tunnels", headers=h)
    assert r.status_code == 200, r.text
    listed = r.json()
    assert {t["id"] for t in listed} == {"t-a", "t-b"}
    for t in listed:
        assert set(t) == _FULL_FIELDS, t["id"]
        assert t["secretKey"] is None, t["id"]

    only_a = test_client.get("/api/frp/tunnels", params={"server_id": "srv-a"}, headers=h)
    assert only_a.status_code == 200, only_a.text
    assert [t["id"] for t in only_a.json()] == ["t-a"]


_STCP_BODY_FOR_SRV_A = {
    "server_id": "srv-a",
    "frp_config_id": "cfg-1",
    "name": "c-ssh",
    "tunnel_type": "stcp",
    "protocol": "ssh",
    "local_port": 22,
    "visitor_port": 6002,
}


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        pytest.param("GET", "/api/frp/tunnels/t-a", None, id="get-one"),
        pytest.param("POST", "/api/frp/tunnels", _STCP_BODY_FOR_SRV_A, id="create"),
        pytest.param("PUT", "/api/frp/tunnels/t-a", {"name": "renamed"}, id="update"),
        pytest.param("DELETE", "/api/frp/tunnels/t-a", None, id="delete"),
    ],
)
def test_non_admin_with_the_server_assigned_is_refused_and_nothing_changes(
    test_client, db_session, normal_user, tunnels, method, path, body
):
    normal_user.servers.append(db_session.get(Server, "srv-a"))
    db_session.commit()
    before = _stored_tunnels(db_session)
    assert set(before) == {"t-a", "t-b"}

    h = _login(test_client, "viewer", "viewerpass")
    r = test_client.request(method, path, json=body, headers=h)
    assert r.status_code == 403, r.text
    assert _stored_tunnels(db_session) == before
