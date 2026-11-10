# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Revision b1c3d5e7f9a1 makes servers.hostname nullable (R-1210): NULL means the address
follows the server's name. A stored hostname that only repeats the name (case and outer
whitespace aside) or is empty becomes NULL; an own address stays. The downgrade writes the
name back into every NULL. Same pattern as test_notification_incident_migration.py: a
throwaway database, migrated up to the revision before, seeded, then upgraded.
"""

import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

import app.core.config as app_config

SERVER_DIR = Path(__file__).resolve().parents[1]
REVISION = "b1c3d5e7f9a1"
PREVIOUS = "a4b6c8d0e2f4"

# id -> (name, hostname before, hostname after the upgrade)
ROWS = {
    "s-same": ("web01.kunde.example", "web01.kunde.example", None),
    "s-case": ("Web01.Kunde.Example", " web01.kunde.example ", None),
    "s-empty": ("db01", "", None),
    "s-blank": ("db02", "   ", None),
    "s-ip": ("mail.kunde.example", "192.0.2.10", "192.0.2.10"),
    "s-other": ("web02", "web02.intern.example", "web02.intern.example"),
}


@pytest.fixture()
def before_upgrade(pg_engine, monkeypatch):
    admin_url = pg_engine.url
    dbname = f"alembic_hostname_{uuid.uuid4().hex[:8]}"
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
            for sid, (name, hostname, _) in ROWS.items():
                conn.execute(
                    text("INSERT INTO servers (id, name, hostname) VALUES (:id, :name, :host)"),
                    {"id": sid, "name": name, "host": hostname},
                )
        yield cfg, engine
    finally:
        engine.dispose()
        with admin_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{dbname}"'))
        admin_engine.dispose()


def _hostnames(engine) -> dict[str, str | None]:
    with engine.connect() as conn:
        return dict(conn.execute(text("SELECT id, hostname FROM servers")).all())


def test_a_hostname_that_repeats_the_name_becomes_null_an_own_address_stays(before_upgrade):
    cfg, engine = before_upgrade

    command.upgrade(cfg, REVISION)

    assert _hostnames(engine) == {sid: after for sid, (_, _, after) in ROWS.items()}
    column = {c["name"]: c for c in inspect(engine).get_columns("servers")}["hostname"]
    assert column["nullable"] is True


def test_the_downgrade_writes_the_name_into_every_null(before_upgrade):
    cfg, engine = before_upgrade
    command.upgrade(cfg, REVISION)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO servers (id, name) VALUES ('s-new', 'new.kunde.example')"))

    command.downgrade(cfg, PREVIOUS)

    expected = {sid: after or name for sid, (name, _, after) in ROWS.items()}
    expected["s-new"] = "new.kunde.example"
    assert _hostnames(engine) == expected
    column = {c["name"]: c for c in inspect(engine).get_columns("servers")}["hostname"]
    assert column["nullable"] is False
