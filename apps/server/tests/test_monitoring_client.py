# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""R-0691: every server call to the monitoring service builds its URL in one place, so
a MONITOR_SERVICE_URL with a trailing slash no longer yields `//` (which the
monitoring's no-prefix routes answer with 404)."""

import pytest

from app.core import config

BASE = "http://monitor.test"


@pytest.fixture()
def slash_url(monkeypatch):
    monkeypatch.setattr(config, "MONITOR_SERVICE_URL", BASE + "/")
    monkeypatch.setattr(config, "MONITOR_API_KEY", "internal-k")


def test_tag_sync_url_without_double_slash(slash_url, httpx_mock):
    from app.modules.servers import router as servers_router

    httpx_mock.add_response(method="POST", url=BASE + "/templates/tag-sync", status_code=204)
    servers_router._do_notify_tag_sync("test")
    (req,) = httpx_mock.get_requests()
    assert str(req.url) == BASE + "/templates/tag-sync"
    assert req.headers["X-Internal-Key"] == "internal-k"


def test_cleanup_url_without_double_slash(slash_url, httpx_mock, test_client, admin_user):
    from app.modules.servers import router as servers_router

    httpx_mock.add_response(
        method="POST", url=BASE + "/templates/tag-sync", status_code=204, is_reusable=True
    )
    login = test_client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    created = test_client.post(
        "/api/servers", json={"name": "srv-x", "hostname": "x.example"}, headers=headers
    )
    assert created.status_code in (200, 201), created.text
    sid = created.json()["id"]
    httpx_mock.add_response(method="DELETE", url=f"{BASE}/servers/{sid}/cleanup", status_code=204)
    res = test_client.delete(f"/api/servers/{sid}", headers=headers)
    assert res.status_code in (200, 204), res.text
    servers_router._NOTIFY_POOL.submit(lambda: None).result()
    cleanups = [r for r in httpx_mock.get_requests() if r.method == "DELETE"]
    assert [str(r.url) for r in cleanups] == [f"{BASE}/servers/{sid}/cleanup"]
    assert cleanups[0].headers["X-Internal-Key"] == "internal-k"


def test_agent_key_and_state_urls_without_double_slash(slash_url, httpx_mock):
    from app.modules.provisioning import helpers, progress

    httpx_mock.add_response(
        method="POST", url=BASE + "/agent-keys/s1", json={"apiKey": "raw"}, status_code=201
    )
    httpx_mock.add_response(method="GET", url=BASE + "/agent/s1/state", json={})
    assert helpers.fetch_or_skip_monitor_key("s1") == "raw"
    assert progress._monitor_state("s1")[1] is True
    assert {r.headers["X-Internal-Key"] for r in httpx_mock.get_requests()} == {"internal-k"}


def test_base_url_is_read_at_call_time(monkeypatch):
    from app.core import monitoring_client

    monkeypatch.setattr(config, "MONITOR_SERVICE_URL", "http://a.test//")
    assert monitoring_client.base_url() == "http://a.test"
    monkeypatch.setattr(config, "MONITOR_SERVICE_URL", "http://b.test")
    assert monitoring_client.base_url() == "http://b.test"
