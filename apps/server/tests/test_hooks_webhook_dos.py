# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Webhook DoS hardening (audit #1 + #9).

- #1: run_hook_script is offloaded off the event loop (run_in_threadpool); this
  test pins that the offloaded webhook path still works end-to-end.
- #9: the per-IP trigger limit now uses the central rate_limit backend (with
  eviction/TTL) instead of an unbounded hand-rolled dict.
- R-0845: the timeout also bounds a run whose worker does not read its payload.
"""

import threading

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
    statuses = [
        test_client.post(f"/api/hooks/trigger/{wt}", json={}).status_code for _ in range(22)
    ]
    assert 429 in statuses, f"no rate limit hit: {statuses}"
    assert statuses.count(200) <= 20, statuses


def test_unknown_webhook_token_is_404(test_client, db_session):
    # The token IS the auth for the public trigger; an unknown token must be a 404 via the
    # hashed_token lookup (a regression comparing against plaintext would open script exec) (6.75).
    reset_backend_for_tests()
    r = test_client.post("/api/hooks/trigger/definitiv-falsch", json={})
    assert r.status_code == 404, r.text


def test_disabled_webhook_is_403(test_client, db_session, admin_user):
    # A disabled hook must be refused (403), not executed (6.75).
    from app.modules.hooks.models import Hook

    reset_backend_for_tests()
    wt = _create_webhook(test_client, _admin_token(test_client), "log('x')")
    hook = db_session.query(Hook).filter(Hook.hook_type == "webhook").first()
    hook.enabled = False
    db_session.commit()

    r = test_client.post(f"/api/hooks/trigger/{wt}", json={})
    assert r.status_code == 403, r.text


def test_a_run_whose_worker_does_not_read_a_large_payload_ends_at_the_timeout(
    tmp_path, monkeypatch
):
    # R-0845: a payload larger than the pipe buffer blocks a writer whose reader never reads; the
    # timeout must bound that write as well, not only the wait for the worker's exit.
    import app.modules.hooks.script_runner as sr

    worker = tmp_path / "deaf_worker.py"
    worker.write_text("import time\ntime.sleep(15)\n")
    monkeypatch.setattr(sr, "_WORKER_SCRIPT", str(worker))
    results = []
    runner = threading.Thread(
        target=lambda: results.append(
            sr.run_hook_script("#" * (1 << 20), "webhook", {}, timeout=1)
        ),
        daemon=True,
    )
    runner.start()
    runner.join(10)
    assert not runner.is_alive(), "the run blocked on writing the payload past its timeout"
    assert results[0]["error"] == "Timeout nach 1s", results
