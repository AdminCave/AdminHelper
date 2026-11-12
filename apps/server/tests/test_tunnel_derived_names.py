# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""R-1210 (Kevin 2026-11-09, 3a and 4a): a tunnel stores no name of its own, only an optional
own text (`label`); the API hands out the display name "{server} · {label|SSH|RDP|Web} (FRP)"
as `name`, the same as its auto-connection. frpc knows the tunnel by its ID, so own texts may
repeat. A client from before sends `name`; one that only repeats the server, the display name
or the old pattern "{server}-{protocol}" stores no own text."""

import pytest

from app.modules.frp.models import FrpServerConfig, FrpTunnel
from app.modules.servers.models import Server


def _headers(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def web01(db_session):
    db_session.add(Server(id="srv-web01", name="web01.kunde.example", hostname=None))
    db_session.add(
        FrpServerConfig(id="cfg", name="frps", server_addr="frps.example", auth_token="t" * 16)
    )
    db_session.commit()


def _create(client, headers, **body):
    payload = {
        "server_id": "srv-web01",
        "frp_config_id": "cfg",
        "tunnel_type": "stcp",
        "protocol": "ssh",
        "local_port": 22,
        **body,
    }
    r = client.post("/api/frp/tunnels", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_a_tunnel_without_a_name_shows_the_server_and_its_protocol(
    test_client, db_session, admin_user, web01
):
    created = _create(test_client, _headers(test_client), auto_create_connection=True)
    assert (created["name"], created["label"]) == ("web01.kunde.example · SSH (FRP)", "")
    connections = test_client.get("/api/connections", headers=_headers(test_client)).json()
    assert [c["name"] for c in connections] == [created["name"]]


@pytest.mark.parametrize(
    "sent",
    [
        "web01.kunde.example-ssh",
        "WEB01.kunde.example-stcp",
        "web01.kunde.example",
        "web01.kunde.example · SSH (FRP)",
    ],
)
def test_an_older_client_repeating_the_server_stores_no_own_text(
    test_client, db_session, admin_user, web01, sent
):
    created = _create(test_client, _headers(test_client), name=sent)
    assert (created["name"], created["label"]) == ("web01.kunde.example · SSH (FRP)", "")


def test_own_texts_may_repeat_and_rename_with_the_server(
    test_client, db_session, admin_user, web01
):
    headers = _headers(test_client)
    first = _create(test_client, headers, label="backup")
    second = _create(test_client, headers, label="backup", protocol="rdp", local_port=3389)
    assert first["name"] == second["name"] == "web01.kunde.example · backup (FRP)"

    r = test_client.put(
        "/api/servers/srv-web01", json={"name": "web02.kunde.example"}, headers=headers
    )
    assert r.status_code == 200, r.text
    listed = test_client.get("/api/frp/tunnels", headers=headers).json()
    assert [t["name"] for t in listed] == ["web02.kunde.example · backup (FRP)"] * 2


def test_an_older_client_sending_back_the_display_name_keeps_the_own_text(
    test_client, db_session, admin_user, web01
):
    headers = _headers(test_client)
    created = _create(test_client, headers, label="backup")
    r = test_client.put(
        f"/api/frp/tunnels/{created['id']}",
        json={"name": created["name"], "local_port": 2222},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert (r.json()["label"], r.json()["localPort"]) == ("backup", 2222)
    r = test_client.put(f"/api/frp/tunnels/{created['id']}", json={"label": ""}, headers=headers)
    assert (r.json()["name"], r.json()["label"]) == ("web01.kunde.example · SSH (FRP)", "")


def test_a_null_label_changes_nothing(test_client, db_session, admin_user, web01):
    headers = _headers(test_client)
    created = _create(test_client, headers, label="backup")
    r = test_client.put(f"/api/frp/tunnels/{created['id']}", json={"label": None}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["label"] == "backup"
    db_session.expire_all()
    assert db_session.get(FrpTunnel, created["id"]).name == "backup"


def test_the_status_page_shows_the_display_name(test_client, db_session, admin_user, web01):
    tunnel = FrpTunnel(
        id="t-1",
        server_id="srv-web01",
        frp_config_id="cfg",
        name="",
        tunnel_type="stcp",
        protocol="rdp",
        local_port=3389,
    )
    db_session.add(tunnel)
    db_session.commit()
    assert tunnel.to_dict()["name"] == "web01.kunde.example · RDP (FRP)"
