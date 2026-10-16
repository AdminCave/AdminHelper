# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Template overrides and check tombstones (R-0420): the schema that lets the
template sync keep a user's change per field (``monitor_checks.overridden_fields``)
and keep a deleted template check deleted (``monitor_check_tombstones``), and the
check routes that mark a changed field as overridden.

The engine enforces foreign keys: SQLite ignores ON DELETE unless the pragma is on,
and the cascade from a deleted template to its tombstones is DB-side only (no ORM
relationship), exactly as on Postgres."""

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.auth import require_internal
from app.core.database import get_db
from app.models import Base, MonitorCheck, MonitorCheckTombstone, MonitorTemplate


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
