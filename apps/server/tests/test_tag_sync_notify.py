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


def _drain_notify():
    """The notify runs fire-and-forget on the single-worker pool (T46) — a
    no-op barrier guarantees every queued notify has completed."""
    import app.modules.servers.router as servers_router

    servers_router._NOTIFY_POOL.submit(lambda: None).result()


def _create(client, headers, name="tsn-srv"):
    r = client.post(
        "/api/servers",
        json={"name": name, "hostname": "tsn.example", "tags": ["web"]},
        headers=headers,
    )
    assert r.status_code in (200, 201), r.text
    _drain_notify()
    return r.json()["id"]


def test_create_notifies(test_client, db_session, admin_user, monkeypatch):
    calls = _spy_notify(monkeypatch)
    headers = _auth(_login(test_client, "admin", "adminpass"))
    _create(test_client, headers)
    _drain_notify()
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
    _drain_notify()
    assert len(calls) == 1

    calls.clear()
    assert (
        test_client.put(
            f"/api/servers/{sid}", json={"notes": "irrelevant"}, headers=headers
        ).status_code
        == 200
    )
    _drain_notify()
    assert calls == []


def test_delete_notifies(test_client, db_session, admin_user, monkeypatch):
    calls = _spy_notify(monkeypatch)
    headers = _auth(_login(test_client, "admin", "adminpass"))
    sid = _create(test_client, headers)
    calls.clear()

    assert test_client.delete(f"/api/servers/{sid}", headers=headers).status_code == 204
    _drain_notify()
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
    # Barrier before the monkeypatch teardown: the queued notify must run
    # against the raising spy, not the real httpx afterwards.
    _drain_notify()


def test_notify_does_not_block_the_request(test_client, db_session, admin_user, monkeypatch):
    # T46: the notify is fire-and-forget — a slow monitoring service must not
    # stall server CRUD. The spy blocks until released; the request has to
    # return while it is still blocked.
    import threading
    import time

    import app.modules.servers.router as servers_router

    release = threading.Event()

    class _Resp:
        status_code = 200

    def slow_post(url, **kw):
        release.wait(timeout=10)
        return _Resp()

    monkeypatch.setattr(servers_router.httpx, "post", slow_post)
    headers = _auth(_login(test_client, "admin", "adminpass"))
    t0 = time.monotonic()
    r = test_client.post(
        "/api/servers",
        json={"name": "tsn-slow", "hostname": "slow.example", "tags": ["web"]},
        headers=headers,
    )
    elapsed = time.monotonic() - t0
    assert r.status_code in (200, 201), r.text
    # Synchronous notify would sit in release.wait's 10s timeout — the
    # request must return while the spy is still blocked.
    assert elapsed < 5, f"request blocked on the notify ({elapsed:.1f}s)"
    release.set()
    _drain_notify()
