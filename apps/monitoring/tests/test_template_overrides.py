# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Template overrides and check tombstones (R-0420): the schema that lets the
template sync keep a user's change per field (``monitor_checks.overridden_fields``)
and keep a deleted template check deleted (``monitor_check_tombstones``).

The engine enforces foreign keys: SQLite ignores ON DELETE unless the pragma is on,
and the cascade from a deleted template to its tombstones is DB-side only (no ORM
relationship), exactly as on Postgres."""

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
