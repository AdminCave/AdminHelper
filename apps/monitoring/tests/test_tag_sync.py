# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tag-sync reconciliation (T10): template→tag bindings materialize into
per-server assignments (source='tag'), stale materialized rows are removed,
tag membership never touches manual assignments, a renamed server reaches all
its assignments and their checks (R-0420), and an unavailable hub inventory
changes nothing (None ≠ empty list)."""

import json
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import (
    Base,
    MonitorCheck,
    MonitorTemplate,
    MonitorTemplateAssignment,
    MonitorTemplateTagAssignment,
)
from app.routers import checks as checks_router
from app.schemas import CheckUpdate
from app.tag_sync import sync_tag_assignments
from app.template_sync import apply_template


@pytest.fixture()
def db(monkeypatch):
    # apply/remove_template mutate the scheduler — neutralize like test_template_sync.
    import app.template_sync as ts

    monkeypatch.setattr(ts, "add_check", lambda *a, **k: None)
    monkeypatch.setattr(ts, "remove_check", lambda *a, **k: None)
    # So does a user's change through the check routes.
    monkeypatch.setattr(checks_router, "add_check", lambda *a, **k: None)
    monkeypatch.setattr(checks_router, "remove_check", lambda *a, **k: None)

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


def _template(db, tid="tpl-1", defs=None):
    db.add(
        MonitorTemplate(
            id=tid,
            name="T",
            check_definitions=json.dumps(defs or []),
            alert_definitions="[]",
        )
    )
    db.commit()
    return tid


def _bind(db, tid, tag):
    db.add(MonitorTemplateTagAssignment(id=str(uuid.uuid4()), template_id=tid, tag=tag))
    db.commit()


def _srv(sid, tags):
    return {"id": sid, "hostname": f"h-{sid}", "name": f"n-{sid}", "tags": tags}


def _assignments(db):
    return {(a.template_id, a.server_id): a for a in db.query(MonitorTemplateAssignment).all()}


def test_materializes_assignments_for_tagged_servers(db):
    tid = _template(
        db,
        defs=[
            {
                "def_id": "d1",
                "name": "Ping {{hostname}}",
                "check_type": "ping",
                "config": {"target": "{{hostname}}"},
                "interval": "5m",
                "severity": "critical",
                "consecutive_fails": 3,
                "enabled": True,
            }
        ],
    )
    _bind(db, tid, "web")

    result = sync_tag_assignments(db, [_srv("srv-1", ["web"]), _srv("srv-2", ["db"])])
    assert result == {"created": 1, "removed": 0, "refreshed": 0}

    rows = _assignments(db)
    assert set(rows) == {(tid, "srv-1")}
    assert rows[(tid, "srv-1")].source == "tag"
    # apply_template materialized the checks with substituted variables.
    check = db.query(MonitorCheck).filter_by(server_id="srv-1").one()
    assert check.name == "Ping h-srv-1"

    # Idempotent second run.
    assert sync_tag_assignments(db, [_srv("srv-1", ["web"]), _srv("srv-2", ["db"])]) == {
        "created": 0,
        "removed": 0,
        "refreshed": 0,
    }


def test_removes_stale_materialized_assignment(db):
    tid = _template(db)
    _bind(db, tid, "web")
    sync_tag_assignments(db, [_srv("srv-1", ["web"])])
    assert (tid, "srv-1") in _assignments(db)

    # Server loses the tag -> materialized row disappears.
    result = sync_tag_assignments(db, [_srv("srv-1", [])])
    assert result == {"created": 0, "removed": 1, "refreshed": 0}
    assert _assignments(db) == {}


def test_manual_assignment_is_never_touched(db):
    tid = _template(db)
    # Names as in the inventory: a rename does reach manual rows (tested below).
    db.add(
        MonitorTemplateAssignment(
            id="man-1",
            template_id=tid,
            server_id="srv-1",
            server_hostname="h-srv-1",
            server_name="n-srv-1",
            source="manual",
        )
    )
    db.commit()

    # Desired pair already covered manually -> no duplicate, no conversion.
    _bind(db, tid, "web")
    assert sync_tag_assignments(db, [_srv("srv-1", ["web"])]) == {
        "created": 0,
        "removed": 0,
        "refreshed": 0,
    }
    assert _assignments(db)[(tid, "srv-1")].source == "manual"

    # Binding gone, server untagged -> the manual row still stays.
    db.query(MonitorTemplateTagAssignment).delete()
    db.commit()
    assert sync_tag_assignments(db, [_srv("srv-1", [])]) == {
        "created": 0,
        "removed": 0,
        "refreshed": 0,
    }
    assert (tid, "srv-1") in _assignments(db)


def test_unavailable_inventory_changes_nothing(db, monkeypatch):
    import app.tag_sync as tag_sync_mod

    tid = _template(db)
    _bind(db, tid, "web")
    sync_tag_assignments(db, [_srv("srv-1", ["web"])])

    # Hub down: fetch yields None -> sync must be a no-op returning None —
    # NOT tear down the materialized assignments like an empty inventory would.
    monkeypatch.setattr(tag_sync_mod, "fetch_inventory", lambda: None)
    assert sync_tag_assignments(db) is None
    assert (tid, "srv-1") in _assignments(db)


def test_binding_for_deleted_template_is_skipped(db):
    tid = _template(db)
    _bind(db, tid, "web")
    db.query(MonitorTemplate).delete()
    db.commit()

    # Stale binding without template must not crash the sync (SQLite keeps the
    # row without FK enforcement; Postgres would CASCADE it away).
    assert sync_tag_assignments(db, [_srv("srv-1", ["web"])]) == {
        "created": 0,
        "removed": 0,
        "refreshed": 0,
    }


def test_malformed_inventory_entries_are_ignored(db):
    tid = _template(db)
    _bind(db, tid, "web")
    inventory = ["not-a-dict", {"tags": ["web"]}, _srv("srv-1", ["web"])]
    assert sync_tag_assignments(db, inventory) == {"created": 1, "removed": 0, "refreshed": 0}
    assert set(_assignments(db)) == {(tid, "srv-1")}


# --- a renamed server reaches its existing assignments (R-0420) -----------------

PING_DEF = {
    "def_id": "ping",
    "name": "Ping {{server_name}}",
    "check_type": "ping",
    "config": {"host": "{{hostname}}"},
    "interval": "5m",
    "severity": "critical",
}


def _renamed(sid, tags):
    return {"id": sid, "hostname": "web02.example", "name": "Web 02", "tags": tags}


def _apply(db, tid, server_id, hostname, name):
    apply_template(db, db.get(MonitorTemplate, tid), server_id, hostname, name)


def test_renamed_server_refreshes_its_tag_and_manual_assignments(db):
    tagged = _template(db, "tpl-tag", [PING_DEF])
    manual = _template(db, "tpl-man", [PING_DEF])
    _bind(db, tagged, "web")
    sync_tag_assignments(db, [_srv("srv-1", ["web"])])
    _apply(db, manual, "srv-1", "h-srv-1", "n-srv-1")

    result = sync_tag_assignments(db, [_renamed("srv-1", ["web"])])

    assert result == {"created": 0, "removed": 0, "refreshed": 2}
    rows = _assignments(db)
    for tid in (tagged, manual):
        row = rows[(tid, "srv-1")]
        assert (row.server_hostname, row.server_name) == ("web02.example", "Web 02")
        check = db.query(MonitorCheck).filter_by(template_id=tid).one()
        assert check.name == "Ping Web 02"
        assert json.loads(check.config) == {"host": "web02.example"}
    assert (rows[(tagged, "srv-1")].source, rows[(manual, "srv-1")].source) == ("tag", "manual")

    # Idempotent second run.
    assert sync_tag_assignments(db, [_renamed("srv-1", ["web"])]) == {
        "created": 0,
        "removed": 0,
        "refreshed": 0,
    }


def test_rename_keeps_a_name_the_user_changed(db):
    tid = _template(db, defs=[PING_DEF])
    _apply(db, tid, "srv-1", "h-srv-1", "n-srv-1")
    cid = db.query(MonitorCheck).one().id
    checks_router.update_check(cid, CheckUpdate(name="My ping"), db)

    assert sync_tag_assignments(db, [_renamed("srv-1", [])])["refreshed"] == 1

    check = db.get(MonitorCheck, cid)
    assert check.name == "My ping"
    assert json.loads(check.config) == {"host": "web02.example"}
    assert json.loads(check.overridden_fields) == ["name"]


@pytest.mark.parametrize(
    ("hostname", "name", "check_name", "config"),
    [
        ("old.example", "New", "Ping New", {"host": "old.example"}),
        ("new.example", "Old", "Ping Old", {"host": "new.example"}),
    ],
    ids=["name-only", "hostname-only"],
)
def test_rename_of_one_field_alone_refreshes_the_assignment(db, hostname, name, check_name, config):
    tid = _template(db, defs=[PING_DEF])
    _apply(db, tid, "srv-1", "old.example", "Old")

    inventory = [{"id": "srv-1", "hostname": hostname, "name": name, "tags": []}]
    assert sync_tag_assignments(db, inventory) == {"created": 0, "removed": 0, "refreshed": 1}

    row = _assignments(db)[(tid, "srv-1")]
    assert (row.server_hostname, row.server_name) == (hostname, name)
    check = db.query(MonitorCheck).one()
    assert check.name == check_name
    assert json.loads(check.config) == config


def test_assignment_of_a_server_missing_from_the_inventory_stays(db):
    tid = _template(db, defs=[PING_DEF])
    _apply(db, tid, "srv-9", "old.example", "Old")

    assert sync_tag_assignments(db, [_renamed("srv-1", [])]) == {
        "created": 0,
        "removed": 0,
        "refreshed": 0,
    }
    row = _assignments(db)[(tid, "srv-9")]
    assert (row.server_hostname, row.server_name) == ("old.example", "Old")
    assert json.loads(db.query(MonitorCheck).one().config) == {"host": "old.example"}


def test_unavailable_inventory_refreshes_nothing(db, monkeypatch):
    import app.tag_sync as tag_sync_mod

    tid = _template(db, defs=[PING_DEF])
    _apply(db, tid, "srv-1", "old.example", "Old")

    monkeypatch.setattr(tag_sync_mod, "fetch_inventory", lambda: None)
    assert sync_tag_assignments(db) is None
    row = _assignments(db)[(tid, "srv-1")]
    assert (row.server_hostname, row.server_name) == ("old.example", "Old")
    assert json.loads(db.query(MonitorCheck).one().config) == {"host": "old.example"}


def test_failed_refresh_keeps_the_old_names_and_the_sync_goes_on(db, monkeypatch):
    import app.tag_sync as tag_sync_mod

    tid = _template(db, defs=[PING_DEF])
    _bind(db, tid, "web")
    _apply(db, tid, "srv-1", "old.example", "Old")

    def boom(*_a, **_k):
        raise RuntimeError("sync failed")

    monkeypatch.setattr(tag_sync_mod, "sync_assignment", boom)
    # srv-2 is new: its assignment is created although the refresh of srv-1 fails.
    result = sync_tag_assignments(db, [_renamed("srv-1", ["web"]), _srv("srv-2", ["web"])])

    assert result == {"created": 1, "removed": 0, "refreshed": 0}
    rows = _assignments(db)
    assert (rows[(tid, "srv-1")].server_hostname, rows[(tid, "srv-1")].server_name) == (
        "old.example",
        "Old",
    )
    assert (tid, "srv-2") in rows


def test_failed_refresh_does_not_stop_the_refresh_of_the_next_assignment(db, monkeypatch):
    import app.tag_sync as tag_sync_mod

    tid = _template(db, defs=[PING_DEF])
    old = {"srv-1": ("old1.example", "Old 1"), "srv-2": ("old2.example", "Old 2")}
    new = {"srv-1": ("new1.example", "New 1"), "srv-2": ("new2.example", "New 2")}
    for sid, (hostname, name) in old.items():
        _apply(db, tid, sid, hostname, name)

    real_sync = tag_sync_mod.sync_assignment
    failed = []

    def fail_first(db_, template, assignment):
        if not failed:
            failed.append(assignment.server_id)
            raise RuntimeError("sync failed")
        real_sync(db_, template, assignment)

    monkeypatch.setattr(tag_sync_mod, "sync_assignment", fail_first)
    inventory = [{"id": sid, "hostname": h, "name": n, "tags": []} for sid, (h, n) in new.items()]
    assert sync_tag_assignments(db, inventory) == {"created": 0, "removed": 0, "refreshed": 1}

    # Whichever pair the sync reaches first fails and keeps its old names and
    # checks; the one after it is refreshed all the same.
    (failed_sid,) = failed
    (refreshed_sid,) = set(old) - {failed_sid}
    rows = _assignments(db)
    for sid, (hostname, name) in (
        (failed_sid, old[failed_sid]),
        (refreshed_sid, new[refreshed_sid]),
    ):
        row = rows[(tid, sid)]
        assert (row.server_hostname, row.server_name) == (hostname, name)
        check = db.query(MonitorCheck).filter_by(server_id=sid).one()
        assert check.name == f"Ping {name}"
        assert json.loads(check.config) == {"host": hostname}
