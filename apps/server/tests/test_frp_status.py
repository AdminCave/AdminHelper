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
