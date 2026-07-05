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


def test_rename_frp_provision_tokens_preserves_rows(pg_engine, monkeypatch):
    # 4.62: op.rename_table must carry the rows over — the old create_table + drop_table silently
    # destroyed every pending provision token. Migrate to just before the rename, plant a token,
    # apply the rename, and assert the token survived under the new table name.
    admin_url = pg_engine.url
    dbname = f"alembic_rename_{uuid.uuid4().hex[:8]}"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{dbname}"'))
    smoke_url = admin_url.set(database=dbname).render_as_string(hide_password=False)
    monkeypatch.setattr(app_config, "DATABASE_URL", smoke_url)
    cfg = Config(str(SERVER_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVER_DIR / "alembic"))
    engine = create_engine(smoke_url)
    try:
        command.upgrade(cfg, "1d8276d3aa26")  # the down_revision, just before the rename
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO servers (id, name, hostname) VALUES ('s1', 'S', 'h')"))
            conn.execute(
                text(
                    "INSERT INTO frp_provision_tokens (id, server_id, hashed_token, expires_at)"
                    " VALUES ('t1', 's1', 'hash', '2099-01-01 00:00:00')"
                )
            )
        command.upgrade(cfg, "0494a8f377ef")  # the rename — must preserve the row
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT server_id, hashed_token FROM provision_tokens WHERE id = 't1'")
            ).first()
        assert row is not None, "das Provision-Token muss das Rename ueberleben"
        assert row[0] == "s1" and row[1] == "hash"
    finally:
        engine.dispose()
        with admin_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{dbname}" WITH (FORCE)'))
        admin_engine.dispose()


def test_uniq_visitor_port_frees_younger_duplicate_instead_of_deleting(pg_engine, monkeypatch):
    # 4.64: pre-existing STCP visitor_port duplicates (a real race artifact) must be defused
    # before CREATE UNIQUE INDEX — per port the OLDEST tunnel keeps it, younger ones lose it to
    # NULL. Unlike the content-identical template-assignment dedupe the ROW is preserved (a
    # distinct tunnel), only its port is freed. Migrate to just before the index, plant two stcp
    # tunnels sharing a port, apply the migration.
    admin_url = pg_engine.url
    dbname = f"alembic_vport_{uuid.uuid4().hex[:8]}"
    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{dbname}"'))
    smoke_url = admin_url.set(database=dbname).render_as_string(hide_password=False)
    monkeypatch.setattr(app_config, "DATABASE_URL", smoke_url)
    cfg = Config(str(SERVER_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVER_DIR / "alembic"))
    engine = create_engine(smoke_url)
    try:
        command.upgrade(cfg, "e7b3c1a9d2f4")  # the down_revision, just before the unique index
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO servers (id, name, hostname) VALUES ('s1', 'S', 'h')"))
            conn.execute(
                text(
                    "INSERT INTO frp_server_config (id, name, server_addr, auth_token)"
                    " VALUES ('c1', 'C', 'frps', 'tok')"
                )
            )
            for tid, created in (("t_old", "2026-01-01"), ("t_new", "2026-02-01")):
                conn.execute(
                    text(
                        "INSERT INTO frp_tunnels (id, server_id, frp_config_id, name, tunnel_type,"
                        " protocol, local_port, visitor_port, created_at)"
                        f" VALUES ('{tid}', 's1', 'c1', '{tid}', 'stcp', 'ssh', 22, 7000,"
                        f" '{created} 00:00:00')"
                    )
                )
        command.upgrade(cfg, "f1a2b3c4d5e6")  # dedupe (NULL the younger) + index — must not crash
        with engine.connect() as conn:
            rows = dict(
                conn.execute(text("SELECT id, visitor_port FROM frp_tunnels ORDER BY id")).all()
            )
        assert rows["t_old"] == 7000, "der aeltere Tunnel behaelt seinen visitor_port"
        assert rows["t_new"] is None, "der juengere verliert den Port (NULL), bleibt aber erhalten"
    finally:
        engine.dispose()
        with admin_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{dbname}" WITH (FORCE)'))
        admin_engine.dispose()
