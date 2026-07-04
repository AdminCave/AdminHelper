# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""template_sync (audit gap: most complex monitoring logic, previously
untested): variable substitution, the create/update/delete diffing across
servers, assignment removal and full server cleanup."""

import json
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import template_sync
from app.models import (
    Base,
    MonitorAgentKey,
    MonitorAlertRule,
    MonitorCheck,
    MonitorState,
    MonitorTemplate,
    MonitorTemplateAssignment,
)
from app.template_sync import (
    apply_template,
    cleanup_server,
    remove_template,
    substitute_variables,
    sync_template,
)

# --- substitute_variables -------------------------------------------------------


def test_substitute_string_and_nested_structures():
    variables = {"hostname": "web01.example", "server_name": "Web 01"}
    obj = {
        "name": "Ping {{server_name}}",
        "config": {"host": "{{hostname}}", "port": 22, "list": ["{{hostname}}", 5]},
    }
    out = substitute_variables(obj, variables)
    assert out["name"] == "Ping Web 01"
    assert out["config"]["host"] == "web01.example"
    assert out["config"]["list"] == ["web01.example", 5]
    # non-strings pass through untouched
    assert out["config"]["port"] == 22


def test_substitute_none_value_becomes_empty_string():
    assert substitute_variables("x{{a}}y", {"a": None}) == "xy"


def test_substitute_unknown_placeholder_stays():
    assert substitute_variables("{{unknown}}", {"a": 1}) == "{{unknown}}"


# --- DB-backed fixtures ---------------------------------------------------------


@pytest.fixture()
def db(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    # Record scheduler interactions instead of touching the real scheduler.
    scheduled, removed = [], []
    monkeypatch.setattr(template_sync, "add_check", lambda cid, interval, *a: scheduled.append(cid))
    monkeypatch.setattr(template_sync, "remove_check", lambda cid: removed.append(cid))

    session = factory()
    session.scheduled = scheduled
    session.removed = removed
    yield session
    session.close()


def _template(db, check_defs, alert_defs=None):
    tpl = MonitorTemplate(
        id=str(uuid.uuid4()),
        name="Linux Base",
        check_definitions=json.dumps(check_defs),
        alert_definitions=json.dumps(alert_defs or []),
    )
    db.add(tpl)
    db.commit()
    return tpl


PING_DEF = {
    "def_id": "ping",
    "name": "Ping {{server_name}}",
    "check_type": "ping",
    "config": {"host": "{{hostname}}"},
    "interval": "5m",
    "severity": "critical",
}


# --- apply_template -------------------------------------------------------------


def test_apply_creates_checks_states_and_alerts(db):
    tpl = _template(
        db,
        [PING_DEF],
        [
            {
                "def_id": "mail",
                "name": "Mail {{server_name}}",
                "channel": "email",
                "channel_config": {"to": "ops@example"},
            }
        ],
    )

    result = apply_template(db, tpl, "srv-1", "web01.example", "Web 01")

    assert len(result["checksCreated"]) == 1
    assert len(result["alertsCreated"]) == 1

    check = db.query(MonitorCheck).one()
    assert check.name == "Ping Web 01"
    assert json.loads(check.config)["host"] == "web01.example"
    assert check.template_def_id == "ping"
    assert db.query(MonitorState).filter_by(check_id=check.id).one().status == "pending"
    assert check.id in db.scheduled

    rule = db.query(MonitorAlertRule).one()
    assert rule.name == "Mail Web 01"
    assert rule.match_server_id == "srv-1"


def test_apply_does_not_schedule_when_commit_fails(db, monkeypatch):
    """1.21: scheduler mutations run only AFTER a successful commit — a failed /
    rolled-back commit must not leave ghost jobs behind."""
    tpl = _template(db, [PING_DEF])

    def _boom():
        raise RuntimeError("commit fail")

    monkeypatch.setattr(db, "commit", _boom)
    with pytest.raises(RuntimeError):
        apply_template(db, tpl, "srv-1", "web01.example", "Web 01")
    assert db.scheduled == []  # no job registered when the DB write did not commit


# --- sync_template diffing ------------------------------------------------------


def test_sync_updates_existing_creates_new_deletes_removed(db):
    tpl = _template(db, [PING_DEF])
    apply_template(db, tpl, "srv-1", "web01.example", "Web 01")
    original_check_id = db.query(MonitorCheck).one().id

    # Template evolves: ping gets a new interval, an http check is added.
    tpl.check_definitions = json.dumps(
        [
            {**PING_DEF, "interval": "1m"},
            {
                "def_id": "http",
                "name": "HTTP {{server_name}}",
                "check_type": "http",
                "config": {"url": "https://{{hostname}}"},
            },
        ]
    )
    db.commit()

    result = sync_template(db, tpl)
    assert result == {"created": 1, "updated": 1, "deleted": 0, "servers": 1}

    # Update happened in place: same row id, new interval.
    ping = db.query(MonitorCheck).filter_by(template_def_id="ping").one()
    assert ping.id == original_check_id
    assert ping.interval == "1m"
    http = db.query(MonitorCheck).filter_by(template_def_id="http").one()
    assert json.loads(http.config)["url"] == "https://web01.example"

    # Template drops the ping definition -> its check is deleted.
    tpl.check_definitions = json.dumps(
        [
            {
                "def_id": "http",
                "name": "HTTP {{server_name}}",
                "check_type": "http",
                "config": {"url": "https://{{hostname}}"},
            },
        ]
    )
    db.commit()
    result = sync_template(db, tpl)
    assert result["deleted"] == 1
    assert db.query(MonitorCheck).filter_by(template_def_id="ping").count() == 0
    assert original_check_id in db.removed


def test_sync_disabled_check_is_unscheduled(db):
    tpl = _template(db, [PING_DEF])
    apply_template(db, tpl, "srv-1", "web01.example", "Web 01")
    check_id = db.query(MonitorCheck).one().id

    tpl.check_definitions = json.dumps([{**PING_DEF, "enabled": False}])
    db.commit()
    sync_template(db, tpl)

    assert check_id in db.removed
    assert db.query(MonitorCheck).one().enabled is False


def test_sync_ignores_defs_without_def_id_and_manual_checks(db):
    tpl = _template(db, [PING_DEF])
    apply_template(db, tpl, "srv-1", "web01.example", "Web 01")

    # A manually created check on the same server must survive every sync.
    db.add(
        MonitorCheck(
            id="manual-1", server_id="srv-1", name="Manuell", check_type="ping", config="{}"
        )
    )
    # Defs without def_id are skipped (not created, nothing deleted for them).
    tpl.check_definitions = json.dumps([PING_DEF, {"name": "kaputt, ohne def_id"}])
    db.commit()

    result = sync_template(db, tpl)
    assert result["created"] == 0
    assert result["deleted"] == 0
    assert db.query(MonitorCheck).filter_by(id="manual-1").count() == 1


def test_sync_covers_all_assigned_servers(db):
    tpl = _template(db, [PING_DEF])
    apply_template(db, tpl, "srv-1", "web01.example", "Web 01")
    apply_template(db, tpl, "srv-2", "db01.example", "DB 01")

    tpl.check_definitions = json.dumps([{**PING_DEF, "severity": "warning"}])
    db.commit()
    result = sync_template(db, tpl)

    assert result["updated"] == 2
    severities = {c.server_id: c.severity for c in db.query(MonitorCheck).all()}
    assert severities == {"srv-1": "warning", "srv-2": "warning"}
    names = {c.server_id: c.name for c in db.query(MonitorCheck).all()}
    assert names["srv-2"] == "Ping DB 01"  # per-server variables stay correct


# --- remove_template / cleanup_server -------------------------------------------


def test_remove_template_deletes_only_this_assignment(db):
    tpl = _template(db, [PING_DEF], [{"def_id": "a1", "name": "A", "channel": "webhook"}])
    apply_template(db, tpl, "srv-1", "web01.example", "Web 01")
    apply_template(db, tpl, "srv-2", "db01.example", "DB 01")

    result = remove_template(db, tpl.id, "srv-1")
    assert result == {"checksDeleted": 1, "alertsDeleted": 1}
    assert db.query(MonitorCheck).filter_by(server_id="srv-1").count() == 0
    assert db.query(MonitorCheck).filter_by(server_id="srv-2").count() == 1
    assert db.query(MonitorTemplateAssignment).filter_by(server_id="srv-1").count() == 0
    assert db.query(MonitorTemplateAssignment).filter_by(server_id="srv-2").count() == 1


def test_cleanup_server_removes_everything_for_server(db):
    tpl = _template(db, [PING_DEF], [{"def_id": "a1", "name": "A", "channel": "webhook"}])
    apply_template(db, tpl, "srv-1", "web01.example", "Web 01")
    db.add(MonitorAgentKey(id="k1", server_id="srv-1", hashed_key="h1"))
    db.add(
        MonitorCheck(
            id="manual-1", server_id="srv-1", name="Manuell", check_type="ping", config="{}"
        )
    )
    db.commit()

    result = cleanup_server(db, "srv-1")

    assert result == {"checksDeleted": 2, "alertsDeleted": 1}
    assert db.query(MonitorCheck).count() == 0
    assert db.query(MonitorAlertRule).count() == 0
    assert db.query(MonitorTemplateAssignment).count() == 0
    assert db.query(MonitorAgentKey).count() == 0
