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
