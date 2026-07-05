# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Agent push path (audit gap): the report endpoint must apply the same
consecutive-fails damping as the scheduler path — including the
"(Fehler n/m)" suppression suffix that the inline copy used to lack."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.auth import require_agent
from app.core.database import get_db
from app.models import Base, MonitorAlertRule, MonitorCheck, MonitorState


@pytest.fixture()
def client_db(monkeypatch):
    """TestClient against the real app with sqlite, auth bypassed and
    VictoriaMetrics writes stubbed out."""
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
    # Background alert dispatch opens its own session via database.SessionLocal;
    # point it at the same sqlite so post-response tasks hit the test DB.
    import app.core.database as database_mod

    monkeypatch.setattr(database_mod, "SessionLocal", factory)
    monkeypatch.setattr(victoria_mod.victoria, "write", lambda lines: None)
    monkeypatch.setattr(victoria_mod.victoria, "write_check_result", lambda **kw: None)

    yield TestClient(app), factory

    app.dependency_overrides.clear()


def _add_resources_check(factory, consecutive_fails: int) -> str:
    with factory() as db:
        db.add(
            MonitorCheck(
                id="chk-1",
                server_id="srv-1",
                name="Resources",
                check_type="agent_resources",
                config=json.dumps({"cpu_warn": 80, "cpu_crit": 95}),
                enabled=True,
                consecutive_fails=consecutive_fails,
            )
        )
        db.commit()
    return "chk-1"


def _report(cpu: float) -> dict:
    return {"resources": {"cpu_percent": cpu}}


def test_report_applies_consecutive_fails_damping(client_db):
    client, factory = client_db
    _add_resources_check(factory, consecutive_fails=2)

    # 1st failing push: below the damping threshold -> stays ok (suppressed),
    # message carries the scheduler-path suffix.
    r = client.post("/agent/srv-1/report", json=_report(cpu=99))
    assert r.status_code == 200
    assert r.json()["checksUpdated"] == 1
    with factory() as db:
        state = db.query(MonitorState).filter_by(check_id="chk-1").one()
        assert state.status == "ok"
        assert state.fail_count == 1
        assert "(Fehler 1/2)" in state.message

    # 2nd failing push: threshold reached -> critical.
    client.post("/agent/srv-1/report", json=_report(cpu=99))
    with factory() as db:
        state = db.query(MonitorState).filter_by(check_id="chk-1").one()
        assert state.status == "critical"
        assert state.fail_count == 2

    # Recovery push: back to ok, fail counter reset.
    client.post("/agent/srv-1/report", json=_report(cpu=5))
    with factory() as db:
        state = db.query(MonitorState).filter_by(check_id="chk-1").one()
        assert state.status == "ok"
        assert state.fail_count == 0


def test_report_rejects_foreign_server_key(client_db):
    client, factory = client_db
    # The dependency override authenticates as srv-1; pushing for another
    # server id must be rejected (key/server binding).
    r = client.post("/agent/srv-2/report", json=_report(cpu=5))
    assert r.status_code == 403


def test_status_change_dispatches_alert_in_background(client_db, monkeypatch):
    """H6: a status change schedules the alert dispatch as a background task
    (off the request path). TestClient runs background tasks after the response,
    so the recorded dispatch proves the wiring without blocking the request."""
    client, factory = client_db
    _add_resources_check(factory, consecutive_fails=1)  # flips on the first fail
    with factory() as db:
        db.add(
            MonitorAlertRule(
                id="r1",
                name="rule",
                channel="webhook",
                channel_config=json.dumps({"url": "https://hooks.example/x"}),
            )
        )
        db.commit()

    from app import alerter

    dispatched: list[tuple] = []
    monkeypatch.setattr(
        alerter,
        "_dispatch",
        lambda rule, check, msg: (
            dispatched.append((check.id, msg["old_status"], msg["new_status"])) or (True, None)
        ),
    )

    r = client.post("/agent/srv-1/report", json=_report(cpu=99))
    assert r.status_code == 200
    assert dispatched == [("chk-1", "pending", "critical")]


def test_capped_limits_length_and_rejects_non_list():
    from app.routers.agent import _MAX_REPORT_ITEMS, _capped

    # 3.76: cap array length so a huge report can't flood the service, and treat a
    # non-list (a malicious agent sending disks="x" or null) as empty rather than
    # iterating it as chars.
    assert _capped(list(range(1000))) == list(range(_MAX_REPORT_ITEMS))
    assert _capped([1, 2, 3]) == [1, 2, 3]
    assert _capped(None) == []
    assert _capped("string") == []
    assert _capped({"a": 1}) == []
