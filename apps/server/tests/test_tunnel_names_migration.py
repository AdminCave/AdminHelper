# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Revision d3e5f7a9b1c3 (R-1210, Kevin 2026-11-09 4a): frp_tunnels.name holds the own text of
the display name and is no longer unique. A name that only copied the server (its name, its
address, "{server}-{protocol}" or "{server}-{tunnel_type}") becomes ''; every other name stays.
The downgrade gives the emptied rows the pattern back, appends the ID to every name used more
than once and restores the unique constraint. Same pattern as test_server_hostname_migration.py.
"""

import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

import app.core.config as app_config

SERVER_DIR = Path(__file__).resolve().parents[1]
REVISION = "d3e5f7a9b1c3"
PREVIOUS = "c2d4e6f8a0b2"

# id -> (server, protocol, tunnel_type, name before, name after the upgrade)
ROWS = {
    "t-pattern": ("s-1", "ssh", "stcp", "web01.kunde.example-ssh", ""),
    "t-type": ("s-1", "web", "https", "WEB01.kunde.example-https", ""),
    "t-server": ("s-1", "rdp", "stcp", "web01.kunde.example", ""),
    "t-address": ("s-2", "ssh", "stcp", "192.0.2.10", ""),
    "t-own": ("s-1", "web", "stcp", "admin-ui", "admin-ui"),
    "t-foreign": ("s-2", "ssh", "stcp", "web01.kunde.example-rdp", "web01.kunde.example-rdp"),
}


@pytest.fixture()
def before_upgrade(pg_engine, monkeypatch):
    admin_url = pg_engine.url
    dbname = f"alembic_tunnames_{uuid.uuid4().hex[:8]}"
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
                text(
                    "INSERT INTO servers (id, name, hostname) VALUES"
                    " ('s-1', 'web01.kunde.example', NULL), ('s-2', 'mail', '192.0.2.10')"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO frp_server_config (id, name, server_addr, auth_token)"
                    " VALUES ('cfg', 'frps', 'frps.example', 'token')"
                )
            )
            for tid, (server, protocol, tunnel_type, name, _) in ROWS.items():
                conn.execute(
                    text(
                        "INSERT INTO frp_tunnels (id, server_id, frp_config_id, name,"
                        " tunnel_type, protocol, local_port)"
                        " VALUES (:id, :server, 'cfg', :name, :type, :protocol, 22)"
                    ),
                    {
                        "id": tid,
                        "server": server,
                        "name": name,
                        "type": tunnel_type,
                        "protocol": protocol,
                    },
                )
        yield cfg, engine
    finally:
        engine.dispose()
        with admin_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{dbname}"'))
        admin_engine.dispose()


def _names(engine) -> dict[str, str]:
    with engine.connect() as conn:
        return dict(conn.execute(text("SELECT id, name FROM frp_tunnels")).all())


def _unique_on_name(engine) -> bool:
    return any(
        c["column_names"] == ["name"] for c in inspect(engine).get_unique_constraints("frp_tunnels")
    )


def test_copies_become_empty_and_names_may_repeat(before_upgrade):
    cfg, engine = before_upgrade
    assert _unique_on_name(engine)

    command.upgrade(cfg, REVISION)

    assert _names(engine) == {tid: after for tid, (*_, after) in ROWS.items()}
    assert not _unique_on_name(engine)
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE frp_tunnels SET name = 'same' WHERE id IN ('t-own', 't-foreign')")
        )


def test_the_downgrade_restores_unique_names(before_upgrade):
    cfg, engine = before_upgrade
    command.upgrade(cfg, REVISION)
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE frp_tunnels SET name = 'same' WHERE id IN ('t-own', 't-foreign')")
        )

    command.downgrade(cfg, PREVIOUS)

    names = _names(engine)
    assert names["t-pattern"] == "web01.kunde.example-ssh"
    assert names["t-type"] == "web01.kunde.example-web"
    assert names["t-address"] == "mail-ssh"
    assert (names["t-own"], names["t-foreign"]) == ("same-t-own", "same-t-foreign")
    assert len(set(names.values())) == len(names)
    assert _unique_on_name(engine)
