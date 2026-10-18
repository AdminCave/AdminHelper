# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Revision c3e5a7b9d1f2 lets the stale outbox backlog expire (R-0411).

From v0.38.0 on the scheduler process ran no DB job, so the outbox drain never
delivered and pending e-mails piled up for months. Once the scheduler works again
its first drain would send that backlog to the addresses stored back then. The
revision marks pending entries older than seven days `failed` — the drain's own
terminal state, which it never picks up again — and leaves everything else alone.

Same pattern as the data-migration tests in test_migrations_smoke.py: a throwaway
database on the session's Postgres, migrated up to the revision before, seeded, then
upgraded. pg_engine falls back to testcontainers, so this does not skip.
"""

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

import app.core.config as app_config

SERVER_DIR = Path(__file__).resolve().parents[1]
REVISION = "c3e5a7b9d1f2"
PREVIOUS = "3f9c2a7e5b1d"


@pytest.fixture()
def before_expiry(pg_engine, monkeypatch):
    """A fresh database migrated up to the revision before the expiry, with the
    alembic config that continues from there."""
    # libpq sends PGTZ on every new connection, Alembic's included. At UTC+14 a cutoff
    # that loses its zone on the way is read as session-local time and lands 14 h beside
    # the real one; in a UTC session (the CI database) the same mistake would pass.
    monkeypatch.setenv("PGTZ", "Pacific/Kiritimati")
    admin_url = pg_engine.url
    dbname = f"alembic_outbox_{uuid.uuid4().hex[:8]}"
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


def _rows(engine, table: str) -> dict:
    with engine.connect() as conn:
        return {
            row["id"]: dict(row)
            for row in conn.execute(text(f"SELECT * FROM {table} ORDER BY id")).mappings()
        }


def test_only_pending_entries_older_than_seven_days_expire(before_expiry):
    cfg, engine = before_expiry
    now = datetime.now(timezone.utc)
    week = timedelta(days=7)
    # id: (status, attempts, created_at, last_error, sent_at)
    seed = {
        1: ("pending", 2, now - timedelta(days=8), "SMTP_HOST is not set", None),
        2: ("pending", 0, now - timedelta(days=1), None, None),
        3: ("sent", 1, now - timedelta(days=8), None, now - timedelta(days=8)),
        4: ("failed", 5, now - timedelta(days=8), "connection refused", None),
        # One hour either side of the cutoff: a cutoff shifted by the session zone
        # (14 h here) puts one of the two on the wrong side.
        5: ("pending", 0, now - week - timedelta(hours=1), None, None),
        6: ("pending", 0, now - week + timedelta(hours=1), None, None),
    }
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users (id, username, hashed_password, is_admin)"
                " VALUES (1, 'alice', 'x', false)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO notification (id, user_id, created_at, severity, category,"
                " event_type, title) VALUES (1, 1, :at, 'critical', 'monitoring',"
                " 'monitoring.check.transition', 'web01 down')"
            ),
            {"at": now - timedelta(days=8)},
        )
        for oid, (status, attempts, created, error, sent) in seed.items():
            conn.execute(
                text(
                    "INSERT INTO notification_outbox (id, notification_id, user_id, channel,"
                    " address, status, attempts, last_error, created_at, sent_at)"
                    " VALUES (:id, 1, 1, 'email', 'alice@example.test', :status, :attempts,"
                    " :error, :created, :sent)"
                ),
                {
                    "id": oid,
                    "status": status,
                    "attempts": attempts,
                    "error": error,
                    "created": created,
                    "sent": sent,
                },
            )
        zone = conn.execute(text("SHOW TimeZone")).scalar_one()
    assert zone == "Pacific/Kiritimati", "the session did not run far from UTC"
    outbox_before = _rows(engine, "notification_outbox")
    bell_before = _rows(engine, "notification")

    command.upgrade(cfg, REVISION)

    outbox_after = _rows(engine, "notification_outbox")
    expired = {oid for oid, row in outbox_after.items() if row != outbox_before[oid]}
    assert expired == {1, 5}, "exactly the pending entries older than seven days change"
    for oid in expired:
        assert outbox_after[oid]["status"] == "failed"
        assert outbox_after[oid]["last_error"] == "expired before delivery"
    # Everything else is untouched, attempts of the expired entries included.
    for oid, row in outbox_after.items():
        ignore = {"status", "last_error"} if oid in expired else set()
        assert {k: v for k, v in row.items() if k not in ignore} == {
            k: v for k, v in outbox_before[oid].items() if k not in ignore
        }, f"outbox entry {oid} changed beyond its status"
    assert _rows(engine, "notification") == bell_before, "the bell feed stays as it was"


def test_an_empty_outbox_upgrades(before_expiry):
    cfg, engine = before_expiry

    command.upgrade(cfg, REVISION)

    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        count = conn.execute(text("SELECT count(*) FROM notification_outbox")).scalar_one()
    assert version == REVISION
    assert count == 0
