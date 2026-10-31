# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A monitoring service that does not answer: the proxy says so with 502 or, for a
timeout, 504, instead of a 500; the warning names the error type only (R-0655)."""

import logging

import httpx
import pytest

from app.core.config import MONITOR_API_KEY
from app.modules.monitoring_proxy import router as proxy

_LOGGER = "app.modules.monitoring_proxy.router"

_ERRORS = [
    pytest.param(httpx.ConnectError, 502, "monitoring service unreachable", id="connect"),
    pytest.param(httpx.ReadTimeout, 504, "monitoring service timed out", id="timeout"),
]


def _failing_client(monkeypatch, error):
    def handler(request):
        raise error("x", request=request)

    monkeypatch.setattr(proxy, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def _call(make_request):
    """The status the client gets, or the exception the TestClient re-raised."""
    try:
        r = make_request()
    except Exception as exc:  # TestClient re-raises an exception the handler let through
        return f"{type(exc).__name__}: {exc}", None
    return r.status_code, r.json().get("detail")


def _one_warning(caplog, error):
    records = [r for r in caplog.records if r.name == _LOGGER and r.levelno == logging.WARNING]
    assert len(records) == 1, [r.getMessage() for r in records]
    message = records[0].getMessage()
    assert error.__name__ in message
    assert proxy._MONITOR_BASE not in message
    assert not MONITOR_API_KEY or MONITOR_API_KEY not in message
    assert "'k'" not in message and " k " not in message


@pytest.mark.parametrize(("error", "status", "detail"), _ERRORS)
def test_the_agent_report_forward(
    test_client, db_session, monkeypatch, caplog, error, status, detail
):
    _failing_client(monkeypatch, error)
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        observed = _call(
            lambda: test_client.post(
                "/api/monitoring/agent/srv-x/report",
                content=b"{}",
                headers={"X-API-Key": "k", "Content-Type": "application/json"},
            )
        )
    assert observed == (status, detail)
    _one_warning(caplog, error)


@pytest.mark.parametrize(("error", "status", "detail"), _ERRORS)
def test_the_admin_proxy(
    test_client, db_session, admin_user, monkeypatch, caplog, error, status, detail
):
    login = test_client.post("/api/auth/login", json={"username": "admin", "password": "adminpass"})
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    _failing_client(monkeypatch, error)
    with caplog.at_level(logging.WARNING, logger=_LOGGER):
        observed = _call(lambda: test_client.get("/api/monitoring/status", headers=headers))
    assert observed == (status, detail)
    _one_warning(caplog, error)
