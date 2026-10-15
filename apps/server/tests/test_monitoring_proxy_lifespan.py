# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""R-0376: the monitoring proxy survives a second in-process lifespan cycle."""

import httpx

import app.core.events as events
import app.main as m
from app.modules.monitoring_proxy import router as proxy
from app.modules.notifications import stream_hub


def test_proxy_forwards_after_second_lifespan_cycle(test_client, monkeypatch):
    forwarded = []

    async def _noop(*_a, **_k):
        return None

    async def _upstream(self, request):  # the monitoring service, in-process: no network
        forwarded.append(str(request.url))
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(m, "_run_startup_tasks", lambda: None)
    monkeypatch.setattr(events, "fire_event", lambda *a, **k: None)
    monkeypatch.setattr(stream_hub, "start", _noop)
    monkeypatch.setattr(stream_hub, "stop", _noop)
    # On the transport CLASS, not the client: a closed client refuses before it gets there.
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", _upstream)
    # Start from an open client, as a fresh process does, whatever earlier tests left behind;
    # monkeypatch puts their client back afterwards.
    monkeypatch.setattr(proxy, "_client", httpx.AsyncClient(timeout=30))

    with test_client:  # lifespan cycle 1: shutdown closes the proxy client
        pass
    with test_client:  # lifespan cycle 2: the proxy call lands inside it
        try:
            r = test_client.post(
                "/api/monitoring/agent/srv-x/report",
                content=b"{}",
                headers={"X-API-Key": "k", "Content-Type": "application/json"},
            )
            observed = f"HTTP {r.status_code}"
        except Exception as exc:  # TestClient re-raises the handler's exception
            observed = f"{type(exc).__name__}: {exc}"
    assert observed == "HTTP 200", (
        "expected: the agent report is forwarded in the second lifespan cycle (HTTP 200); "
        f"observed: {observed}"
    )
    assert forwarded == [f"{proxy._MONITOR_BASE}/agent/srv-x/report"]


def test_open_client_keeps_an_open_client(monkeypatch):
    """The schemathesis fixture installs its stub before the lifespan starts; a startup that
    replaced an open client would send the fuzzer's forwards to the network instead."""
    stub = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    monkeypatch.setattr(proxy, "_client", stub)

    proxy.open_client()

    assert proxy._client is stub
