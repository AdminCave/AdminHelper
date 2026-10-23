# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Who may use the FRP tunnel routes (/api/frp/tunnels) and what they get back: an admin lists
every tunnel in the full shape with the secret masked; a non-admin lists only the enabled tunnels
of his assigned servers, each with just the fields the desktop reads (TunnelMapping), and gets 403
on the single-tunnel read and on every write, even when the tunnel's server is assigned to him."""

import re
from pathlib import Path

import pytest

from app.modules.frp import tunnel_router
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

# What a non-admin reads per tunnel, written out here rather than imported, so a field dropped
# from the server's list shows up as a missing key.
_MAPPING_KEYS = {
    "id",
    "serverId",
    "tunnelType",
    "protocol",
    "localPort",
    "visitorPort",
    "customDomains",
    "connectionId",
    "enabled",
    "name",
}

_TUNNEL_RS = (
    Path(__file__).resolve().parents[3] / "apps" / "desktop" / "src-tauri" / "src" / "tunnel.rs"
)


def _login(client, username: str, password: str) -> dict:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_tunnel(
    db, *, tid: str, server_id: str, name: str, visitor_port: int, enabled: bool = True
) -> None:
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
            enabled=enabled,
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


@pytest.fixture()
def more_tunnels(db_session, tunnels):
    # On srv-a besides t-a: a disabled STCP tunnel and an HTTPS one.
    _make_tunnel(
        db_session, tid="t-off", server_id="srv-a", name="a-off", visitor_port=6003, enabled=False
    )
    db_session.add(
        FrpTunnel(
            id="t-web",
            server_id="srv-a",
            frp_config_id="cfg-1",
            name="a-web",
            tunnel_type="https",
            protocol="web",
            local_port=443,
            custom_domains="web.example",
            enabled=True,
        )
    )
    db_session.commit()


def _stored_tunnels(db) -> dict[str, dict]:
    # Unmasked, so a write that only touched the secret would show as well.
    db.expire_all()
    return {t.id: t.to_dict() for t in db.query(FrpTunnel).all()}


def test_admin_lists_every_tunnel_in_the_full_shape_without_secret(
    test_client, db_session, admin_user, more_tunnels
):
    # Disabled ones included: the desktop's tunnel tab shows them to admins.
    h = _login(test_client, "admin", "adminpass")
    r = test_client.get("/api/frp/tunnels", headers=h)
    assert r.status_code == 200, r.text
    listed = r.json()
    assert {t["id"] for t in listed} == {"t-a", "t-b", "t-off", "t-web"}
    for t in listed:
        assert set(t) == _FULL_FIELDS, t["id"]
        assert t["secretKey"] is None, t["id"]

    only_a = test_client.get("/api/frp/tunnels", params={"server_id": "srv-a"}, headers=h)
    assert only_a.status_code == 200, only_a.text
    assert sorted(t["id"] for t in only_a.json()) == ["t-a", "t-off", "t-web"]


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


def _list_as_viewer(client, params: dict | None = None) -> list[dict]:
    h = _login(client, "viewer", "viewerpass")
    r = client.get("/api/frp/tunnels", params=params, headers=h)
    assert r.status_code == 200, r.text
    assert "do-not-leak" not in r.text
    return r.json()


def test_non_admin_lists_the_enabled_tunnels_of_his_servers_in_the_mapping_shape(
    test_client, db_session, normal_user, more_tunnels
):
    normal_user.servers.append(db_session.get(Server, "srv-a"))
    db_session.commit()
    stored = {t.id: t.to_dict(mask_secrets=True) for t in db_session.query(FrpTunnel).all()}

    listed = _list_as_viewer(test_client)
    assert {t["id"] for t in listed} == {"t-a", "t-web"}
    for t in listed:
        assert set(t) == _MAPPING_KEYS, t["id"]
        assert "secretKey" not in t, t["id"]
        assert t == {k: stored[t["id"]][k] for k in _MAPPING_KEYS}, t["id"]
    web = next(t for t in listed if t["id"] == "t-web")
    assert web["customDomains"] == "web.example"


def test_non_admin_without_assigned_server_lists_nothing(
    test_client, db_session, normal_user, more_tunnels
):
    assert _list_as_viewer(test_client) == []


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        pytest.param({"server_id": "srv-b"}, set(), id="foreign-server"),
        pytest.param({"frp_config_id": "cfg-unknown"}, set(), id="unknown-config"),
        pytest.param({"frp_config_id": "cfg-1"}, {"t-a", "t-web"}, id="own-config"),
        pytest.param({"server_id": "srv-a"}, {"t-a", "t-web"}, id="own-server"),
    ],
)
def test_non_admin_query_parameters_only_narrow(
    test_client, db_session, normal_user, more_tunnels, params, expected
):
    normal_user.servers.append(db_session.get(Server, "srv-a"))
    db_session.commit()
    assert {t["id"] for t in _list_as_viewer(test_client, params)} == expected


def _camel(snake: str) -> str:
    head, *rest = snake.split("_")
    return head + "".join(part.capitalize() for part in rest)


def test_mapping_fields_match_the_desktop_tunnel_mapping():
    # The desktop deserialises every listed tunnel into TunnelMapping; a field the server leaves
    # out that the struct requires fails it for every non-admin.
    src = _TUNNEL_RS.read_text(encoding="utf-8")
    m = re.search(
        r'#\[serde\(rename_all = "camelCase"\)\]\s*pub struct TunnelMapping \{(.*?)\n\}', src, re.S
    )
    assert m, f"camelCase struct TunnelMapping not found in {_TUNNEL_RS}"
    body = m.group(1)
    # A per-field serde attribute would change the wire name this test derives.
    assert "#[serde" not in body
    rust_fields = {_camel(f) for f in re.findall(r"^\s*pub (\w+):", body, re.M)}
    assert "localPort" in rust_fields
    assert rust_fields == set(tunnel_router._MAPPING_FIELDS)
