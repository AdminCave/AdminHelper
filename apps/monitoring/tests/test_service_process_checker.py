# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""ServiceProcessChecker under inventory throttling.

The agent omits systemd.all_services on most pushes (the inventory is large
and mostly static); failed/enabled_inactive and the watched "services" list
are always sent. A missing all_services key must fall back to the legacy
keys — and must NOT be treated like an empty inventory — so checks keep
working and the stored check state stays intact on throttled pushes.
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.checkers.agent import ServiceProcessChecker
from app.core.auth import require_agent
from app.core.database import get_db
from app.models import Base, MonitorCheck, MonitorState


def _full_report() -> dict:
    """Report with the full inventory (hash changed / hourly full send)."""
    return {
        "systemd": {
            "failed": ["nginx.service"],
            "enabled_inactive": ["cron.service"],
            "all_services": [
                {"unit": "nginx.service", "active_state": "failed", "enabled_state": "enabled"},
                {"unit": "cron.service", "active_state": "inactive", "enabled_state": "enabled"},
                {"unit": "sshd.service", "active_state": "active", "enabled_state": "enabled"},
            ],
        },
        "services": [{"name": "nginx", "running": False, "pid": None}],
    }


def _throttled_report() -> dict:
    """Same agent state, but all_services omitted (throttled push)."""
    report = _full_report()
    del report["systemd"]["all_services"]
    return report


def test_auto_mode_full_and_throttled_report_agree():
    checker = ServiceProcessChecker()
    full = checker.evaluate({"mode": "auto"}, _full_report())
    throttled = checker.evaluate({"mode": "auto"}, _throttled_report())
    # Identical status, metrics and details — throttling must be invisible.
    assert full == throttled
    status, _, metrics = throttled
    assert status == "critical"
    assert metrics["services_failed"] == 1
    assert metrics["_details"]["failed"] == ["nginx.service"]
    assert metrics["_details"]["enabled_inactive"] == ["cron.service"]


def test_auto_mode_missing_key_is_not_empty_inventory():
    # Throttled push with healthy legacy keys -> ok, not "unknown"/failure.
    report = {"systemd": {"failed": [], "enabled_inactive": []}}
    status, _, _ = ServiceProcessChecker().evaluate({"mode": "auto"}, report)
    assert status == "ok"

    # Empty all_services list means genuinely empty -> also ok, but via v2 path.
    report = {"systemd": {"failed": [], "enabled_inactive": [], "all_services": []}}
    status, _, _ = ServiceProcessChecker().evaluate({"mode": "auto"}, report)
    assert status == "ok"


def test_list_mode_unaffected_by_throttling():
    # Watched services are always sent; list mode must work without all_services.
    status, message, _ = ServiceProcessChecker().evaluate(
        {"mode": "list", "services": ["nginx"]}, _throttled_report()
    )
    assert status == "critical"
    assert "nginx" in message


@pytest.fixture()
def client_db(monkeypatch):
    """TestClient against the real app with sqlite, auth bypassed and
    VictoriaMetrics writes stubbed out (same pattern as test_agent_report)."""
    from app.core import victoria as victoria_mod
    from app.main import app

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_agent] = lambda: "srv-1"
    monkeypatch.setattr(victoria_mod.victoria, "write", lambda lines: None)
    monkeypatch.setattr(victoria_mod.victoria, "write_check_result", lambda **kw: None)
    # Background alert dispatch opens its OWN session via database.SessionLocal (not get_db). Without
    # this patch _dispatch_alert_bg would hit the real DATABASE_URL — a hidden network dependency that
    # silently exercises the swallowed error path instead of the dispatch path, and a DROP'd connect
    # would hang the suite (6.61). Mirrors test_agent_report.py.
    import app.core.database as database_mod

    monkeypatch.setattr(database_mod, "SessionLocal", factory)

    yield TestClient(app), factory

    app.dependency_overrides.clear()


def test_throttled_push_keeps_stored_state(client_db):
    client, factory = client_db
    with factory() as db:
        db.add(
            MonitorCheck(
                id="chk-svc",
                server_id="srv-1",
                name="Services",
                check_type="service_process",
                config=json.dumps({"mode": "auto"}),
                enabled=True,
                consecutive_fails=1,
            )
        )
        db.commit()

    # Full push establishes the stored state.
    r = client.post("/agent/srv-1/report", json=_full_report())
    assert r.status_code == 200
    with factory() as db:
        state = db.query(MonitorState).filter_by(check_id="chk-svc").one()
        assert state.status == "critical"
        assert json.loads(state.details)["failed"] == ["nginx.service"]

    # Throttled push (no all_services key): stored state must survive intact.
    r = client.post("/agent/srv-1/report", json=_throttled_report())
    assert r.status_code == 200
    with factory() as db:
        state = db.query(MonitorState).filter_by(check_id="chk-svc").one()
        assert state.status == "critical"
        assert json.loads(state.details)["failed"] == ["nginx.service"]
        assert json.loads(state.details)["enabled_inactive"] == ["cron.service"]
