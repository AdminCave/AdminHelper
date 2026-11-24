# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""SERVER_ENABLE_DOCS gates /api/docs and /openapi.json; an empty MONITOR_API_KEY is logged (R-0699)."""

import asyncio
import importlib
import logging
import sys

import pytest
from fastapi.testclient import TestClient


def _fresh_app(monkeypatch, value):
    # The gate is read when app.main builds the app, so each case imports a fresh module;
    # the original stays in sys.modules for every other test.
    if value is None:
        monkeypatch.delenv("SERVER_ENABLE_DOCS", raising=False)
    else:
        monkeypatch.setenv("SERVER_ENABLE_DOCS", value)
    import app as app_package

    monkeypatch.setattr(app_package, "main", sys.modules["app.main"])
    monkeypatch.delitem(sys.modules, "app.main")
    return importlib.import_module("app.main").app


@pytest.mark.parametrize("value", [None, "", "0", "false", "no"])
def test_docs_and_schema_are_off_by_default(monkeypatch, value):
    client = TestClient(_fresh_app(monkeypatch, value))
    assert client.get("/api/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


@pytest.mark.parametrize("value", ["1", "true", "YES"])
def test_docs_and_schema_are_served_when_enabled(monkeypatch, value):
    client = TestClient(_fresh_app(monkeypatch, value))
    assert client.get("/api/docs").status_code == 200
    schema = client.get("/openapi.json")
    assert schema.status_code == 200
    assert schema.json()["info"]["title"] == "AdminHelper Server"


def test_schema_stays_available_in_process_when_off(monkeypatch):
    # Snapshot and schemathesis read app.openapi(), not the route.
    app = _fresh_app(monkeypatch, None)
    assert "/api/auth/login" in app.openapi()["paths"]


def _run_lifespan(monkeypatch, key):
    # Same isolation as test_bootstrap's lifespan tests: no startup DB work, no Redis.
    import app.core.events as events
    import app.main as m
    from app.core import config
    from app.modules.notifications import stream_hub

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(config, "MONITOR_API_KEY", key)
    monkeypatch.setattr(m, "_run_startup_tasks", lambda: None)
    monkeypatch.setattr(events, "fire_event", lambda *a, **k: None)
    monkeypatch.setattr(stream_hub, "start", _noop)
    monkeypatch.setattr(stream_hub, "stop", _noop)

    async def scenario():
        async with m.lifespan(m.app):
            pass

    asyncio.run(scenario())


def _main_errors(caplog):
    return [r for r in caplog.records if r.name == "app.main" and r.levelno >= logging.ERROR]


def test_empty_monitor_key_logs_one_error(monkeypatch, caplog):
    with caplog.at_level(logging.ERROR, logger="app.main"):
        _run_lifespan(monkeypatch, "")
    errors = _main_errors(caplog)
    assert len(errors) == 1, errors
    assert "MONITOR_API_KEY" in errors[0].getMessage()
    assert "init-secrets.sh" in errors[0].getMessage()


def test_set_monitor_key_logs_no_error(monkeypatch, caplog):
    with caplog.at_level(logging.ERROR, logger="app.main"):
        _run_lifespan(monkeypatch, "k" * 32)
    assert _main_errors(caplog) == []
