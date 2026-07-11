# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Authorization for the servers module — the admin-only inventory every other
object references via server_id. The structural gate (test_route_auth_gate.py)
proves a guard is *wired*; this proves it actually *enforces*: a non-admin user
is rejected, an unauthenticated request is rejected, and an admin gets through.
The authz dependency runs before the handler, so a non-admin is 403'd even for a
non-existent id (no IDOR window)."""

SERVER = {"name": "authz-srv", "hostname": "authz.example"}


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_admin_can_create_and_list_servers(test_client, db_session, admin_user):
    headers = _auth(_login(test_client, "admin", "adminpass"))
    created = test_client.post("/api/servers", json=SERVER, headers=headers)
    assert created.status_code in (200, 201), created.text
    listed = test_client.get("/api/servers", headers=headers)
    assert listed.status_code == 200, listed.text
    assert any(s["name"] == "authz-srv" for s in listed.json())


def test_nonadmin_cannot_list_servers(test_client, db_session, normal_user):
    headers = _auth(_login(test_client, "viewer", "viewerpass"))
    r = test_client.get("/api/servers", headers=headers)
    assert r.status_code == 403, r.text


def test_nonadmin_cannot_create_server(test_client, db_session, normal_user):
    headers = _auth(_login(test_client, "viewer", "viewerpass"))
    r = test_client.post("/api/servers", json=SERVER, headers=headers)
    assert r.status_code == 403, r.text


def test_nonadmin_cannot_delete_server(test_client, db_session, normal_user):
    # 403 from the authz dependency, before the (missing) row is ever looked up.
    headers = _auth(_login(test_client, "viewer", "viewerpass"))
    r = test_client.delete("/api/servers/does-not-exist", headers=headers)
    assert r.status_code == 403, r.text


def test_unauthenticated_cannot_list_servers(test_client, db_session):
    r = test_client.get("/api/servers")
    assert r.status_code == 401, r.text


def test_server_deleted_event_fires_after_commit(test_client, db_session, admin_user, monkeypatch):
    """2.48: server.deleted must fire only AFTER the delete commits — a rolled-back
    delete must not tell admins "server removed" for a still-existing server. The
    spy asserts the row is already gone at fire time (i.e. the commit ran first)."""
    from app.modules.servers import router as servers_router
    from app.modules.servers.models import Server

    headers = _auth(_login(test_client, "admin", "adminpass"))
    server_id = test_client.post("/api/servers", json=SERVER, headers=headers).json()["id"]

    seen = {}

    def spy_fire(event, data):
        seen["event"] = event
        seen["row_gone"] = db_session.query(Server).filter(Server.id == data["id"]).first() is None

    monkeypatch.setattr(servers_router, "fire_event", spy_fire)

    r = test_client.delete(f"/api/servers/{server_id}", headers=headers)

    assert r.status_code == 204, r.text
    assert seen["event"] == "server.deleted"
    assert seen["row_gone"] is True  # fired after the commit, not before it


def test_server_delete_logs_monitoring_cleanup_http_error(
    test_client, db_session, admin_user, monkeypatch, caplog
):
    # 4.140: a monitoring cleanup returning an error status (403 wrong internal key, 5xx) must be
    # logged, not silently treated as done — else the deleted server's checks/alerts/assignments
    # linger as orphans in monitoring with no log trace.
    from types import SimpleNamespace

    from app.modules.servers import router as servers_router

    headers = _auth(_login(test_client, "admin", "adminpass"))
    server_id = test_client.post("/api/servers", json=SERVER, headers=headers).json()["id"]

    monkeypatch.setattr(
        servers_router.httpx, "delete", lambda *a, **k: SimpleNamespace(status_code=403)
    )
    with caplog.at_level("WARNING"):
        r = test_client.delete(f"/api/servers/{server_id}", headers=headers)
    assert r.status_code == 204, r.text
    assert "HTTP 403" in caplog.text
