# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Migration-chain smoke test (audit T1), monitoring variant.

The monitoring suite is deliberately DB-free, so this test only runs when a
Postgres is available via DATABASE_URL (CI provides a service container; local
runs skip). It builds a fresh database via `alembic upgrade head` and asserts
the result matches the models exactly."""

import os
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

DB_URL = os.environ.get("DATABASE_URL", "").strip()

pytestmark = pytest.mark.skipif(
    not DB_URL,
    reason="DATABASE_URL nicht gesetzt — Migrations-Smoke laeuft in CI (Postgres-Service)",
)

MONITORING_DIR = Path(__file__).resolve().parents[1]


def _normalize(url: str) -> str:
    for old in ("postgresql+psycopg2://", "postgresql://"):
        if url.startswith(old):
            return "postgresql+psycopg://" + url[len(old) :]
    return url


@contextmanager
def scratch_db(monkeypatch, tag: str):
    """A throwaway database plus a ready alembic Config, yielded as (cfg, engine).

    Every test here needs the same four steps — CREATE DATABASE, point
    app.core.config.DATABASE_URL at it (env.py reads that attribute at
    execution time, so patching the ini would not take), build the Config, and
    DROP it afterwards.

    The caller decides how far to migrate: `command.upgrade(cfg, "head")` for
    the parity check, or a specific revision to plant data at an intermediate
    state before applying the next one.
    """
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    import app.core.config as app_config

    admin_engine = create_engine(_normalize(DB_URL), isolation_level="AUTOCOMMIT")
    dbname = f"alembic_{tag}_{uuid.uuid4().hex[:8]}"
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{dbname}"'))

    smoke_url = admin_engine.url.set(database=dbname).render_as_string(hide_password=False)
    monkeypatch.setattr(app_config, "DATABASE_URL", smoke_url)
    cfg = Config(str(MONITORING_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(MONITORING_DIR / "alembic"))

    engine = create_engine(smoke_url)
    try:
        yield cfg, engine
    finally:
        engine.dispose()
        with admin_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{dbname}" WITH (FORCE)'))
        admin_engine.dispose()


@pytest.fixture()
def migrated_engine(monkeypatch):
    from alembic import command

    with scratch_db(monkeypatch, "smoke") as (cfg, engine):
        command.upgrade(cfg, "head")
        yield engine


def test_migration_chain_matches_models(migrated_engine):
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.models import Base

    with migrated_engine.connect() as conn:
        # Match env.py's autogenerate context (compare_server_default=True) so a model that loses or
        # changes a server_default no longer passes silently (6.151).
        ctx = MigrationContext.configure(conn, opts={"compare_server_default": True})
        diff = compare_metadata(ctx, Base.metadata)
    assert diff == [], (
        "Die Alembic-Kette erzeugt ein anderes Schema als die Modelle:\n"
        + "\n".join(str(d) for d in diff)
    )


def test_uniq_template_assignment_dedupes_before_constraint(monkeypatch):
    # 4.44: the migration must delete content-identical duplicate (template_id, server_id) rows
    # before adding the unique constraint — else ADD CONSTRAINT fails and the container
    # crash-loops on boot. Migrate to just before it, plant duplicates, then apply it.
    from alembic import command
    from sqlalchemy import text

    with scratch_db(monkeypatch, "dedupe") as (cfg, engine):
        command.upgrade(cfg, "c85e6dacd792")  # just before the uniq-constraint migration
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO monitor_templates (id, name, check_definitions, alert_definitions)"
                    " VALUES ('t1', 'T', '[]', '[]')"
                )
            )
            for aid in ("a1", "a2"):
                conn.execute(
                    text(
                        "INSERT INTO monitor_template_assignments"
                        " (id, template_id, server_id, server_hostname, server_name)"
                        f" VALUES ('{aid}', 't1', 's1', 'h', 'n')"
                    )
                )
        command.upgrade(cfg, "b1a2c3d4e5f6")  # must dedupe + add the constraint without crashing
        with engine.connect() as conn:
            n = conn.execute(text("SELECT count(*) FROM monitor_template_assignments")).scalar()
        assert n == 1  # exactly one row per (template_id, server_id) pair survived


def test_notified_status_backfill_marks_existing_states_as_reported(monkeypatch):
    # alert-sent-state T1: the upgrade must backfill notified_status = status —
    # without it every pre-existing warning/critical state would count as a
    # discrepancy and trigger a catch-up notification storm on deploy.
    from alembic import command
    from sqlalchemy import text

    with scratch_db(monkeypatch, "sentstate") as (cfg, engine):
        command.upgrade(cfg, "b7d9f1a3c5e7")  # just before the sent-state migration
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO monitor_checks"
                    " (id, name, check_type, config, interval, severity)"
                    " VALUES ('c1', 'C', 'ping', '{}', '5m', 'critical')"
                )
            )
            conn.execute(
                text("INSERT INTO monitor_states (check_id, status) VALUES ('c1', 'critical')")
            )
        # A check standing on unknown at deploy time: the last SENT status
        # comes from the alert log (c2 -> critical, recovery after the deploy
        # must not be swallowed); without a log entry it stays unknown (c3).
        with engine.begin() as conn:
            for cid in ("c2", "c3"):
                conn.execute(
                    text(
                        "INSERT INTO monitor_checks"
                        " (id, name, check_type, config, interval, severity)"
                        f" VALUES ('{cid}', 'C', 'ping', '{{}}', '5m', 'critical')"
                    )
                )
                conn.execute(
                    text(
                        f"INSERT INTO monitor_states (check_id, status) VALUES ('{cid}', 'unknown')"
                    )
                )
            conn.execute(
                text(
                    "INSERT INTO monitor_alert_rules (id, name, channel, channel_config)"
                    " VALUES ('r1', 'R', 'webhook', '{}')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO monitor_alert_log"
                    " (alert_rule_id, check_id, old_status, new_status, sent_at, success)"
                    " VALUES ('r1', 'c2', 'ok', 'critical', '2026-01-01 00:00:00', true)"
                )
            )
        command.upgrade(cfg, "c1d3e5f7a9b1")
        with engine.connect() as conn:
            rows = dict(
                conn.execute(
                    text("SELECT check_id, notified_status FROM monitor_states")
                ).fetchall()
            )
        assert rows == {"c1": "critical", "c2": "critical", "c3": "unknown"}
