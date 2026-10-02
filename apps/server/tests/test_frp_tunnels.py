# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""FRP tunnel CRUD (/api/frp/tunnels): the visitor-port conflict (409), automatic port assignment +
STCP secret autogeneration, and the duplicate-name conflict — none of which had a test, so a
regression removing the conflict check would only surface as frps misbehaviour in production (6.74)."""

from app.modules.frp.models import FrpServerConfig, FrpTunnel
from app.modules.servers.models import Server


def _login(client, username: str, password: str) -> dict:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _seed(db) -> None:
    db.add(
        FrpServerConfig(
            id="cfg-1",
            name="Default",
            server_addr="frps.example.net",
            bind_port=7000,
            auth_token="secret-frps-auth",
        )
    )
    db.add(Server(id="srv-a", name="serverA", hostname="a.example.test"))
    db.add(
        FrpTunnel(
            id="t-a",
            server_id="srv-a",
            frp_config_id="cfg-1",
            name="a-ssh",
            tunnel_type="stcp",
            protocol="ssh",
            local_port=22,
            secret_key="existing-secret",
            visitor_port=6000,
            enabled=True,
        )
    )
    db.commit()


def _body(**over) -> dict:
    body = {
        "server_id": "srv-a",
        "frp_config_id": "cfg-1",
        "name": "neu",
        "tunnel_type": "stcp",
        "protocol": "ssh",
        "local_port": 22,
    }
    body.update(over)
    return body


def test_visitor_port_conflict_is_409(test_client, db_session, admin_user):
    _seed(db_session)
    h = _login(test_client, "admin", "adminpass")
    r = test_client.post("/api/frp/tunnels", json=_body(visitor_port=6000), headers=h)
    assert r.status_code == 409, r.text  # 6000 is already bound by t-a


def test_duplicate_name_is_409(test_client, db_session, admin_user):
    _seed(db_session)
    h = _login(test_client, "admin", "adminpass")
    r = test_client.post("/api/frp/tunnels", json=_body(name="a-ssh", visitor_port=6002), headers=h)
    assert r.status_code == 409, r.text  # name a-ssh already exists


def _stored_secret(db, tunnel_id: str) -> str | None:
    db.expire_all()
    return db.query(FrpTunnel).filter(FrpTunnel.id == tunnel_id).one().secret_key


def test_put_null_secret_keeps_the_stored_one(test_client, db_session, admin_user):
    _seed(db_session)
    h = _login(test_client, "admin", "adminpass")
    r = test_client.put("/api/frp/tunnels/t-a", json={"secret_key": None}, headers=h)
    assert r.status_code == 200, r.text
    assert _stored_secret(db_session, "t-a") == "existing-secret"


def test_put_empty_secret_keeps_the_stored_one(test_client, db_session, admin_user):
    _seed(db_session)
    h = _login(test_client, "admin", "adminpass")
    r = test_client.put("/api/frp/tunnels/t-a", json={"secret_key": ""}, headers=h)
    assert r.status_code == 200, r.text
    assert _stored_secret(db_session, "t-a") == "existing-secret"


def test_put_switch_to_stcp_without_secret_generates_one(test_client, db_session, admin_user):
    _seed(db_session)
    db_session.add(
        FrpTunnel(
            id="t-web",
            server_id="srv-a",
            frp_config_id="cfg-1",
            name="a-web",
            tunnel_type="https",
            protocol="web",
            local_port=443,
            custom_domains="a.example.test",
            enabled=True,
        )
    )
    db_session.commit()
    h = _login(test_client, "admin", "adminpass")
    r = test_client.put("/api/frp/tunnels/t-web", json={"tunnel_type": "stcp"}, headers=h)
    assert r.status_code == 200, r.text
    secret = _stored_secret(db_session, "t-web")
    assert secret is not None and len(secret) >= 32


def test_put_new_secret_replaces_the_stored_one(test_client, db_session, admin_user):
    _seed(db_session)
    h = _login(test_client, "admin", "adminpass")
    new = "a-new-rotated-secret-0123456789"
    r = test_client.put("/api/frp/tunnels/t-a", json={"secret_key": new}, headers=h)
    assert r.status_code == 200, r.text
    assert _stored_secret(db_session, "t-a") == new


def test_put_without_secret_keeps_the_stored_one(test_client, db_session, admin_user):
    _seed(db_session)
    h = _login(test_client, "admin", "adminpass")
    r = test_client.put("/api/frp/tunnels/t-a", json={"local_port": 2222}, headers=h)
    assert r.status_code == 200, r.text
    assert _stored_secret(db_session, "t-a") == "existing-secret"


def test_get_list_get_and_put_answer_without_the_secret(test_client, db_session, admin_user):
    _seed(db_session)
    h = _login(test_client, "admin", "adminpass")
    listed = test_client.get("/api/frp/tunnels", headers=h)
    assert listed.status_code == 200, listed.text
    assert [t["secretKey"] for t in listed.json()] == [None]
    one = test_client.get("/api/frp/tunnels/t-a", headers=h)
    assert one.status_code == 200, one.text
    assert one.json()["secretKey"] is None
    put = test_client.put("/api/frp/tunnels/t-a", json={"local_port": 2222}, headers=h)
    assert put.status_code == 200, put.text
    assert put.json()["secretKey"] is None
    assert _stored_secret(db_session, "t-a") == "existing-secret"


def test_provision_config_and_visitor_bundle_still_carry_the_secret(
    test_client, db_session, admin_user
):
    # The secret is needed on both tunnel ends: frpc gets it through the provision config,
    # the desktop visitor through the visitor bundle. Only the JSON answers mask it.
    _seed(db_session)
    h = _login(test_client, "admin", "adminpass")
    frpc = test_client.get("/api/frp/provision/srv-a/config", headers=h)
    assert frpc.status_code == 200, frpc.text
    assert 'secretKey = "existing-secret"' in frpc.text
    bundle = test_client.get("/api/frp/generate/visitor-bundle", headers=h)
    assert bundle.status_code == 200, bundle.text
    assert 'secretKey = "existing-secret"' in bundle.json()["toml"]


def test_stcp_create_generates_secret_and_port_and_masks_the_secret(
    test_client, db_session, admin_user
):
    _seed(db_session)
    h = _login(test_client, "admin", "adminpass")
    # No visitor_port, no secret_key -> both auto-assigned; the answer carries no secret.
    r = test_client.post("/api/frp/tunnels", json=_body(name="auto"), headers=h)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["secretKey"] is None
    db_session.expire_all()
    stored = db_session.query(FrpTunnel).filter(FrpTunnel.name == "auto").one()
    assert stored.secret_key and len(stored.secret_key) >= 32
    assert stored.visitor_port and stored.visitor_port != 6000
    assert data["visitorPort"] == stored.visitor_port


# secret_key and visitor_port belong to stcp tunnels only: an https tunnel keeps neither, a switch
# back to stcp gets a fresh secret, and a stored port that another stcp tunnel took meanwhile is
# replaced by a free one. A port the client sends explicitly is still checked (409).

_HTTPS = {"tunnel_type": "https", "protocol": "web", "custom_domains": "a.example.test"}


def _stored(db, tunnel_id: str) -> FrpTunnel:
    db.expire_all()
    return db.query(FrpTunnel).filter(FrpTunnel.id == tunnel_id).one()


def test_put_to_https_clears_secret_and_visitor_port(test_client, db_session, admin_user):
    _seed(db_session)
    h = _login(test_client, "admin", "adminpass")
    r = test_client.put("/api/frp/tunnels/t-a", json=_HTTPS, headers=h)
    assert r.status_code == 200, r.text
    row = _stored(db_session, "t-a")
    assert (row.secret_key, row.visitor_port) == (None, None)


def test_https_post_stores_no_stcp_fields(test_client, db_session, admin_user):
    _seed(db_session)
    h = _login(test_client, "admin", "adminpass")
    body = _body(name="web", local_port=443, secret_key="s" * 32, visitor_port=6010, **_HTTPS)
    r = test_client.post("/api/frp/tunnels", json=body, headers=h)
    assert r.status_code == 201, r.text
    row = _stored(db_session, r.json()["id"])
    assert (row.secret_key, row.visitor_port) == (None, None)


def test_switch_back_to_stcp_gets_a_new_secret_and_a_free_port(test_client, db_session, admin_user):
    _seed(db_session)
    h = _login(test_client, "admin", "adminpass")
    assert test_client.put("/api/frp/tunnels/t-a", json=_HTTPS, headers=h).status_code == 200
    taken = test_client.post("/api/frp/tunnels", json=_body(name="other"), headers=h)
    assert taken.status_code == 201, taken.text
    assert _stored(db_session, taken.json()["id"]).visitor_port == 6000  # the freed port
    r = test_client.put("/api/frp/tunnels/t-a", json={"tunnel_type": "stcp"}, headers=h)
    assert r.status_code == 200, r.text
    row = _stored(db_session, "t-a")
    assert row.visitor_port not in (None, 6000)
    assert row.secret_key and row.secret_key != "existing-secret"


def test_old_https_row_with_stcp_fields_heals_on_switch(test_client, db_session, admin_user):
    _seed(db_session)  # t-a: stcp on 6000
    db_session.add(
        FrpTunnel(
            id="t-old",
            server_id="srv-a",
            frp_config_id="cfg-1",
            name="old-web",
            tunnel_type="https",
            protocol="web",
            local_port=443,
            secret_key="an-old-secret-from-before-0123",
            visitor_port=6000,
            enabled=True,
        )
    )
    db_session.commit()
    h = _login(test_client, "admin", "adminpass")
    r = test_client.put("/api/frp/tunnels/t-old", json={"tunnel_type": "stcp"}, headers=h)
    assert r.status_code == 200, r.text
    row = _stored(db_session, "t-old")
    assert row.visitor_port not in (None, 6000)
    assert row.secret_key and row.secret_key != "an-old-secret-from-before-0123"


def test_an_explicitly_sent_taken_port_stays_409(test_client, db_session, admin_user):
    _seed(db_session)
    db_session.add(
        FrpTunnel(
            id="t-old",
            server_id="srv-a",
            frp_config_id="cfg-1",
            name="old-web",
            tunnel_type="https",
            protocol="web",
            local_port=443,
            enabled=True,
        )
    )
    db_session.commit()
    h = _login(test_client, "admin", "adminpass")
    r = test_client.put(
        "/api/frp/tunnels/t-old", json={"tunnel_type": "stcp", "visitor_port": 6000}, headers=h
    )
    assert r.status_code == 409, r.text
