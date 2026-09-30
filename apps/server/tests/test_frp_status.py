# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""GET /api/frp/status (6.148). The endpoint has real logic that only surfaced live against a real frps
before: 404 without a config, 400 without a dashboard port, and — crucially — an unreachable dashboard
must return a 200 error payload rather than throwing. pytest-httpx stubs the dashboard request."""

import httpx

from app.modules.frp.models import FrpServerConfig


def _login(test_client):
    r = test_client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _config(db, **over):
    fields = dict(id="c1", name="c1", server_addr="frps.example", bind_port=7000, auth_token="tok")
    fields.update(over)
    db.add(FrpServerConfig(**fields))
    db.commit()


def test_status_404_without_config(test_client, admin_user, db_session):
    resp = test_client.get("/api/frp/status", headers=_login(test_client))
    assert resp.status_code == 404


def test_status_400_without_dashboard_port(test_client, admin_user, db_session):
    _config(db_session, dashboard_port=None)
    resp = test_client.get("/api/frp/status", headers=_login(test_client))
    assert resp.status_code == 400


def test_status_unreachable_dashboard_returns_error_payload(
    test_client, admin_user, db_session, httpx_mock, monkeypatch
):
    # Pin a single dashboard candidate so exactly one request is made, then make it refuse to connect.
    import app.modules.frp.status_router as sr

    monkeypatch.setattr(sr, "FRPS_DASHBOARD_URL", "http://frps-test:7500")
    _config(db_session, dashboard_port=7500)
    httpx_mock.add_exception(httpx.ConnectError("connection refused"))

    resp = test_client.get("/api/frp/status", headers=_login(test_client))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["proxies"] == []
    assert "nicht erreichbar" in body["error"]


_DASHBOARD = "http://frps-test:7500"


def test_status_body_equals_the_untyped_dict(
    test_client, admin_user, db_session, httpx_mock, monkeypatch
):
    """R-0043: the route declares FrpStatus. One proxy from the stubbed dashboard, matched to
    a tunnel: the body must be exactly the dict the untyped route built — every proxy key, the
    tunnel as to_dict() hands it out, and no `error` key on success."""
    from fastapi.encoders import jsonable_encoder

    import app.modules.frp.status_router as sr
    from app.modules.frp.models import FrpTunnel
    from app.modules.servers.models import Server

    monkeypatch.setattr(sr, "FRPS_DASHBOARD_URL", _DASHBOARD)
    _config(db_session, dashboard_port=7500)
    db_session.add(Server(id="srv-st", name="st", hostname="st.example.test"))
    db_session.add(
        FrpTunnel(
            id="tun-st",
            server_id="srv-st",
            frp_config_id="c1",
            name="st-ssh",
            tunnel_type="stcp",
            protocol="ssh",
            local_port=22,
            tags='["prod"]',
        )
    )
    db_session.commit()
    proxy = {
        "name": "admin.st-ssh",
        "status": "online",
        "curConns": 2,
        "todayTrafficIn": 1024,
        "todayTrafficOut": 2048,
        "lastStartTime": "09-27 10:00:00",
        "lastCloseTime": "",
    }
    httpx_mock.add_response(url=f"{_DASHBOARD}/api/proxy/stcp", json={"proxies": [proxy]})
    for proxy_type in ("https", "tcp", "udp"):
        httpx_mock.add_response(url=f"{_DASHBOARD}/api/proxy/{proxy_type}", json={"proxies": []})

    resp = test_client.get("/api/frp/status", headers=_login(test_client))

    assert resp.status_code == 200, resp.text
    tunnel = db_session.get(FrpTunnel, "tun-st")
    assert resp.json() == {
        "proxies": [
            {
                "name": "admin.st-ssh",
                "type": "stcp",
                "status": "online",
                "curConns": 2,
                "clientVersion": "",
                "todayTrafficIn": 1024,
                "todayTrafficOut": 2048,
                "lastStartTime": "09-27 10:00:00",
                "lastCloseTime": "",
                "tunnel": jsonable_encoder(tunnel.to_dict()),
            }
        ],
        "total": 1,
    }
    assert resp.json()["proxies"][0]["tunnel"]["secretKey"] is None


def test_status_masks_the_tunnel_secret(
    test_client, admin_user, db_session, httpx_mock, monkeypatch
):
    """The matched tunnel is handed out without its secret: the status page never needs it."""
    import app.modules.frp.status_router as sr
    from app.modules.frp.models import FrpTunnel
    from app.modules.servers.models import Server

    monkeypatch.setattr(sr, "FRPS_DASHBOARD_URL", _DASHBOARD)
    _config(db_session, dashboard_port=7500)
    db_session.add(Server(id="srv-sec", name="sec", hostname="sec.example.test"))
    db_session.add(
        FrpTunnel(
            id="tun-sec",
            server_id="srv-sec",
            frp_config_id="c1",
            name="sec-ssh",
            tunnel_type="stcp",
            protocol="ssh",
            local_port=22,
            secret_key="s" * 32,
        )
    )
    db_session.commit()
    httpx_mock.add_response(
        url=f"{_DASHBOARD}/api/proxy/stcp",
        json={"proxies": [{"name": "admin.sec-ssh", "status": "online"}]},
    )
    for proxy_type in ("https", "tcp", "udp"):
        httpx_mock.add_response(url=f"{_DASHBOARD}/api/proxy/{proxy_type}", json={"proxies": []})

    resp = test_client.get("/api/frp/status", headers=_login(test_client))

    assert resp.status_code == 200, resp.text
    tunnel = resp.json()["proxies"][0]["tunnel"]
    assert tunnel["id"] == "tun-sec"
    assert tunnel["secretKey"] is None


def test_status_unreachable_body_equals_the_untyped_dict(
    test_client, admin_user, db_session, httpx_mock, monkeypatch
):
    """The error answer keeps its three keys, nothing more (an unset `error` is dropped, a set
    one is not)."""
    import app.modules.frp.status_router as sr

    monkeypatch.setattr(sr, "FRPS_DASHBOARD_URL", _DASHBOARD)
    _config(db_session, dashboard_port=7500)
    httpx_mock.add_exception(httpx.ConnectError("connection refused"))

    resp = test_client.get("/api/frp/status", headers=_login(test_client))

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "proxies": [],
        "total": 0,
        "error": "frps-Dashboard: nicht erreichbar (ConnectError)",
    }
