# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The tables of the service details (R-1226): the switch for error lines is on for a
server nobody has decided about, error lines are unique per server and unit and carry
a naive UTC time, and deleting a server takes its inventory and error lines with it.

The migration part needs a real Postgres (DATABASE_URL), like the migration smoke
test whose throwaway-database helper it borrows; on sqlite only the model part runs.
"""

import os
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.time import utcnow_naive
from app.models import Base, MonitorServiceInventory, MonitorServiceLog
from app.server_cleanup import cleanup_server

from .test_migrations_smoke import scratch_db

DB_URL = os.environ.get("DATABASE_URL", "").strip()
_BEFORE = "b8d0f2a4c6e8"
_REVISION = "c1e3a5b7d9f0"


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        yield session
    engine.dispose()


def _assert_naive_utc_now(value: datetime) -> None:
    assert value.tzinfo is None
    assert abs(value - utcnow_naive()) < timedelta(minutes=1), value


def test_inventory_row_written_without_the_switch_has_it_on(db):
    # Raw SQL: the ORM would fill log_lines from its own default, so only an insert
    # that leaves the column out shows the server default.
    db.execute(text("INSERT INTO monitor_service_inventory (server_id) VALUES ('srv-1')"))
    row = db.query(MonitorServiceInventory).one()
    assert (row.log_lines, row.services, row.reported_at) == (True, "[]", None)


def test_inventory_row_from_the_orm_has_the_switch_on(db):
    db.add(MonitorServiceInventory(server_id="srv-1"))
    db.commit()
    assert db.query(MonitorServiceInventory).one().log_lines is True


def test_error_lines_start_empty_with_a_naive_utc_time(db):
    db.execute(
        text("INSERT INTO monitor_service_logs (server_id, unit) VALUES ('srv-1', 'nginx.service')")
    )
    row = db.query(MonitorServiceLog).one()
    assert (row.lines, row.since) == ("[]", None)
    _assert_naive_utc_now(row.collected_at)


def test_error_lines_are_unique_per_server_and_unit(db):
    db.add_all(
        [
            MonitorServiceLog(server_id="srv-1", unit="nginx.service"),
            MonitorServiceLog(server_id="srv-1", unit="cron.service"),
            MonitorServiceLog(server_id="srv-2", unit="nginx.service"),
        ]
    )
    db.commit()
    db.add(MonitorServiceLog(server_id="srv-1", unit="nginx.service"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_cleanup_server_removes_its_inventory_and_error_lines(db):
    # Neither table has a foreign key to the server (it lives in the server's
    # database), so cleanup_server has to drop the rows itself.
    db.add_all(
        [
            MonitorServiceInventory(server_id="srv-1", services='[{"unit": "nginx.service"}]'),
            MonitorServiceInventory(server_id="srv-2", log_lines=False),
            MonitorServiceLog(server_id="srv-1", unit="nginx.service", lines='["boom"]'),
            MonitorServiceLog(server_id="srv-1", unit="cron.service"),
            MonitorServiceLog(server_id="srv-2", unit="nginx.service"),
        ]
    )
    db.commit()

    cleanup_server(db, "srv-1")

    assert [r.server_id for r in db.query(MonitorServiceInventory)] == ["srv-2"]
    assert [(r.server_id, r.unit) for r in db.query(MonitorServiceLog)] == [
        ("srv-2", "nginx.service")
    ]


@pytest.mark.skipif(
    not DB_URL.startswith("postgres"),
    reason="kein Postgres in DATABASE_URL — die Migration braucht ein echtes Postgres",
)
def test_migration_adds_both_tables_and_downgrades_cleanly(monkeypatch):
    from alembic import command

    with scratch_db(monkeypatch, "services") as (cfg, engine):
        command.upgrade(cfg, _BEFORE)
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO monitor_discovery (server_id) VALUES ('srv-1')"))

        command.upgrade(cfg, _REVISION)
        with engine.begin() as conn:
            # The stack's sessions run in Europe/Berlin: the default must still be UTC.
            conn.execute(text("SET TIME ZONE 'Europe/Berlin'"))
            conn.execute(text("INSERT INTO monitor_service_inventory (server_id) VALUES ('srv-1')"))
            conn.execute(
                text(
                    "INSERT INTO monitor_service_logs (server_id, unit)"
                    " VALUES ('srv-1', 'nginx.service')"
                )
            )
        with engine.connect() as conn:
            inventory = conn.execute(
                text("SELECT log_lines, services, reported_at FROM monitor_service_inventory")
            ).one()
            log = conn.execute(
                text("SELECT lines, since, collected_at FROM monitor_service_logs")
            ).one()
        assert tuple(inventory) == (True, "[]", None)
        assert (log.lines, log.since) == ("[]", None)
        _assert_naive_utc_now(log.collected_at)
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO monitor_service_logs (server_id, unit)"
                    " VALUES ('srv-1', 'nginx.service')"
                )
            )

        command.downgrade(cfg, _BEFORE)
        insp = inspect(engine)
        assert not insp.has_table("monitor_service_inventory")
        assert not insp.has_table("monitor_service_logs")
        # Paired with the two negatives: the downgrade dropped only its own tables.
        assert insp.has_table("monitor_discovery")
        with engine.connect() as conn:
            assert conn.execute(
                text("SELECT server_id FROM monitor_discovery")
            ).scalars().all() == ["srv-1"]

        command.upgrade(cfg, _REVISION)
        assert inspect(engine).has_table("monitor_service_logs")
