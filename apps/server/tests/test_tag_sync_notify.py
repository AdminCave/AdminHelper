# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tag-sync notify (T11): server create/update(tags|name|hostname)/delete nudge
the monitoring service (POST /templates/tag-sync) best-effort — a down
monitoring service must never fail the server operation."""


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _spy_notify(monkeypatch):
    """Patch httpx.post as seen by the servers router; records target URLs."""
    import app.modules.servers.router as servers_router

    calls: list[str] = []

    class _Resp:
        status_code = 200

    monkeypatch.setattr(
        servers_router.httpx, "post", lambda url, **kw: calls.append(url) or _Resp()
    )
    return calls


def _create(client, headers, name="tsn-srv"):
    r = client.post(
        "/api/servers",
        json={"name": name, "hostname": "tsn.example", "tags": ["web"]},
        headers=headers,
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


def test_create_notifies(test_client, db_session, admin_user, monkeypatch):
    calls = _spy_notify(monkeypatch)
    headers = _auth(_login(test_client, "admin", "adminpass"))
    _create(test_client, headers)
    assert len(calls) == 1
    assert calls[0].endswith("/templates/tag-sync")


def test_update_of_tags_notifies_but_notes_do_not(test_client, db_session, admin_user, monkeypatch):
    calls = _spy_notify(monkeypatch)
    headers = _auth(_login(test_client, "admin", "adminpass"))
    sid = _create(test_client, headers)
    calls.clear()

    assert (
        test_client.put(f"/api/servers/{sid}", json={"tags": ["db"]}, headers=headers).status_code
        == 200
    )
    assert len(calls) == 1

    calls.clear()
    assert (
        test_client.put(
            f"/api/servers/{sid}", json={"notes": "irrelevant"}, headers=headers
        ).status_code
        == 200
    )
    assert calls == []


def test_delete_notifies(test_client, db_session, admin_user, monkeypatch):
    calls = _spy_notify(monkeypatch)
    headers = _auth(_login(test_client, "admin", "adminpass"))
    sid = _create(test_client, headers)
    calls.clear()

    assert test_client.delete(f"/api/servers/{sid}", headers=headers).status_code == 204
    assert len(calls) == 1


def test_raising_notify_never_fails_the_operation(test_client, db_session, admin_user, monkeypatch):
    import app.modules.servers.router as servers_router

    def boom(url, **kw):
        raise ConnectionError("monitoring down")

    monkeypatch.setattr(servers_router.httpx, "post", boom)
    headers = _auth(_login(test_client, "admin", "adminpass"))
    r = test_client.post(
        "/api/servers",
        json={"name": "tsn-broken", "hostname": "x.example", "tags": ["web"]},
        headers=headers,
    )
    assert r.status_code in (200, 201), r.text
