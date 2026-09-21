# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The migration chain, checked by pytest-alembic's four built-in tests plus one
seeded data migration.

What the existing smoke test asserts is that `upgrade head` on an empty database
produces the models. These four add the questions it does not ask: is there
exactly one head, does every revision apply in order, do the models still match
the DDL after the full run, and — the one that actually finds things — does every
revision survive a down-and-up round trip.

The fifth test is the one no generic check can do: a data migration only shows
its behaviour when there is data. f1a2b3c4d5e6 defuses duplicate STCP visitor
ports before it can create a unique index, and "the oldest tunnel keeps the port"
is a decision that deserves a test with two tunnels in the table.

The fixtures live here rather than in conftest.py on purpose: alembic_engine has
to point at an EMPTY database (pytest-alembic builds the schema itself), while
the conftest's session-scoped pg_engine creates all tables up front. Two fixtures
of that name in one package would be a trap for whichever test picked the wrong.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

# The four built-ins are collected by being imported into this module.
from pytest_alembic.tests import (  # noqa: F401
    test_model_definitions_match_ddl,
    test_single_head_revision,
    test_up_down_consistency,
    test_upgrade,
)
from sqlalchemy import create_engine, text

SERVER_DIR = Path(__file__).resolve().parents[1]
DB_URL = (os.environ.get("DATABASE_URL") or "").strip()

pytestmark = pytest.mark.skipif(
    not DB_URL,
    reason="DATABASE_URL nicht gesetzt — die Migrationskette braucht ein echtes Postgres",
)


def _normalize(url: str) -> str:
    for old in ("postgresql+psycopg2://", "postgresql://"):
        if url.startswith(old):
            return "postgresql+psycopg://" + url[len(old) :]
    return url


@pytest.fixture()
def alembic_config():
    """Where the chain lives. pytest-alembic reads this as a plain dict."""
    return {"script_location": str(SERVER_DIR / "alembic")}


@pytest.fixture()
def alembic_engine(monkeypatch):
    """A throwaway, EMPTY database — the migrations create everything themselves.

    The engine alone is not enough: alembic/env.py reads
    app.core.config.DATABASE_URL at execution time and opens its OWN connection,
    so without patching that attribute the migrations run against the configured
    database while this engine looks at an empty one (the same trap the migration
    smoke documents).
    """
    import app.core.config as app_config

    admin = create_engine(_normalize(DB_URL), isolation_level="AUTOCOMMIT")
    dbname = f"alembic_builtin_{uuid.uuid4().hex[:8]}"
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{dbname}"'))

    url = admin.url.set(database=dbname).render_as_string(hide_password=False)
    monkeypatch.setattr(app_config, "DATABASE_URL", url)
    engine = create_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{dbname}"'))
        admin.dispose()


def test_duplicate_visitor_ports_are_defused_oldest_wins(alembic_runner, alembic_engine):
    """Two STCP tunnels on one visitor port: the older keeps it, the younger loses it.

    Without this the migration is only ever exercised against an empty table,
    where its UPDATE is a no-op and the index creation trivially succeeds — which
    is exactly the situation the migration was written to avoid (a crash-looping
    container on an image update).
    """
    alembic_runner.migrate_up_before("f1a2b3c4d5e6")

    alembic_runner.insert_into("servers", {"id": "srv-old", "name": "old", "hostname": "old.test"})
    alembic_runner.insert_into(
        "frp_server_config",
        {
            "id": "cfg-1",
            "name": "frps",
            "server_addr": "frps.example.test",
            "bind_port": 7000,
            "auth_token": "0123456789abcdef",
        },
    )
    alembic_runner.insert_into(
        "frp_tunnels",
        {
            "id": "tun-old",
            "server_id": "srv-old",
            "frp_config_id": "cfg-1",
            "name": "older",
            "tunnel_type": "stcp",
            "protocol": "tcp",
            "local_ip": "127.0.0.1",
            "local_port": 22,
            "visitor_port": 6000,
            "enabled": True,
            "created_at": "2026-01-01 00:00:00",
        },
    )
    alembic_runner.insert_into(
        "frp_tunnels",
        {
            "id": "tun-young",
            "server_id": "srv-old",
            "frp_config_id": "cfg-1",
            "name": "younger",
            "tunnel_type": "stcp",
            "protocol": "tcp",
            "local_ip": "127.0.0.1",
            "local_port": 23,
            "visitor_port": 6000,
            "enabled": True,
            "created_at": "2026-06-01 00:00:00",
        },
    )

    alembic_runner.migrate_up_one()

    with alembic_engine.connect() as conn:
        ports = dict(
            conn.execute(text("SELECT id, visitor_port FROM frp_tunnels ORDER BY id")).all()
        )
    assert ports["tun-old"] == 6000, "the older tunnel should have kept the port"
    assert ports["tun-young"] is None, "the younger tunnel should have lost it"

    # ...and the index that the dedupe made room for actually exists.
    with alembic_engine.connect() as conn:
        indexes = [
            row[0]
            for row in conn.execute(
                text("SELECT indexname FROM pg_indexes WHERE tablename = 'frp_tunnels'")
            ).all()
        ]
    assert "uq_frp_tunnel_visitor_port" in indexes
