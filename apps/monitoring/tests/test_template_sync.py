# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""template_sync (audit gap: most complex monitoring logic, previously
untested): variable substitution, the create/update/delete diffing across
servers, assignment removal and full server cleanup, the user's changes and
deleted template checks the sync keeps (R-0420), the check the shipped Host Ping
template creates and the consecutive_oks the shipped templates set (R-0424)."""

import json
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import template_sync
from app.builtin_templates import BUILTIN_TEMPLATES, seed_builtin_templates
from app.models import (
    Base,
    MonitorAgentKey,
    MonitorAlertRule,
    MonitorCheck,
    MonitorCheckTombstone,
    MonitorSeedState,
    MonitorState,
    MonitorTemplate,
    MonitorTemplateAssignment,
)
from app.routers import checks as checks_router
from app.schemas import CheckUpdate
from app.server_cleanup import cleanup_server
from app.template_sync import (
    apply_template,
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
    # After the first start: it marked the changes from before the update. Without
    # the key every sync would mark first, against the template a test just changed
    # (test_template_overrides covers that path).
    with factory() as setup:
        setup.add(MonitorSeedState(slug=template_sync.OVERRIDE_BASELINE_KEY))
        setup.commit()

    # Record scheduler interactions instead of touching the real scheduler.
    # scheduled = check_ids; scheduled_calls = (check_id, check_type) so a test can
    # assert the type reaches add_check (2.34 — without it push-only checks get
    # ghost jobs that fire every interval and abort).
    scheduled, removed, scheduled_calls = [], [], []

    def _record_add(cid, interval, check_type):
        scheduled.append(cid)
        scheduled_calls.append((cid, check_type))

    monkeypatch.setattr(template_sync, "add_check", _record_add)
    monkeypatch.setattr(template_sync, "remove_check", lambda cid: removed.append(cid))
    # The check routes a user's change goes through schedule the same way.
    monkeypatch.setattr(checks_router, "add_check", _record_add)
    monkeypatch.setattr(checks_router, "remove_check", lambda cid: removed.append(cid))

    session = factory()
    session.scheduled = scheduled
    session.removed = removed
    session.scheduled_calls = scheduled_calls
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


# A push-only check type (evaluated only from agent reports, never polled).
AGENT_RES_DEF = {
    "def_id": "agentres",
    "name": "Resources {{server_name}}",
    "check_type": "agent_resources",
    "config": {},
    "interval": "5m",
    "severity": "warning",
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


def test_apply_writes_no_control_characters_from_the_assignment(db):
    # hostname and server_name reach the check name past its schema validator, so
    # C0 and DEL in them become spaces, as in every other substituted field.
    tpl = _template(db, [PING_DEF])

    apply_template(db, tpl, "srv-1", "web01\x7f.example", "Web\n01\x1b")

    check = db.query(MonitorCheck).one()
    assert check.name == "Ping Web 01 "
    assert json.loads(check.config)["host"] == "web01 .example"


def test_apply_passes_check_type_so_push_only_is_skippable(db):
    """2.34: template_sync must pass check_type to add_check; without it, add_check
    can't skip push-only checks (agent_resources, ...) and each one leaves a ghost
    scheduler job that fires execute_check every interval and aborts immediately."""
    tpl = _template(db, [PING_DEF, AGENT_RES_DEF])

    apply_template(db, tpl, "srv-1", "web01.example", "Web 01")

    types = {ctype for _cid, ctype in db.scheduled_calls}
    assert types == {"ping", "agent_resources"}
    assert None not in types  # None was the ghost-job bug: add_check couldn't skip


def test_minimal_defs_get_the_shared_create_defaults(db):
    """2.35: apply and sync both build checks/alerts through _create_check /
    _create_alert, so a def carrying only a def_id + name gets the same column
    defaults on either path — they can't drift out of sync."""
    tpl = _template(
        db,
        [{"def_id": "c", "name": "Minimal Check"}],
        [{"def_id": "a", "name": "Minimal Alert"}],
    )

    apply_template(db, tpl, "srv-1", "web01.example", "Web 01")

    check = db.query(MonitorCheck).one()
    assert (check.check_type, check.interval, check.severity, check.consecutive_fails) == (
        "ping",
        "5m",
        "critical",
        3,
    )
    assert check.enabled is True
    rule = db.query(MonitorAlertRule).one()
    assert (rule.channel, rule.cooldown_minutes, rule.enabled) == ("webhook", 30, True)


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
    from datetime import datetime

    from app.models import MonitorAgentLiveness, MonitorMaintenance

    tpl = _template(db, [PING_DEF], [{"def_id": "a1", "name": "A", "channel": "webhook"}])
    apply_template(db, tpl, "srv-1", "web01.example", "Web 01")
    db.add(MonitorAgentKey(id="k1", server_id="srv-1", hashed_key="h1"))
    db.add(
        MonitorCheck(
            id="manual-1", server_id="srv-1", name="Manuell", check_type="ping", config="{}"
        )
    )
    # T42: server-scoped maintenance + liveness must go with the server; a
    # GLOBAL window (server_id NULL) must survive.
    db.add(MonitorMaintenance(id="m1", server_id="srv-1", kind="once", enabled=True))
    db.add(MonitorMaintenance(id="m-global", server_id=None, kind="once", enabled=True))
    db.add(MonitorAgentLiveness(server_id="srv-1", last_report_at=datetime(2026, 1, 1)))
    db.commit()
    check_ids = sorted(c.id for c in db.query(MonitorCheck))

    result = cleanup_server(db, "srv-1")

    assert result == {"checksDeleted": 2, "alertsDeleted": 1}
    # The scheduler loses the jobs too, through template_sync's scheduler hooks.
    assert sorted(db.removed) == check_ids
    assert db.query(MonitorCheck).count() == 0
    assert db.query(MonitorAlertRule).count() == 0
    assert db.query(MonitorTemplateAssignment).count() == 0
    assert db.query(MonitorAgentKey).count() == 0
    assert db.query(MonitorAgentLiveness).count() == 0
    assert [m.id for m in db.query(MonitorMaintenance).all()] == ["m-global"]


# --- user changes and deleted template checks survive the sync (R-0420) --------


def _tombstones(db):
    return sorted((t.server_id, t.def_id) for t in db.query(MonitorCheckTombstone))


def test_sync_keeps_an_overridden_field_and_updates_the_others(db):
    tpl = _template(db, [PING_DEF])
    apply_template(db, tpl, "srv-1", "web01.example", "Web 01")
    cid = db.query(MonitorCheck).one().id
    checks_router.update_check(cid, CheckUpdate(interval="15m"), db)

    tpl.check_definitions = json.dumps([{**PING_DEF, "interval": "1m", "severity": "warning"}])
    db.commit()
    result = sync_template(db, tpl)

    assert result["updated"] == 1
    check = db.get(MonitorCheck, cid)
    assert (check.interval, check.severity) == ("15m", "warning")
    assert json.loads(check.overridden_fields) == ["interval"]


def test_sync_keeps_a_check_the_user_disabled_disabled(db):
    # PING_DEF carries no "enabled": the sync used to write True and so switched
    # the check on again with every template change.
    tpl = _template(db, [PING_DEF])
    apply_template(db, tpl, "srv-1", "web01.example", "Web 01")
    cid = db.query(MonitorCheck).one().id
    checks_router.toggle_check(cid, db)
    db.scheduled.clear()

    tpl.check_definitions = json.dumps([{**PING_DEF, "severity": "warning"}])
    db.commit()
    sync_template(db, tpl)

    check = db.get(MonitorCheck, cid)
    assert (check.enabled, check.severity) == (False, "warning")
    assert cid not in db.scheduled


def test_sync_keeps_the_type_of_a_check_whose_config_the_user_changed(db):
    # The template's new type with the user's ping config would be a pair nobody
    # validated; type and config stay together, the other fields still follow.
    tpl = _template(db, [PING_DEF])
    apply_template(db, tpl, "srv-1", "web01.example", "Web 01")
    cid = db.query(MonitorCheck).one().id
    checks_router.update_check(cid, CheckUpdate(config={"target": "192.0.2.10"}), db)

    tpl.check_definitions = json.dumps(
        [
            {
                **PING_DEF,
                "check_type": "tcp",
                "config": {"target": "{{hostname}}", "port": 22},
                "severity": "warning",
            }
        ]
    )
    db.commit()
    sync_template(db, tpl)

    check = db.get(MonitorCheck, cid)
    assert (check.check_type, json.loads(check.config), check.severity) == (
        "ping",
        {"target": "192.0.2.10"},
        "warning",
    )
    assert json.loads(check.overridden_fields) == ["config"]


def test_deleted_template_check_is_not_created_again_by_the_sync(db):
    tpl = _template(db, [PING_DEF])
    apply_template(db, tpl, "srv-1", "web01.example", "Web 01")
    apply_template(db, tpl, "srv-2", "db01.example", "DB 01")
    deleted_id = db.query(MonitorCheck).filter_by(server_id="srv-1").one().id
    checks_router.delete_check(deleted_id, db)
    assert _tombstones(db) == [("srv-1", "ping")]

    tpl.check_definitions = json.dumps([{**PING_DEF, "interval": "1m"}])
    db.commit()
    result = sync_template(db, tpl)

    # The tombstone holds for its server only; srv-2 keeps following the template.
    assert result == {"created": 0, "updated": 1, "deleted": 0, "servers": 2}
    assert [(c.server_id, c.interval) for c in db.query(MonitorCheck)] == [("srv-2", "1m")]


def test_deleting_a_manual_or_unassigned_check_leaves_no_tombstone(db):
    tpl = _template(db, [PING_DEF])
    db.add(
        MonitorCheck(
            id="manual-1", server_id="srv-1", name="Manuell", check_type="ping", config="{}"
        )
    )
    # A template check whose server no longer has the template: nothing could
    # create it again, so there is nothing to keep deleted.
    db.add(
        MonitorCheck(
            id="orphan-1",
            server_id="srv-1",
            name="Ping",
            check_type="ping",
            config="{}",
            template_id=tpl.id,
            template_def_id="ping",
        )
    )
    db.commit()

    checks_router.delete_check("manual-1", db)
    checks_router.delete_check("orphan-1", db)

    assert db.query(MonitorCheck).count() == 0
    assert _tombstones(db) == []


def test_overridden_check_is_deleted_when_its_definition_leaves_the_template(db):
    # The template owns its checks: dropping a definition removes the check even
    # where a user adjusted it.
    tpl = _template(db, [PING_DEF])
    apply_template(db, tpl, "srv-1", "web01.example", "Web 01")
    cid = db.query(MonitorCheck).one().id
    checks_router.update_check(cid, CheckUpdate(interval="15m"), db)

    tpl.check_definitions = json.dumps([])
    db.commit()
    result = sync_template(db, tpl)

    assert result["deleted"] == 1
    assert db.query(MonitorCheck).count() == 0
    assert cid in db.removed


def test_remove_and_assign_again_creates_a_deleted_check_again(db):
    tpl = _template(db, [PING_DEF])
    apply_template(db, tpl, "srv-1", "web01.example", "Web 01")
    apply_template(db, tpl, "srv-2", "db01.example", "DB 01")
    for check in db.query(MonitorCheck).all():
        checks_router.delete_check(check.id, db)
    assert _tombstones(db) == [("srv-1", "ping"), ("srv-2", "ping")]

    remove_template(db, tpl.id, "srv-1")
    assert _tombstones(db) == [("srv-2", "ping")]

    apply_template(db, tpl, "srv-1", "web01.example", "Web 01")
    result = sync_template(db, tpl)

    assert result["created"] == 0
    assert [c.server_id for c in db.query(MonitorCheck)] == ["srv-1"]


def test_cleanup_server_removes_the_servers_tombstones(db):
    # Tombstones carry no foreign key to the server (it lives in the server's
    # database), so cleanup_server has to drop them itself.
    tpl_a = _template(db, [PING_DEF])
    tpl_b = _template(db, [PING_DEF])
    for tpl in (tpl_a, tpl_b):
        apply_template(db, tpl, "srv-1", "web01.example", "Web 01")
    apply_template(db, tpl_a, "srv-2", "db01.example", "DB 01")
    for check in db.query(MonitorCheck).all():
        checks_router.delete_check(check.id, db)
    assert len(_tombstones(db)) == 3

    cleanup_server(db, "srv-1")

    assert [(t.template_id, t.server_id) for t in db.query(MonitorCheckTombstone)] == [
        (tpl_a.id, "srv-2")
    ]


# --- consecutive_oks is a template field (R-0424) -------------------------------


def test_sync_writes_the_definitions_consecutive_oks_and_2_without_the_key(db):
    # A definition without the key holds the default, not the check's last value:
    # dropping the key from the template takes the check back to 2.
    tpl = _template(db, [{**PING_DEF, "consecutive_oks": 1}])
    apply_template(db, tpl, "srv-1", "web01.example", "Web 01")
    cid = db.query(MonitorCheck).one().id
    assert db.get(MonitorCheck, cid).consecutive_oks == 1

    tpl.check_definitions = json.dumps([{**PING_DEF, "consecutive_oks": 4}])
    db.commit()
    sync_template(db, tpl)
    assert db.get(MonitorCheck, cid).consecutive_oks == 4

    tpl.check_definitions = json.dumps([PING_DEF])
    db.commit()
    sync_template(db, tpl)
    check = db.get(MonitorCheck, cid)
    assert (check.consecutive_oks, json.loads(check.overridden_fields)) == (2, [])


def test_sync_keeps_a_consecutive_oks_the_user_changed(db):
    tpl = _template(db, [PING_DEF])
    apply_template(db, tpl, "srv-1", "web01.example", "Web 01")
    cid = db.query(MonitorCheck).one().id
    checks_router.update_check(cid, CheckUpdate(consecutive_oks=5), db)
    assert json.loads(db.get(MonitorCheck, cid).overridden_fields) == ["consecutive_oks"]

    tpl.check_definitions = json.dumps([{**PING_DEF, "consecutive_oks": 1, "severity": "warning"}])
    db.commit()
    sync_template(db, tpl)

    check = db.get(MonitorCheck, cid)
    assert (check.consecutive_oks, check.severity) == (5, "warning")
    assert json.loads(check.overridden_fields) == ["consecutive_oks"]


# --- the shipped Host Ping template (R-0424) ------------------------------------


def test_host_ping_pings_the_assigned_hostname_every_minute(db):
    seed_builtin_templates(db)
    tpl = db.query(MonitorTemplate).filter(MonitorTemplate.builtin_slug == "host-ping").one()

    apply_template(db, tpl, "srv-1", "web01.example", "Web 01")

    check = db.query(MonitorCheck).one()
    assert (check.check_type, check.template_def_id, check.name) == (
        "ping",
        "host-ping",
        "Host Ping",
    )
    assert json.loads(check.config) == {"target": "web01.example", "timeout": 3}
    assert (check.interval, check.severity, check.consecutive_fails, check.consecutive_oks) == (
        "1m",
        "critical",
        3,
        2,
    )
    assert db.scheduled_calls == [(check.id, "ping")]


def test_only_the_disk_forecast_of_the_shipped_templates_recovers_on_the_first_ok(db):
    # Disk Forecast runs hourly: with the default 2 its all-clear would come an hour
    # late. Every other shipped check keeps 2, SMART Health (every 5 minutes) too.
    seed_builtin_templates(db)
    for tpl in db.query(MonitorTemplate).all():
        apply_template(db, tpl, tpl.builtin_slug, "host01.example", "Host 01")

    got = {
        (check.server_id, check.template_def_id): check.consecutive_oks
        for check in db.query(MonitorCheck)
    }
    assert len(got) == sum(len(t["check_definitions"]) for t in BUILTIN_TEMPLATES)
    assert {key: oks for key, oks in got.items() if oks != 2} == {
        ("linux-base", "disk-forecast"): 1,
        ("windows-base", "disk-forecast"): 1,
    }
    assert (got[("linux-base", "smart-health")], got[("windows-base", "smart-health")]) == (2, 2)
