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
