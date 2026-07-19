# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The public (JWT-free) agent-ingest proxy is rate-limited per IP (audit #8/#16)."""

from app.core.rate_limit import get_backend, reset_backend_for_tests


def test_agent_ingest_is_rate_limited(test_client):
    reset_backend_for_tests()
    backend = get_backend()
    # Pre-load the per-IP window to the cap (TestClient's client.host == "testclient")
    # so the next request trips the limit BEFORE the proxy-forward is attempted.
    for _ in range(120):
        backend.increment("agent_ingest:testclient", 60)
    r = test_client.post(
        "/api/monitoring/agent/srv-x/report",
        content=b"{}",
        headers={"X-API-Key": "irrelevant", "Content-Type": "application/json"},
    )
    assert r.status_code == 429, r.text


def test_agent_report_forwards_via_shared_client(test_client, monkeypatch):
    # 5.30: the proxy forwards through the process-wide _client, not a fresh AsyncClient per request.
    from app.modules.monitoring_proxy import router as mp

    reset_backend_for_tests()  # ensure this request isn't rate-limited

    class _FakeResp:
        content = b'{"ok": true}'
        status_code = 200
        headers = {"content-type": "application/json"}

    calls = {"n": 0}

    async def fake_post(url, **kw):
        calls["n"] += 1
        return _FakeResp()

    monkeypatch.setattr(mp._client, "post", fake_post)
    r = test_client.post(
        "/api/monitoring/agent/srv-x/report",
        content=b"{}",
        headers={"X-API-Key": "k", "Content-Type": "application/json"},
    )
    assert r.status_code == 200, r.text
    assert calls["n"] == 1  # forwarded through the shared client, not a per-request AsyncClient


def _admin_headers(client) -> dict:
    r = client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_monitoring_proxy_rejects_traversal_and_unknown_prefix(test_client, db_session, admin_user):
    # The catch-all proxy is the only SSRF boundary between the admin browser and the internal
    # monitoring service (reached with X-Internal-Key). Its allowlist (".."-filter + prefix list)
    # must reject path traversal and unknown prefixes with 400 (6.76).
    h = _admin_headers(test_client)
    # %2e%2e keeps the ".." literal — a plain ".." is collapsed by the client before it is sent.
    assert test_client.get("/api/monitoring/%2e%2e/secret", headers=h).status_code == 400
    assert test_client.get("/api/monitoring/admin/keys", headers=h).status_code == 400
    assert test_client.get("/api/monitoring/etc/passwd", headers=h).status_code == 400


def test_monitoring_proxy_allows_known_prefix(test_client, db_session, admin_user, monkeypatch):
    # A known prefix (status) is forwarded, not over-blocked by the allowlist.
    from app.modules.monitoring_proxy import router as mp

    class _FakeResp:
        content = b"[]"
        status_code = 200
        headers = {"content-type": "application/json"}

    async def fake_request(**kw):
        return _FakeResp()

    monkeypatch.setattr(mp._client, "request", fake_request)
    resp = test_client.get("/api/monitoring/status", headers=_admin_headers(test_client))
    assert resp.status_code == 200  # allowed prefix -> forwarded, not 400


def test_monitoring_proxy_allows_maintenance_prefix(
    test_client, db_session, admin_user, monkeypatch
):
    # T24: the new maintenance CRUD must pass the proxy allowlist.
    from app.modules.monitoring_proxy import router as mp

    class _FakeResp:
        content = b"[]"
        status_code = 200
        headers = {"content-type": "application/json"}

    async def fake_request(**kw):
        return _FakeResp()

    monkeypatch.setattr(mp._client, "request", fake_request)
    resp = test_client.get("/api/monitoring/maintenance", headers=_admin_headers(test_client))
    assert resp.status_code == 200
