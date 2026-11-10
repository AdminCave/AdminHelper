# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The tables of module discovery (R-1223): a finding is unique per server, module and
instance, a check from before modules stays an ordinary loud check, and deleting a
server takes its discovery and findings with it.

The migration part needs a real Postgres (DATABASE_URL), like the migration smoke
test whose throwaway-database helper it borrows; on sqlite only the model part runs.
"""

import os
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, MonitorDiscovery, MonitorFinding
from app.server_cleanup import cleanup_server

from .test_migrations_smoke import scratch_db

DB_URL = os.environ.get("DATABASE_URL", "").strip()
_BEFORE = "3c66308d11a7"
_REVISION = "b8d0f2a4c6e8"


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session
    engine.dispose()


def _finding(server_id="srv-1", module_id="paperless", instance_key="paperless"):
    return MonitorFinding(
        id=str(uuid.uuid4()),
        server_id=server_id,
        module_id=module_id,
        instance_key=instance_key,
        kind="new",
        catalog_version="sha256:" + "0" * 64,
    )


def test_finding_is_unique_per_server_module_and_instance(db):
    db.add_all(
        [
            _finding(),
            _finding(server_id="srv-2"),
            _finding(instance_key="paperless-2"),
            _finding(module_id="port", instance_key="paperless"),
        ]
    )
    db.commit()
    db.add(_finding())
    with pytest.raises(IntegrityError):
        db.commit()


def test_new_finding_starts_open_with_an_empty_summary(db):
    db.add(_finding())
    db.commit()
    row = db.query(MonitorFinding).one()
    assert (row.status, row.summary, row.decided_at) == ("open", "{}", None)
    assert row.first_seen is not None and row.last_seen is not None


def test_check_written_without_the_new_columns_is_loud_and_moduleless(db):
    # Raw SQL: the ORM would fill silent from its own default, so only an insert that
    # leaves the column out shows the server default an old writer gets.
    db.execute(
        text(
            "INSERT INTO monitor_checks (id, name, check_type, config, interval, severity)"
            " VALUES ('c1', 'C', 'ping', '{}', '5m', 'critical')"
        )
    )
    row = db.execute(
        text(
            "SELECT silent, module_id, module_instance, module_check_key"
            " FROM monitor_checks WHERE id = 'c1'"
        )
    ).one()
    assert (bool(row.silent), row.module_id, row.module_instance, row.module_check_key) == (
        False,
        None,
        None,
        None,
    )


def test_discovery_row_starts_empty_and_due(db):
    db.execute(text("INSERT INTO monitor_discovery (server_id) VALUES ('srv-1')"))
    row = db.query(MonitorDiscovery).one()
    assert (row.inventory, row.credentials) == ("{}", "{}")
    assert (row.scanned_at, row.next_scan_at, row.scan_requested_at) == (None, None, None)


def test_cleanup_server_removes_its_discovery_and_findings(db):
    # Neither table has a foreign key to the server (it lives in the server's
    # database), so cleanup_server has to drop the rows itself.
    db.add_all(
        [
            MonitorDiscovery(server_id="srv-1", inventory='{"containers": []}'),
            MonitorDiscovery(server_id="srv-2"),
            _finding("srv-1"),
            _finding("srv-1", module_id="port", instance_key="tcp/8080"),
            _finding("srv-2"),
        ]
    )
    db.commit()

    cleanup_server(db, "srv-1")

    assert [d.server_id for d in db.query(MonitorDiscovery)] == ["srv-2"]
    assert [f.server_id for f in db.query(MonitorFinding)] == ["srv-2"]


@pytest.mark.skipif(
    not DB_URL.startswith("postgres"),
    reason="kein Postgres in DATABASE_URL — die Migration braucht ein echtes Postgres",
)
def test_migration_keeps_old_checks_loud_and_downgrades_cleanly(monkeypatch):
    from alembic import command

    with scratch_db(monkeypatch, "modules") as (cfg, engine):
        command.upgrade(cfg, _BEFORE)
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO monitor_checks (id, name, check_type, config, interval, severity)"
                    " VALUES ('c1', 'C', 'ping', '{}', '5m', 'critical')"
                )
            )

        command.upgrade(cfg, _REVISION)
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT silent, module_id, module_instance, module_check_key"
                    " FROM monitor_checks WHERE id = 'c1'"
                )
            ).one()
        assert tuple(row) == (False, None, None, None)
        with engine.begin() as conn:
            insert = text(
                "INSERT INTO monitor_findings"
                " (id, server_id, module_id, instance_key, kind, catalog_version)"
                " VALUES (:id, 'srv-1', 'paperless', 'paperless', 'new', 'sha256:x')"
            )
            conn.execute(insert, {"id": "f1"})
            conn.execute(text("INSERT INTO monitor_discovery (server_id) VALUES ('srv-1')"))
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(insert, {"id": "f2"})

        command.downgrade(cfg, _BEFORE)
        insp = inspect(engine)
        assert not insp.has_table("monitor_findings")
        assert not insp.has_table("monitor_discovery")
        columns = {c["name"] for c in insp.get_columns("monitor_checks")}
        assert columns.isdisjoint({"module_id", "module_instance", "module_check_key", "silent"})
        with engine.connect() as conn:
            assert conn.execute(text("SELECT id FROM monitor_checks")).scalars().all() == ["c1"]

        command.upgrade(cfg, _REVISION)
        assert inspect(engine).has_table("monitor_findings")
