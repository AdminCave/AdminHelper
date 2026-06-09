# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Webhook DoS hardening (audit #1 + #9).

- #1: run_hook_script is offloaded off the event loop (run_in_threadpool); this
  test pins that the offloaded webhook path still works end-to-end.
- #9: the per-IP trigger limit now uses the central rate_limit backend (with
  eviction/TTL) instead of an unbounded hand-rolled dict.
"""

from app.core.rate_limit import reset_backend_for_tests


def _admin_token(client) -> str:
    r = client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _create_webhook(client, admin_token: str, script: str) -> str:
    r = client.post(
        "/api/hooks",
        json={"name": "wh", "hook_type": "webhook", "script": script},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["token"]


def test_webhook_trigger_works_after_offload(test_client, db_session, admin_user):
    reset_backend_for_tests()
    wt = _create_webhook(test_client, _admin_token(test_client), "log('hello-from-hook')")
    r = test_client.post(f"/api/hooks/trigger/{wt}", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("success") is True, body
    assert "hello-from-hook" in body.get("logs", []), body


def test_webhook_trigger_is_rate_limited(test_client, db_session, admin_user):
    reset_backend_for_tests()
    wt = _create_webhook(test_client, _admin_token(test_client), "log('x')")
    statuses = [test_client.post(f"/api/hooks/trigger/{wt}", json={}).status_code for _ in range(22)]
    assert 429 in statuses, f"no rate limit hit: {statuses}"
    assert statuses.count(200) <= 20, statuses
