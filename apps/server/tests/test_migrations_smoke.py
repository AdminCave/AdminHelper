# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Migration-chain smoke test (audit T1): the rest of the suite runs against a
Base.metadata.create_all() schema, but production schemas are built by
Alembic — a broken migration (wrong column, bad backfill SQL, divergent
constraint) would pass every other test and fail only at deploy time. This
test runs the real chain against a brand-new database and asserts it produces
exactly the model metadata."""

import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text

import app.core.config as app_config
from app.core.database import Base

SERVER_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture()
def migrated_engine(pg_engine, monkeypatch):
    """A fresh database on the session's Postgres server, schema built by
    `alembic upgrade head` (deliberately NOT create_all)."""
    admin_url = pg_engine.url
    dbname = f"alembic_smoke_{uuid.uuid4().hex[:8]}"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{dbname}"'))

    smoke_url = admin_url.set(database=dbname).render_as_string(hide_password=False)

    # env.py reads app.core.config.DATABASE_URL at execution time and
    # overrides sqlalchemy.url with it — patch the attribute, not the ini.
    monkeypatch.setattr(app_config, "DATABASE_URL", smoke_url)
    cfg = Config(str(SERVER_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVER_DIR / "alembic"))
    command.upgrade(cfg, "head")

    engine = create_engine(smoke_url)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{dbname}" WITH (FORCE)'))
        admin_engine.dispose()


def test_migration_chain_matches_models(migrated_engine):
    with migrated_engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
        diff = compare_metadata(ctx, Base.metadata)
    assert diff == [], (
        "Die Alembic-Kette erzeugt ein anderes Schema als die Modelle:\n"
        + "\n".join(str(d) for d in diff)
    )


def test_migration_chain_is_reentrant(migrated_engine, monkeypatch):
    """`upgrade head` on an up-to-date schema must be a no-op, not an error."""
    smoke_url = migrated_engine.url.render_as_string(hide_password=False)
    monkeypatch.setattr(app_config, "DATABASE_URL", smoke_url)
    cfg = Config(str(SERVER_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVER_DIR / "alembic"))
    command.upgrade(cfg, "head")
