# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""R-1601: every way that deletes checks closes the bell's incident of each whose
alarm it shows, as delete_check does (R-1571); "gone" switches the checks off and
the catch-up job sends their all-clear."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import alerter, template_sync
from app.models import Base, MonitorCheck, MonitorSeedState, MonitorState, MonitorTemplate
from app.routers import templates as templates_router
from app.server_cleanup import cleanup_server
from app.template_sync import apply_template, remove_template, sync_template

PING = {
    "def_id": "ping",
    "name": "Ping {{server_name}}",
    "check_type": "ping",
    "config": {"host": "{{hostname}}"},
    "interval": "5m",
    "severity": "critical",
}
HTTP = {**PING, "def_id": "http", "name": "HTTP {{server_name}}", "check_type": "http",
        "config": {"url": "https://{{hostname}}"}}  # fmt: skip


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(MonitorSeedState(slug=template_sync.OVERRIDE_BASELINE_KEY))
    session.commit()
    monkeypatch.setattr(template_sync, "add_check", lambda *args: None)
    monkeypatch.setattr(template_sync, "remove_check", lambda cid: None)
    monkeypatch.setattr(templates_router, "remove_check", lambda cid: None)
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def hub(monkeypatch):
    """A hub that answers each POST from ``answers`` (True once they run out) and
    keeps (new_status, severity, title) of each POST in ``posts``."""
    hub = type("Hub", (), {})()
    hub.answers = []
    hub.posts = []

    def post(payload, label):
        hub.posts.append((payload["new_status"], payload["severity"], payload["title"]))
        return hub.answers.pop(0) if hub.answers else True

    monkeypatch.setattr(alerter, "post_hub_event", post)
    return hub


def _assigned(db, *defs, server_id="srv-1"):
    """A template with ``defs`` applied to ``server_id``; the bell shows critical
    of the ping check and nothing of the others."""
    tpl = MonitorTemplate(
        id=str(uuid.uuid4()), name="Linux Base", check_definitions=json.dumps(list(defs)),
        alert_definitions="[]",
    )  # fmt: skip
    db.add(tpl)
    db.commit()
    apply_template(db, tpl, server_id, "web01.example", "Web 01")
    for check in db.query(MonitorCheck).filter(MonitorCheck.template_id == tpl.id):
        if check.template_def_id == "ping":
            state = db.get(MonitorState, check.id)
            state.status = state.notified_status = state.hub_status = "critical"
    db.commit()
    return tpl


def _closed(hub):
    return [
        (status, severity, title.endswith(": check deleted"))
        for status, severity, title in hub.posts
    ]


def test_deleting_the_template_closes_the_incident(db, hub):
    tpl = _assigned(db, PING, HTTP)

    templates_router.delete_template(tpl.id, db)

    assert _closed(hub) == [("ok", "critical", True)]


def test_removing_the_assignment_closes_the_incident(db, hub):
    tpl = _assigned(db, PING, HTTP)

    remove_template(db, tpl.id, "srv-1")

    assert _closed(hub) == [("ok", "critical", True)]


def test_a_definition_the_sync_drops_closes_the_incident(db, hub):
    tpl = _assigned(db, PING, HTTP)
    tpl.check_definitions = json.dumps([HTTP])
    db.commit()

    sync_template(db, tpl)

    assert db.query(MonitorCheck).count() == 1
    assert _closed(hub) == [("ok", "critical", True)]


def test_deleting_the_server_closes_the_incident(db, hub):
    _assigned(db, PING, HTTP)
    _assigned(db, PING, server_id="srv-2")

    cleanup_server(db, "srv-1")

    assert _closed(hub) == [("ok", "critical", True)]


def test_the_all_clear_goes_at_the_level_the_alarm_reached_the_bell_with(db, hub):
    tpl = _assigned(db, PING)
    db.query(MonitorState).update({"hub_status": "warning"})
    db.commit()

    remove_template(db, tpl.id, "srv-1")

    assert _closed(hub) == [("ok", "warning", True)]


def test_a_check_the_bell_shows_no_problem_of_sends_nothing(db, hub):
    tpl = _assigned(db, PING)
    db.query(MonitorState).update({"hub_status": "ok"})
    db.commit()

    remove_template(db, tpl.id, "srv-1")

    assert hub.posts == []


def test_a_refused_all_clear_is_logged_and_the_delete_stands(db, hub, caplog):
    tpl = _assigned(db, PING)
    hub.answers = [False]

    remove_template(db, tpl.id, "srv-1")

    assert db.query(MonitorCheck).count() == 0
    assert "the incident stays open" in caplog.text
