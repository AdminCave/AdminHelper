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

from app.core.database import get_db
from app.core.auth import require_agent
from app.models import Base, MonitorCheck, MonitorState


@pytest.fixture()
def client_db(monkeypatch):
    """TestClient against the real app with sqlite, auth bypassed and
    VictoriaMetrics writes stubbed out."""
    from app.main import app
    from app.core import victoria as victoria_mod

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
    monkeypatch.setattr(
        victoria_mod.victoria, "write_check_result", lambda **kw: None
    )

    yield TestClient(app), factory

    app.dependency_overrides.clear()


def _add_resources_check(factory, consecutive_fails: int) -> str:
    with factory() as db:
        db.add(MonitorCheck(
            id="chk-1", server_id="srv-1", name="Resources",
            check_type="agent_resources",
            config=json.dumps({"cpu_warn": 80, "cpu_crit": 95}),
            enabled=True, consecutive_fails=consecutive_fails,
        ))
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
