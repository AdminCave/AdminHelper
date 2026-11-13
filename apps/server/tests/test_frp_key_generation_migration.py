# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Revision b7c9d1e3f5a7 adds servers.frp_key_generation (R-1316): every existing server
gets 0, the generation of the key it had before; the downgrade drops the column. Same
pattern as test_server_hostname_migration.py: a throwaway database, migrated up to the
revision before, seeded, then upgraded.
"""

import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

import app.core.config as app_config

SERVER_DIR = Path(__file__).resolve().parents[1]
REVISION = "b7c9d1e3f5a7"
PREVIOUS = "d3e5f7a9b1c3"


@pytest.fixture()
def before_upgrade(pg_engine, monkeypatch):
    admin_url = pg_engine.url
    dbname = f"alembic_frpkeygen_{uuid.uuid4().hex[:8]}"
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
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO servers (id, name) VALUES ('s-old', 'web01.kunde.example')")
            )
        yield cfg, engine
    finally:
        engine.dispose()
        with admin_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{dbname}"'))
        admin_engine.dispose()


def _columns(engine) -> dict:
    return {c["name"]: c for c in inspect(engine).get_columns("servers")}


def test_an_existing_server_gets_generation_0_and_new_rows_default_to_it(before_upgrade):
    cfg, engine = before_upgrade

    command.upgrade(cfg, REVISION)

    with engine.begin() as conn:
        conn.execute(text("INSERT INTO servers (id, name) VALUES ('s-new', 'db01')"))
        rows = dict(conn.execute(text("SELECT id, frp_key_generation FROM servers")).all())
    assert rows == {"s-old": 0, "s-new": 0}
    assert _columns(engine)["frp_key_generation"]["nullable"] is False


def test_the_downgrade_drops_the_column_and_keeps_the_servers(before_upgrade):
    cfg, engine = before_upgrade
    command.upgrade(cfg, REVISION)

    command.downgrade(cfg, PREVIOUS)

    assert "frp_key_generation" not in _columns(engine)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT id FROM servers")).scalars().all() == ["s-old"]
