# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Tag-sync reconciliation (T10): template→tag bindings materialize into
per-server assignments (source='tag'), stale materialized rows are removed,
manual assignments are never touched, and an unavailable hub inventory changes
nothing (None ≠ empty list)."""

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
from app.tag_sync import sync_tag_assignments


@pytest.fixture()
def db(monkeypatch):
    # apply/remove_template mutate the scheduler — neutralize like test_template_sync.
    import app.template_sync as ts

    monkeypatch.setattr(ts, "add_check", lambda *a, **k: None)
    monkeypatch.setattr(ts, "remove_check", lambda *a, **k: None)

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
    assert result == {"created": 1, "removed": 0}

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
    }


def test_removes_stale_materialized_assignment(db):
    tid = _template(db)
    _bind(db, tid, "web")
    sync_tag_assignments(db, [_srv("srv-1", ["web"])])
    assert (tid, "srv-1") in _assignments(db)

    # Server loses the tag -> materialized row disappears.
    result = sync_tag_assignments(db, [_srv("srv-1", [])])
    assert result == {"created": 0, "removed": 1}
    assert _assignments(db) == {}


def test_manual_assignment_is_never_touched(db):
    tid = _template(db)
    db.add(
        MonitorTemplateAssignment(
            id="man-1",
            template_id=tid,
            server_id="srv-1",
            server_hostname="h",
            server_name="n",
            source="manual",
        )
    )
    db.commit()

    # Desired pair already covered manually -> no duplicate, no conversion.
    _bind(db, tid, "web")
    assert sync_tag_assignments(db, [_srv("srv-1", ["web"])]) == {"created": 0, "removed": 0}
    assert _assignments(db)[(tid, "srv-1")].source == "manual"

    # Binding gone, server untagged -> the manual row still stays.
    db.query(MonitorTemplateTagAssignment).delete()
    db.commit()
    assert sync_tag_assignments(db, [_srv("srv-1", [])]) == {"created": 0, "removed": 0}
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
    assert sync_tag_assignments(db, [_srv("srv-1", ["web"])]) == {"created": 0, "removed": 0}


def test_malformed_inventory_entries_are_ignored(db):
    tid = _template(db)
    _bind(db, tid, "web")
    inventory = ["not-a-dict", {"tags": ["web"]}, _srv("srv-1", ["web"])]
    assert sync_tag_assignments(db, inventory) == {"created": 1, "removed": 0}
    assert set(_assignments(db)) == {(tid, "srv-1")}
