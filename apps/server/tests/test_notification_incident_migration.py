# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Revision d3b5f7a9c1e4 adds the incidents of the bell (R-1079): four tables and the
columns incident_id, notified_at, muted_until and hidden_at on notification.

The rows that exist keep their content and get notified_at = created_at, so the feed
keeps its order; the downgrade drops what the upgrade added and leaves the rows. Same
pattern as test_outbox_expiry_migration.py: a throwaway database, migrated up to the
revision before, seeded, then upgraded.
"""

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

import app.core.config as app_config

SERVER_DIR = Path(__file__).resolve().parents[1]
REVISION = "d3b5f7a9c1e4"
PREVIOUS = "c1a7e3f5b9d2"
TABLES = {
    "notification_incident",
    "notification_incident_member",
    "notification_incident_event",
    "notification_server_mute",
}
COLUMNS = {"incident_id", "notified_at", "muted_until", "hidden_at"}


@pytest.fixture()
def before_incidents(pg_engine, monkeypatch):
    admin_url = pg_engine.url
    dbname = f"alembic_incidents_{uuid.uuid4().hex[:8]}"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{dbname}"'))
    url = admin_url.set(database=dbname).render_as_string(hide_password=False)
    # env.py reads app.core.config.DATABASE_URL at execution time — patch the attribute.
    monkeypatch.setattr(app_config, "DATABASE_URL", url)
    cfg = Config(str(SERVER_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVER_DIR / "alembic"))
    engine = create_engine(url)
    try:
        command.upgrade(cfg, PREVIOUS)
        yield cfg, engine
    finally:
        engine.dispose()
        with admin_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{dbname}"'))
        admin_engine.dispose()


def _seed(engine, created: dict[int, datetime]) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, username, hashed_password, is_admin)"
                " VALUES (1, 'alice', 'x', true)"
            )
        )
        for nid, at in created.items():
            conn.execute(
                text(
                    "INSERT INTO notification (id, user_id, created_at, severity, category,"
                    " event_type, title, body, source_type, source_id, read_at)"
                    " VALUES (:id, 1, :at, 'critical', 'monitoring',"
                    " 'monitoring.check.transition', :title, 'body', 'server', 'srv-1', :read)"
                ),
                {"id": nid, "at": at, "title": f"web0{nid} down", "read": at if nid == 2 else None},
            )


def _rows(engine, columns: str = "*") -> dict:
    with engine.connect() as conn:
        return {
            row["id"]: dict(row)
            for row in conn.execute(
                text(f"SELECT {columns} FROM notification ORDER BY id")
            ).mappings()
        }


def test_old_rows_keep_their_content_and_their_order(before_incidents):
    cfg, engine = before_incidents
    now = datetime.now(timezone.utc)
    created = {1: now - timedelta(days=3), 2: now - timedelta(days=1), 3: now - timedelta(hours=1)}
    _seed(engine, created)
    before = _rows(engine)

    command.upgrade(cfg, REVISION)

    after = _rows(engine)
    for nid, row in after.items():
        assert {k: v for k, v in row.items() if k not in COLUMNS} == before[nid]
        assert row["notified_at"] == row["created_at"] == created[nid]
        assert (row["incident_id"], row["muted_until"], row["hidden_at"]) == (None, None, None)
    assert TABLES <= set(inspect(engine).get_table_names())


def test_a_new_row_is_notified_now_and_one_row_per_person_and_incident(before_incidents):
    cfg, engine = before_incidents
    _seed(engine, {})
    command.upgrade(cfg, REVISION)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO notification_incident (id, state, severity, category, event_type,"
                " title, event_count) VALUES (10, 'open', 'critical', 'monitoring',"
                " 'monitoring.check.transition', 'web01 down', 1)"
            )
        )
        for nid, incident in ((1, 10), (2, None), (3, None)):
            conn.execute(
                text(
                    "INSERT INTO notification (id, user_id, severity, category, event_type,"
                    " title, incident_id) VALUES (:id, 1, 'critical', 'monitoring',"
                    " 'monitoring.check.transition', 'web01 down', :incident)"
                ),
                {"id": nid, "incident": incident},
            )
        stamped = conn.execute(
            text("SELECT notified_at = created_at FROM notification WHERE id = 1")
        ).scalar_one()
    assert stamped, "a row written without notified_at is notified at its creation"
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO notification (id, user_id, severity, category, event_type, title,"
                " incident_id) VALUES (4, 1, 'critical', 'monitoring',"
                " 'monitoring.check.transition', 'web01 down', 10)"
            )
        )
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM notification_incident WHERE id = 10"))
    assert set(_rows(engine, "id")) == {2, 3}, "an incident takes its rows with it"


def test_downgrade_drops_what_the_upgrade_added_and_keeps_the_rows(before_incidents):
    cfg, engine = before_incidents
    now = datetime.now(timezone.utc)
    _seed(engine, {1: now - timedelta(days=2), 2: now - timedelta(minutes=5)})
    before = _rows(engine)
    command.upgrade(cfg, REVISION)

    command.downgrade(cfg, PREVIOUS)

    assert _rows(engine) == before
    assert not TABLES & set(inspect(engine).get_table_names())
    command.upgrade(cfg, REVISION)
    assert {nid: row["notified_at"] for nid, row in _rows(engine).items()} == {
        nid: row["created_at"] for nid, row in before.items()
    }
