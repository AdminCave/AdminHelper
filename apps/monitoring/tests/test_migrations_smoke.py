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


@pytest.fixture()
def migrated_engine(monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    import app.core.config as app_config

    admin_engine = create_engine(_normalize(DB_URL), isolation_level="AUTOCOMMIT")
    dbname = f"alembic_smoke_{uuid.uuid4().hex[:8]}"
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{dbname}"'))

    smoke_url = admin_engine.url.set(database=dbname).render_as_string(hide_password=False)

    # env.py reads app.core.config.DATABASE_URL at execution time and
    # overrides sqlalchemy.url with it — patch the attribute, not the ini.
    monkeypatch.setattr(app_config, "DATABASE_URL", smoke_url)
    cfg = Config(str(MONITORING_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(MONITORING_DIR / "alembic"))
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
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext

    from app.models import Base

    with migrated_engine.connect() as conn:
        ctx = MigrationContext.configure(conn)
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
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    import app.core.config as app_config

    admin_engine = create_engine(_normalize(DB_URL), isolation_level="AUTOCOMMIT")
    dbname = f"alembic_dedupe_{uuid.uuid4().hex[:8]}"
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{dbname}"'))
    smoke_url = admin_engine.url.set(database=dbname).render_as_string(hide_password=False)
    monkeypatch.setattr(app_config, "DATABASE_URL", smoke_url)
    cfg = Config(str(MONITORING_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(MONITORING_DIR / "alembic"))
    engine = create_engine(smoke_url)
    try:
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
    finally:
        engine.dispose()
        with admin_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{dbname}" WITH (FORCE)'))
        admin_engine.dispose()
