# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Template overrides and check tombstones (R-0420): the schema that lets the
template sync keep a user's change per field (``monitor_checks.overridden_fields``)
and keep a deleted template check deleted (``monitor_check_tombstones``), the
check routes that mark a changed field as overridden, and the first start after the
update, which marks the fields changed before it.

The engine enforces foreign keys: SQLite ignores ON DELETE unless the pragma is on,
and the cascade from a deleted template to its tombstones is DB-side only (no ORM
relationship), exactly as on Postgres."""

import copy
import json
import logging
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import builtin_templates, template_sync
from app.builtin_templates import seed_builtin_templates
from app.core.auth import require_internal
from app.core.database import get_db
from app.models import Base, MonitorCheck, MonitorCheckTombstone, MonitorTemplate
from app.tag_sync import sync_tag_assignments
from app.template_sync import apply_template


@pytest.fixture()
def client(monkeypatch):
    from app.main import app

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def _foreign_keys_on(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_internal] = lambda: None
    # The scheduler is not under test; keep jobs out of the process-wide one.
    monkeypatch.setattr("app.routers.checks.add_check", lambda *a, **k: None)
    monkeypatch.setattr("app.template_sync.add_check", lambda *a, **k: None)
    yield TestClient(app), factory
    app.dependency_overrides.clear()


def _tombstone(template_id, server_id="srv-1", def_id="def-ping"):
    return MonitorCheckTombstone(
        id=str(uuid.uuid4()), template_id=template_id, server_id=server_id, def_id=def_id
    )


# --- overridden_fields / templateDefId on the check ----------------------------


def test_new_manual_check_has_no_template_def_and_no_overrides(client):
    c, _factory = client
    r = c.post(
        "/checks",
        json={
            "server_id": "srv-1",
            "name": "ping",
            "check_type": "ping",
            "config": {"target": "192.0.2.10"},
        },
    )
    assert r.status_code == 201
    assert r.json()["templateDefId"] is None
    assert r.json()["overriddenFields"] == []


def test_new_template_check_carries_its_def_id_and_no_overrides(client):
    c, _factory = client
    r = c.post(
        "/templates",
        json={
            "name": "T",
            "check_definitions": [
                {
                    "def_id": "def-ping",
                    "name": "Ping {{server_name}}",
                    "check_type": "ping",
                    "config": {"target": "{{hostname}}"},
                }
            ],
        },
    )
    assert r.status_code == 201
    tid = r.json()["id"]
    assign = {"server_id": "srv-1", "hostname": "web01.example", "server_name": "web01"}
    assert c.post(f"/templates/{tid}/assign", json=assign).status_code == 200

    checks = c.get("/checks", params={"server_id": "srv-1"}).json()
    assert [(ch["templateId"], ch["templateDefId"], ch["overriddenFields"]) for ch in checks] == [
        (tid, "def-ping", [])
    ]


def test_stored_overridden_fields_come_back_as_a_list(client):
    _c, factory = client
    with factory() as db:
        db.add(
            MonitorCheck(
                id="c1",
                server_id="srv-1",
                name="c",
                check_type="ping",
                config="{}",
                overridden_fields='["interval", "enabled"]',
            )
        )
        db.commit()
        assert db.get(MonitorCheck, "c1").to_dict()["overriddenFields"] == ["interval", "enabled"]


def test_row_inserted_without_the_column_gets_the_db_default(client):
    # The migration adds the column to existing rows through this server default;
    # the raw value is read because to_dict would hide a NULL behind "[]".
    _c, factory = client
    with factory() as db:
        db.execute(
            text(
                "INSERT INTO monitor_checks (id, name, check_type, config, interval, severity)"
                " VALUES ('legacy', 'c', 'ping', '{}', '5m', 'critical')"
            )
        )
        db.commit()
        raw = db.execute(
            text("SELECT overridden_fields FROM monitor_checks WHERE id = 'legacy'")
        ).scalar()
    assert raw == "[]"


# --- monitor_check_tombstones ---------------------------------------------------


def test_second_tombstone_for_the_same_template_check_is_rejected(client):
    _c, factory = client
    with factory() as db:
        db.add(MonitorTemplate(id="tpl-1", name="T"))
        db.commit()
        db.add(_tombstone("tpl-1"))
        # Another def or another server is another template check: both allowed.
        db.add(_tombstone("tpl-1", def_id="def-disk"))
        db.add(_tombstone("tpl-1", server_id="srv-2"))
        db.commit()
        assert db.query(MonitorCheckTombstone).count() == 3
        assert all(t.created_at is not None for t in db.query(MonitorCheckTombstone))

        db.add(_tombstone("tpl-1"))
        with pytest.raises(IntegrityError):
            db.commit()


def test_deleting_the_template_removes_its_tombstones(client):
    c, factory = client
    with factory() as db:
        db.add_all([MonitorTemplate(id="tpl-1", name="A"), MonitorTemplate(id="tpl-2", name="B")])
        db.commit()
        db.add_all(
            [_tombstone("tpl-1"), _tombstone("tpl-1", def_id="def-disk"), _tombstone("tpl-2")]
        )
        db.commit()

    assert c.delete("/templates/tpl-1").status_code == 204

    with factory() as db:
        left = [(t.template_id, t.def_id) for t in db.query(MonitorCheckTombstone)]
    assert left == [("tpl-2", "def-ping")]


# --- marking user changes as overridden (update_check, toggle_check) -------------

# Deliberately without "enabled" and "description", like the built-in definitions.
_PING_DEF = {
    "def_id": "def-ping",
    "name": "Ping {{server_name}}",
    "check_type": "ping",
    "config": {"target": "{{hostname}}"},
    "interval": "5m",
    "severity": "critical",
    "consecutive_fails": 3,
}
_ASSIGN = {"server_id": "srv-1", "hostname": "web01.example", "server_name": "web01"}


def _template_check(c, check_def=_PING_DEF) -> str:
    """Create a template with one check definition, assign it to srv-1 and return
    the id of the check the assignment created."""
    r = c.post("/templates", json={"name": "T", "check_definitions": [check_def]})
    assert r.status_code == 201, r.text
    assert c.post(f"/templates/{r.json()['id']}/assign", json=_ASSIGN).status_code == 200
    (check,) = c.get("/checks", params={"server_id": "srv-1"}).json()
    return check["id"]


def test_changing_a_field_marks_it_overridden(client):
    c, _factory = client
    cid = _template_check(c)
    r = c.put(f"/checks/{cid}", json={"interval": "15m"})
    assert r.status_code == 200, r.text
    assert r.json()["overriddenFields"] == ["interval"]


def test_setting_a_field_back_to_the_template_value_clears_it(client):
    c, _factory = client
    cid = _template_check(c)
    c.put(f"/checks/{cid}", json={"interval": "15m"})
    r = c.put(f"/checks/{cid}", json={"interval": "5m"})
    assert r.status_code == 200, r.text
    assert r.json()["overriddenFields"] == []


def test_toggle_marks_enabled_and_toggling_back_clears_it(client):
    c, _factory = client
    cid = _template_check(c)
    r = c.post(f"/checks/{cid}/toggle")
    assert (r.json()["enabled"], r.json()["overriddenFields"]) == (False, ["enabled"])
    r = c.post(f"/checks/{cid}/toggle")
    assert (r.json()["enabled"], r.json()["overriddenFields"]) == (True, [])


def test_type_switch_marks_type_and_config_even_with_the_template_config(client):
    # {"server_id": ...} is a valid config for both types: the config still equals
    # the template's, but it now belongs to another type, so the sync must not
    # write the template's config either.
    c, _factory = client
    cid = _template_check(
        c,
        {
            "def_id": "def-heartbeat",
            "name": "Heartbeat",
            "check_type": "agent_ping",
            "config": {"server_id": "{{server_id}}"},
        },
    )
    r = c.put(f"/checks/{cid}", json={"check_type": "disk_forecast"})
    assert r.status_code == 200, r.text
    assert r.json()["overriddenFields"] == ["check_type", "config"]


def test_full_resend_compares_with_the_resolved_template_values(client):
    # The check editor resends every field; name and config carry the substituted
    # variables, so only the really changed severity counts.
    c, _factory = client
    cid = _template_check(c)
    r = c.put(
        f"/checks/{cid}",
        json={
            "server_id": "srv-1",
            "name": "Ping web01",
            "description": None,
            "check_type": "ping",
            "config": {"target": "web01.example"},
            "enabled": True,
            "interval": "5m",
            "severity": "warning",
            "consecutive_fails": 3,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["overriddenFields"] == ["severity"]


def test_a_field_the_stored_definition_leaves_out_compares_with_its_default(client):
    # The API stores every field of a definition, the built-in seed does not: their
    # checks got the default, so the default is the template value.
    c, factory = client
    with factory() as db:
        db.add(MonitorTemplate(id="tpl-1", name="T", check_definitions=json.dumps([_PING_DEF])))
        db.commit()
    assert c.post("/templates/tpl-1/assign", json=_ASSIGN).status_code == 200
    (check,) = c.get("/checks", params={"server_id": "srv-1"}).json()

    assert c.post(f"/checks/{check['id']}/toggle").json()["overriddenFields"] == ["enabled"]
    assert c.post(f"/checks/{check['id']}/toggle").json()["overriddenFields"] == []
    r = c.put(f"/checks/{check['id']}", json={"description": None})
    assert r.json()["overriddenFields"] == []


def test_manual_check_is_never_marked(client):
    c, _factory = client
    r = c.post(
        "/checks",
        json={
            "server_id": "srv-1",
            "name": "ping",
            "check_type": "ping",
            "config": {"target": "192.0.2.10"},
        },
    )
    cid = r.json()["id"]
    assert c.put(f"/checks/{cid}", json={"interval": "15m"}).json()["overriddenFields"] == []
    assert c.post(f"/checks/{cid}/toggle").json()["overriddenFields"] == []


def test_only_known_field_names_are_stored_as_a_json_list(client):
    # to_dict parses the column unguarded, so the writer must never store anything
    # but a JSON list of overridable field names: a client-sent list is ignored,
    # server_id is no template field, and an unreadable stored value is replaced.
    c, factory = client
    cid = _template_check(c)
    with factory() as db:
        db.get(MonitorCheck, cid).overridden_fields = "not json"
        db.commit()

    r = c.put(
        f"/checks/{cid}",
        json={"interval": "15m", "server_id": "srv-1", "overridden_fields": ["evil"]},
    )
    assert r.status_code == 200, r.text

    with factory() as db:
        raw = db.execute(
            text("SELECT overridden_fields FROM monitor_checks WHERE id = :id"), {"id": cid}
        ).scalar()
    assert json.loads(raw) == ["interval"]


# --- changes from before the update: marked once at the first start ---------------

_RENAMED = [{"id": "srv-1", "hostname": "web02.example", "name": "web02", "tags": []}]


def _changed_before_the_update(factory, cid, **columns):
    """Change a template check the way the code before overridden_fields did: the
    columns only, nothing marked."""
    with factory() as db:
        check = db.get(MonitorCheck, cid)
        for column, value in columns.items():
            setattr(check, column, value)
        db.commit()


def _first_start(factory) -> int:
    with factory() as db:
        return template_sync.record_override_baseline(db)


def _overrides(factory, cid) -> list[str]:
    with factory() as db:
        return json.loads(db.get(MonitorCheck, cid).overridden_fields)


def test_first_start_marks_a_field_changed_before_the_update(client, caplog):
    c, factory = client
    cid = _template_check(c)
    _changed_before_the_update(factory, cid, interval="1h")

    with caplog.at_level(logging.INFO, logger="monitor.template_sync"):
        assert _first_start(factory) == 1

    assert _overrides(factory, cid) == ["interval"]
    assert any("1 of 1" in m for m in caplog.messages), caplog.messages


def test_first_start_leaves_an_unchanged_check_unmarked(client):
    c, factory = client
    cid = _template_check(c)

    assert _first_start(factory) == 0
    assert _overrides(factory, cid) == []


def test_first_start_marks_a_check_disabled_before_the_update(client):
    c, factory = client
    cid = _template_check(c)
    _changed_before_the_update(factory, cid, enabled=False)

    assert _first_start(factory) == 1
    assert _overrides(factory, cid) == ["enabled"]


def test_first_start_marks_a_changed_type_together_with_its_config(client):
    # The coupling of a type switch through the check routes: the config is still
    # the template's, but it now belongs to the user's type.
    c, factory = client
    cid = _template_check(c)
    _changed_before_the_update(factory, cid, check_type="tcp")

    assert _first_start(factory) == 1
    assert _overrides(factory, cid) == ["check_type", "config"]


def test_first_start_resolves_the_template_with_the_names_the_check_was_built_from(client):
    # The server was renamed in the inventory before the update. Its assignment and
    # check carry the old names until the first tag sync: no change of the user's,
    # so the tag sync still brings the new names into name and config.
    c, factory = client
    cid = _template_check(c)

    assert _first_start(factory) == 0
    assert _overrides(factory, cid) == []

    with factory() as db:
        assert sync_tag_assignments(db, _RENAMED)["refreshed"] == 1
        check = db.get(MonitorCheck, cid)
        assert (check.name, json.loads(check.config)) == (
            "Ping web02",
            {"target": "web02.example"},
        )


def test_first_start_leaves_manual_checks_and_checks_without_a_definition_alone(client):
    c, factory = client
    cid = _template_check(c)
    manual = c.post(
        "/checks",
        json={
            "server_id": "srv-1",
            "name": "ping",
            "check_type": "ping",
            "config": {"target": "192.0.2.10"},
        },
    ).json()["id"]
    _changed_before_the_update(factory, cid, interval="1h")
    _changed_before_the_update(factory, manual, interval="1h")
    # The definition left the template without a sync (that would delete the check).
    with factory() as db:
        db.get(MonitorTemplate, db.get(MonitorCheck, cid).template_id).check_definitions = "[]"
        db.commit()

    assert _first_start(factory) == 0
    assert (_overrides(factory, cid), _overrides(factory, manual)) == ([], [])


def test_second_start_marks_nothing_again_even_after_later_changes(client):
    c, factory = client
    cid = _template_check(c)
    _changed_before_the_update(factory, cid, interval="1h")
    assert _first_start(factory) == 1
    # Later the user takes the template's values back, and a field changes past the
    # check routes: comparing once more would now mark the severity.
    assert c.post(f"/checks/{cid}/reset").status_code == 200
    _changed_before_the_update(factory, cid, severity="warning")

    assert _first_start(factory) == 0
    assert _overrides(factory, cid) == []


def test_a_change_marked_at_the_first_start_survives_template_sync_and_rename(client):
    c, factory = client
    cid = _template_check(c)
    _changed_before_the_update(factory, cid, interval="1h")
    _first_start(factory)
    with factory() as db:
        tid = db.get(MonitorCheck, cid).template_id

    r = c.put(
        f"/templates/{tid}", json={"check_definitions": [{**_PING_DEF, "severity": "warning"}]}
    )
    assert r.status_code == 200, r.text
    with factory() as db:
        assert sync_tag_assignments(db, _RENAMED)["refreshed"] == 1
        check = db.get(MonitorCheck, cid)
        assert (check.interval, check.severity, json.loads(check.config)) == (
            "1h",
            "warning",
            {"target": "web02.example"},
        )


@pytest.fixture()
def start(client, monkeypatch):
    """The service's startup against the test database, without the scheduler and
    the agent liveness: start() runs it once and says whether it got as far as
    scheduling the checks."""
    from app import scheduler as scheduler_mod
    from app.main import app

    _c, factory = client
    loaded: list[bool] = []
    monkeypatch.setattr("app.core.database.SessionLocal", factory)
    monkeypatch.setattr("app.checkers.agent.hydrate_agent_liveness", lambda entries: None)
    monkeypatch.setattr(scheduler_mod, "load_all_checks", lambda: loaded.append(True))
    monkeypatch.setattr(scheduler_mod, "schedule_alert_log_cleanup", lambda: None)
    monkeypatch.setattr(scheduler_mod, "schedule_tag_sync", lambda: None)
    monkeypatch.setattr(
        scheduler_mod,
        "scheduler",
        SimpleNamespace(start=lambda: None, shutdown=lambda wait: None),
    )
    monkeypatch.setattr(template_sync, "remove_check", lambda *a, **k: None)

    def run() -> bool:
        loaded.clear()
        with TestClient(app):
            pass
        return loaded == [True]

    return run


def _ship_linux_base_v2(monkeypatch) -> int:
    """Ship a new version of linux-base (the shipped one + 1): system-resources
    warns every minute. Returns the new version."""
    shipped = copy.deepcopy(builtin_templates.BUILTIN_TEMPLATES)
    linux = next(t for t in shipped if t["slug"] == "linux-base")
    linux["version"] += 1
    for check_def in linux["check_definitions"]:
        if check_def["def_id"] == "system-resources":
            check_def.update(severity="warning", interval="1m")
    monkeypatch.setattr(builtin_templates, "BUILTIN_TEMPLATES", shipped)
    return linux["version"]


def test_start_marks_earlier_changes_before_it_updates_the_builtins(client, start, monkeypatch):
    # An unedited built-in follows a new version at startup and syncs its checks:
    # by then the change from before the update has to be known.
    _c, factory = client
    with factory() as db:
        seed_builtin_templates(db)
        linux = db.query(MonitorTemplate).filter_by(builtin_slug="linux-base").one()
        apply_template(db, linux, "srv-1", "web01.example", "web01")
        check = db.query(MonitorCheck).filter_by(template_def_id="system-resources").one()
        check.interval = "1h"
        db.commit()
        cid = check.id
    new_version = _ship_linux_base_v2(monkeypatch)

    assert start()

    with factory() as db:
        check = db.get(MonitorCheck, cid)
        assert (check.interval, check.severity) == ("1h", "warning")
        assert json.loads(check.overridden_fields) == ["interval"]
        linux = db.query(MonitorTemplate).filter_by(builtin_slug="linux-base").one()
        assert linux.builtin_version == new_version


def test_a_failed_first_start_keeps_nothing_and_the_next_start_marks(client, start, monkeypatch):
    # Two servers, so the run fails halfway: the mark it already made is not kept
    # either, and nothing records the run as done. The service starts all the same.
    c, factory = client
    first = _template_check(c)
    with factory() as db:
        tid = db.get(MonitorCheck, first).template_id
    db01 = {"server_id": "srv-2", "hostname": "db01.example", "server_name": "db01"}
    assert c.post(f"/templates/{tid}/assign", json=db01).status_code == 200
    with factory() as db:
        cids = sorted(cid for (cid,) in db.query(MonitorCheck.id))
    for cid in cids:
        _changed_before_the_update(factory, cid, interval="1h")

    real = template_sync.mark_overrides
    calls: list[str] = []

    def connection_lost_after_the_first(db, check, changed):
        calls.append(check.id)
        if len(calls) > 1:
            raise _connection_lost()
        real(db, check, changed)

    monkeypatch.setattr(template_sync, "mark_overrides", connection_lost_after_the_first)
    assert start()
    assert len(calls) > 1
    assert [_overrides(factory, cid) for cid in cids] == [[], []]

    monkeypatch.setattr(template_sync, "mark_overrides", real)
    assert start()
    assert [_overrides(factory, cid) for cid in cids] == [["interval"], ["interval"]]


def _connection_lost() -> OperationalError:
    return OperationalError("UPDATE monitor_checks", {}, Exception("connection lost"))


def _linux_base_on_srv_1_with_interval_1h(factory) -> str:
    """linux-base assigned to srv-1, its system-resources check changed to 1h before
    the update; returns that check's id."""
    with factory() as db:
        seed_builtin_templates(db)
        linux = db.query(MonitorTemplate).filter_by(builtin_slug="linux-base").one()
        apply_template(db, linux, "srv-1", "web01.example", "web01")
        cid = db.query(MonitorCheck).filter_by(template_def_id="system-resources").one().id
    _changed_before_the_update(factory, cid, interval="1h")
    return cid


def _interval_severity_overrides(factory, cid) -> tuple[str, str, list[str]]:
    with factory() as db:
        check = db.get(MonitorCheck, cid)
        return check.interval, check.severity, json.loads(check.overridden_fields)


def test_a_built_in_update_waits_for_a_failed_first_start(client, start, monkeypatch):
    # Security's probe: version 2 of an unedited built-in ships while the baseline
    # fails on the first start. The rollout must not run without it; the next start
    # marks the change and rolls out.
    _c, factory = client
    cid = _linux_base_on_srv_1_with_interval_1h(factory)
    new_version = _ship_linux_base_v2(monkeypatch)
    real = template_sync.mark_overrides

    def connection_lost(*_args):
        raise _connection_lost()

    monkeypatch.setattr(template_sync, "mark_overrides", connection_lost)
    assert start()
    assert _interval_severity_overrides(factory, cid) == ("1h", "critical", [])
    with factory() as db:
        linux = db.query(MonitorTemplate).filter_by(builtin_slug="linux-base").one()
        assert linux.builtin_version == new_version - 1

    monkeypatch.setattr(template_sync, "mark_overrides", real)
    assert start()
    assert _interval_severity_overrides(factory, cid) == ("1h", "warning", ["interval"])
    with factory() as db:
        linux = db.query(MonitorTemplate).filter_by(builtin_slug="linux-base").one()
        assert linux.builtin_version == new_version


def test_tag_sync_before_the_baseline_marks_first_with_the_names_from_before(client):
    # The baseline has to compare before the rename reaches the assignment: with the
    # new names, the old name and config would count as the user's.
    c, factory = client
    cid = _template_check(c)
    _changed_before_the_update(factory, cid, interval="1h")

    with factory() as db:
        assert sync_tag_assignments(db, _RENAMED)["refreshed"] == 1
        check = db.get(MonitorCheck, cid)
        assert (check.interval, check.name, json.loads(check.config)) == (
            "1h",
            "Ping web02",
            {"target": "web02.example"},
        )
        assert json.loads(check.overridden_fields) == ["interval"]


@pytest.mark.parametrize("sync", ["sync_template", "restore"])
def test_a_sync_before_the_baseline_marks_first(client, sync):
    c, factory = client
    cid = _template_check(c)
    _changed_before_the_update(factory, cid, interval="1h")
    with factory() as db:
        tid = db.get(MonitorCheck, cid).template_id

    if sync == "sync_template":
        with factory() as db:
            template_sync.sync_template(db, db.get(MonitorTemplate, tid))
    else:
        assert c.post(f"/templates/{tid}/assign/srv-1/restore").status_code == 200

    assert _interval_severity_overrides(factory, cid) == ("1h", "critical", ["interval"])


def test_a_template_change_before_the_baseline_is_compared_with_the_template_before_it(client):
    # Compared with the changed template, the severity nobody touched would count as
    # changed and would not follow the template.
    c, factory = client
    cid = _template_check(c)
    _changed_before_the_update(factory, cid, interval="1h")
    with factory() as db:
        tid = db.get(MonitorCheck, cid).template_id

    r = c.put(
        f"/templates/{tid}", json={"check_definitions": [{**_PING_DEF, "severity": "warning"}]}
    )
    assert r.status_code == 200, r.text
    assert _interval_severity_overrides(factory, cid) == ("1h", "warning", ["interval"])


def test_taking_a_built_in_update_before_the_baseline_keeps_the_change(client, monkeypatch):
    c, factory = client
    cid = _linux_base_on_srv_1_with_interval_1h(factory)
    with factory() as db:
        tid = db.get(MonitorCheck, cid).template_id
    _ship_linux_base_v2(monkeypatch)

    r = c.post(f"/templates/{tid}/builtin-update")
    assert r.status_code == 200, r.text
    assert _interval_severity_overrides(factory, cid) == ("1h", "warning", ["interval"])


def test_a_check_whose_config_cannot_be_read_is_kept_as_it_is(client, caplog):
    # One broken row must not stop the baseline for all the others, and no sync may
    # touch it: every field counts as changed.
    c, factory = client
    first = _template_check(c)
    with factory() as db:
        tid = db.get(MonitorCheck, first).template_id
    db01 = {"server_id": "srv-2", "hostname": "db01.example", "server_name": "db01"}
    assert c.post(f"/templates/{tid}/assign", json=db01).status_code == 200
    with factory() as db:
        broken = db.query(MonitorCheck).filter_by(server_id="srv-2").one().id
    _changed_before_the_update(factory, first, interval="1h")
    _changed_before_the_update(factory, broken, config="{not json")

    with caplog.at_level(logging.INFO, logger="monitor.template_sync"):
        assert _first_start(factory) == 2

    assert _overrides(factory, first) == ["interval"]
    assert _overrides(factory, broken) == list(template_sync.TEMPLATE_CHECK_FIELDS)
    assert any(broken in m for m in caplog.messages), caplog.messages
    assert any("1 not comparable" in m for m in caplog.messages), caplog.messages
    assert _first_start(factory) == 0  # recorded
    with factory() as db:
        template_sync.sync_template(db, db.get(MonitorTemplate, tid))
        assert db.get(MonitorCheck, broken).config == "{not json"


def test_a_check_whose_template_cannot_be_read_is_kept_as_it_is(client):
    c, factory = client
    cid = _template_check(c)
    with factory() as db:
        db.get(MonitorTemplate, db.get(MonitorCheck, cid).template_id).check_definitions = "{"
        db.commit()

    assert _first_start(factory) == 1
    assert _overrides(factory, cid) == list(template_sync.TEMPLATE_CHECK_FIELDS)


def test_the_baseline_key_is_no_built_in_slug():
    assert ":" in template_sync.OVERRIDE_BASELINE_KEY
    assert [t["slug"] for t in builtin_templates.BUILTIN_TEMPLATES if ":" in t["slug"]] == []
