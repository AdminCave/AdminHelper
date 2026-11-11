# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The agent's plan through the server (R-1223): GET /api/monitoring/agent/{id}/plan is
forwarded like the report, with the agent's X-API-Key and never the internal key, and
the monitoring's answer passes untouched. It sits behind the binding of an agent
certificate to its server, the agent scope and a rate counter of its own."""

import logging

import httpx
import pytest

from app.core import config
from app.core.config import MONITOR_API_KEY
from app.core.identity import SCOPE_ACCESS, SCOPE_AGENT
from app.core.rate_limit import get_backend, reset_backend_for_tests
from app.modules.monitoring_proxy import router as proxy
from tests.test_mtls_scope import _gateway_headers

_LOGGER = "app.modules.monitoring_proxy.router"
_PLAN = b'{"catalog_version":"sha256:x","checks":[],"scan":false}'


@pytest.fixture(autouse=True)
def _fresh_counters():
    reset_backend_for_tests()
    yield
    reset_backend_for_tests()


class _Monitoring:
    """The monitoring service behind a real AsyncClient on a MockTransport, so httpx's own
    URL handling runs; records every request it gets."""

    def __init__(self, monkeypatch, response=None):
        self.seen: list[httpx.Request] = []
        self.response = response or httpx.Response(
            200, content=_PLAN, headers={"content-type": "application/json"}
        )
        monkeypatch.setattr(
            proxy, "_client", httpx.AsyncClient(transport=httpx.MockTransport(self._handle))
        )

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        return self.response


def _plan(test_client, server_id="srv-1", headers=None):
    return test_client.get(
        f"/api/monitoring/agent/{server_id}/plan", headers={"X-API-Key": "k", **(headers or {})}
    )


def _admin_headers(client) -> dict:
    r = client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# --- forwarding --------------------------------------------------------------------------


def test_the_plan_is_forwarded_with_the_agents_key(test_client, monkeypatch):
    monitoring = _Monitoring(monkeypatch)

    resp = _plan(test_client)

    assert (resp.status_code, resp.content) == (200, _PLAN)
    assert resp.headers["content-type"] == "application/json"
    [request] = monitoring.seen
    assert (request.method, request.url.raw_path) == ("GET", b"/agent/srv-1/plan")
    assert request.headers["x-api-key"] == "k"
    assert "x-internal-key" not in request.headers


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (401, b'{"detail":"Invalid API key"}'),
        (403, b'{"detail":"API key does not belong to this server"}'),
        (404, b'{"detail":"Server not found"}'),
    ],
)
def test_the_monitorings_answer_passes_untouched(test_client, monkeypatch, status, body):
    # Not a text/* type: Starlette appends a charset to those, the proxy does not.
    _Monitoring(
        monkeypatch,
        httpx.Response(status, content=body, headers={"content-type": "application/x-y"}),
    )

    resp = _plan(test_client)

    assert (resp.status_code, resp.content, resp.headers["content-type"]) == (
        status,
        body,
        "application/x-y",
    )


def test_an_admin_token_does_not_make_it_an_internal_call(test_client, admin_user, monkeypatch):
    # The admin catch-all forwards with X-Internal-Key; the plan route must win over it.
    monitoring = _Monitoring(monkeypatch)

    resp = test_client.get("/api/monitoring/agent/srv-1/plan", headers=_admin_headers(test_client))

    assert resp.status_code == 200, resp.text
    [request] = monitoring.seen
    assert "x-internal-key" not in request.headers
    assert request.headers["x-api-key"] == ""


@pytest.mark.parametrize("wire_id", ["%1F", "web%3Fx", "web%231"])
def test_an_encoded_server_id_stays_encoded(test_client, monkeypatch, wire_id):
    # `server_id` arrives decoded: re-embedded raw, '?'/'#' would cut the target URL short.
    monitoring = _Monitoring(monkeypatch)

    resp = _plan(test_client, wire_id)

    assert resp.status_code == 200, resp.text
    assert [r.url.raw_path for r in monitoring.seen] == [f"/agent/{wire_id}/plan".encode()]


# --- its own rate counter ----------------------------------------------------------------


def _fill(counter):
    # TestClient's client.host is "testclient".
    backend = get_backend()
    for _ in range(proxy._INGEST_MAX):
        backend.increment(f"{counter}:testclient", proxy._INGEST_WINDOW)


def test_the_plan_is_rate_limited_per_address(test_client, monkeypatch):
    monitoring = _Monitoring(monkeypatch)
    _fill("agent_plan")

    resp = _plan(test_client)

    assert resp.status_code == 429, resp.text
    assert monitoring.seen == []


def test_the_report_counter_does_not_limit_the_plan(test_client, monkeypatch):
    monitoring = _Monitoring(monkeypatch)
    _fill("agent_ingest")

    assert _plan(test_client).status_code == 200
    assert len(monitoring.seen) == 1


def test_the_plan_counter_does_not_limit_the_report(test_client, monkeypatch):
    monitoring = _Monitoring(monkeypatch, httpx.Response(202, json={"ok": True}))
    _fill("agent_plan")

    resp = test_client.post(
        "/api/monitoring/agent/srv-1/report",
        content=b"{}",
        headers={"X-API-Key": "k", "Content-Type": "application/json"},
    )

    assert resp.status_code == 202, resp.text
    assert len(monitoring.seen) == 1


# --- certificate and scope ---------------------------------------------------------------


@pytest.mark.parametrize("enforced", [False, True])
def test_another_servers_certificate_is_refused(test_client, monkeypatch, enforced):
    monkeypatch.setattr(config, "MTLS_ENFORCE", enforced)
    monitoring = _Monitoring(monkeypatch)

    resp = _plan(test_client, "srv-1", _gateway_headers(cn="srv-2", ou=SCOPE_AGENT))

    assert resp.status_code == 403, resp.text
    assert resp.json()["code"] == "ERR_CERT_SERVER_MISMATCH", resp.text
    assert monitoring.seen == []


@pytest.mark.parametrize(
    "headers",
    [
        pytest.param({}, id="no-certificate"),
        pytest.param(_gateway_headers(cn="srv-1", ou=SCOPE_ACCESS), id="access-certificate"),
    ],
)
def test_enforced_it_takes_only_an_agent_certificate(test_client, monkeypatch, headers):
    monkeypatch.setattr(config, "MTLS_ENFORCE", True)
    monitoring = _Monitoring(monkeypatch)

    resp = _plan(test_client, "srv-1", headers)

    assert resp.status_code == 403, resp.text
    assert monitoring.seen == []


def test_enforced_its_own_certificate_is_forwarded(test_client, monkeypatch):
    monkeypatch.setattr(config, "MTLS_ENFORCE", True)
    monitoring = _Monitoring(monkeypatch)

    resp = _plan(test_client, "srv-1", _gateway_headers(cn="srv-1", ou=SCOPE_AGENT))

    assert resp.status_code == 200, resp.text
    assert len(monitoring.seen) == 1


def test_permissive_without_a_certificate_it_is_forwarded(test_client, monkeypatch):
    monkeypatch.setattr(config, "MTLS_ENFORCE", False)
    monitoring = _Monitoring(monkeypatch)

    assert _plan(test_client).status_code == 200
    assert len(monitoring.seen) == 1


# --- a monitoring service that does not answer -------------------------------------------


@pytest.mark.parametrize(
    ("error", "status", "detail"),
    [
        pytest.param(httpx.ConnectError, 502, "monitoring service unreachable", id="connect"),
        pytest.param(httpx.ReadTimeout, 504, "monitoring service timed out", id="timeout"),
    ],
)
def test_an_unanswered_forward(test_client, monkeypatch, caplog, error, status, detail):
    def handler(request):
        raise error("x", request=request)

    monkeypatch.setattr(proxy, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        resp = _plan(test_client)

    assert (resp.status_code, resp.json()["detail"]) == (status, detail)
    records = [r for r in caplog.records if r.name == _LOGGER and r.levelno == logging.WARNING]
    assert len(records) == 1, [r.getMessage() for r in records]
    message = records[0].getMessage()
    assert error.__name__ in message and "agent plan" in message
    assert proxy._MONITOR_BASE not in message
    assert not MONITOR_API_KEY or MONITOR_API_KEY not in message
