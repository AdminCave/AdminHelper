# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The monitoring migration chain, checked by pytest-alembic's four built-in
tests plus one seeded data migration.

Same shape as the server's variant. The seeded test covers b1a2c3d4e5f6, which
deletes content-identical duplicate template assignments before it can add the
unique constraint — "the lexicographically smaller id survives" is a decision
that only shows itself with duplicates in the table, and an empty database makes
its DELETE a no-op.

The fixtures live here rather than in conftest.py: alembic_engine has to point at
an EMPTY database, and env.py opens its own connection from
app.core.config.DATABASE_URL, so that attribute is patched along with it.
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

MONITORING_DIR = Path(__file__).resolve().parents[1]
DB_URL = (os.environ.get("DATABASE_URL") or "").strip()

# Nicht nur "gesetzt", sondern "zeigt auf ein Postgres": ein DATABASE_URL auf SQLite
# wuerde die Kette laufen lassen und etwas anderes pruefen, als der Test behauptet.
pytestmark = pytest.mark.skipif(
    not DB_URL.startswith("postgres"),
    reason="kein Postgres in DATABASE_URL — die Migrationskette braucht ein echtes Postgres",
)


def _normalize(url: str) -> str:
    for old in ("postgresql+psycopg2://", "postgresql://"):
        if url.startswith(old):
            return "postgresql+psycopg://" + url[len(old) :]
    return url


@pytest.fixture()
def alembic_config():
    """Where the chain lives. pytest-alembic reads this as a plain dict."""
    return {"script_location": str(MONITORING_DIR / "alembic")}


@pytest.fixture()
def alembic_engine(monkeypatch):
    """A throwaway, EMPTY database — the migrations create everything themselves."""
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


def test_duplicate_assignments_are_deduplicated_smaller_id_wins(alembic_runner, alembic_engine):
    """Two identical assignments for one (template, server): exactly one survives.

    The rows differ only in id, so the deletion is lossless — but which one stays
    is a decision the migration makes, and on an empty table nothing would test it.
    """
    alembic_runner.migrate_up_before("b1a2c3d4e5f6")

    alembic_runner.insert_into(
        "monitor_templates",
        {
            "id": "tpl-1",
            "name": "template",
            "check_definitions": "[]",
            "alert_definitions": "[]",
        },
    )
    for assignment_id in ("assign-a", "assign-b"):
        alembic_runner.insert_into(
            "monitor_template_assignments",
            {
                "id": assignment_id,
                "template_id": "tpl-1",
                "server_id": "srv-1",
                "server_hostname": "host.test",
                "server_name": "host",
            },
        )

    alembic_runner.migrate_up_one()

    with alembic_engine.connect() as conn:
        survivors = [
            row[0]
            for row in conn.execute(
                text("SELECT id FROM monitor_template_assignments ORDER BY id")
            ).all()
        ]
    assert survivors == ["assign-a"], f"expected only the smaller id to survive, got {survivors}"

    # ...and the constraint the dedupe made room for is in place.
    with alembic_engine.connect() as conn:
        constraints = [
            row[0]
            for row in conn.execute(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conrelid = 'monitor_template_assignments'::regclass"
                )
            ).all()
        ]
    assert "uq_assignment_template_server" in constraints
