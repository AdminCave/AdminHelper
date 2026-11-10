# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Revision c2d4e6f8a0b2 (R-1210, Kevin 2026-11-09 4a): a connection of a server keeps only
its own text. A name that only copied the server's name or address, or the name of the
tunnel leading to it (also as "{tunnel} (via FRP)"), becomes ''; every other name stays,
and so does every connection without a server. The downgrade writes the display name into
the emptied rows. Same pattern as test_server_hostname_migration.py."""

import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

import app.core.config as app_config

SERVER_DIR = Path(__file__).resolve().parents[1]
REVISION = "c2d4e6f8a0b2"
PREVIOUS = "b1c3d5e7f9a1"

# id -> (server, kind, name before, name after the upgrade)
ROWS = {
    "c-server": ("s-1", "ssh", "web01.kunde.example", ""),
    "c-case": ("s-1", "rdp", " WEB01.Kunde.Example ", ""),
    "c-address": ("s-2", "ssh", "192.0.2.10", ""),
    "c-auto": ("s-1", "ssh", "web01-ssh (via FRP)", ""),
    "c-tunnel": ("s-1", "web", "web01-web", ""),
    "c-own": ("s-1", "ssh", "root on web01", "root on web01"),
    "c-other-tunnel": ("s-2", "ssh", "web01-ssh (via FRP)", "web01-ssh (via FRP)"),
    "c-free": (None, "ssh", "web01.kunde.example", "web01.kunde.example"),
}


@pytest.fixture()
def before_upgrade(pg_engine, monkeypatch):
    admin_url = pg_engine.url
    dbname = f"alembic_connnames_{uuid.uuid4().hex[:8]}"
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
            for cid, (server, kind, name, _) in ROWS.items():
                conn.execute(
                    text(
                        "INSERT INTO connections (id, name, kind, server_id)"
                        " VALUES (:id, :name, :kind, :server)"
                    ),
                    {"id": cid, "name": name, "kind": kind, "server": server},
                )
            conn.execute(
                text(
                    "INSERT INTO frp_server_config (id, name, server_addr, auth_token)"
                    " VALUES ('cfg', 'frps', 'frps.example', 'token')"
                )
            )
            for tid, name, connection in (
                ("t-ssh", "web01-ssh", "c-auto"),
                ("t-web", "web01-web", "c-tunnel"),
            ):
                conn.execute(
                    text(
                        "INSERT INTO frp_tunnels (id, server_id, frp_config_id, name,"
                        " tunnel_type, protocol, local_port, connection_id)"
                        " VALUES (:id, 's-1', 'cfg', :name, 'stcp', 'ssh', 22, :conn)"
                    ),
                    {"id": tid, "name": name, "conn": connection},
                )
        yield cfg, engine
    finally:
        engine.dispose()
        with admin_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{dbname}"'))
        admin_engine.dispose()


def _names(engine) -> dict[str, str]:
    with engine.connect() as conn:
        return dict(conn.execute(text("SELECT id, name FROM connections")).all())


def test_copies_become_empty_own_texts_and_free_names_stay(before_upgrade):
    cfg, engine = before_upgrade

    command.upgrade(cfg, REVISION)

    assert _names(engine) == {cid: after for cid, (_, _, _, after) in ROWS.items()}


def test_the_downgrade_writes_the_display_name_into_the_emptied_rows(before_upgrade):
    cfg, engine = before_upgrade
    command.upgrade(cfg, REVISION)

    command.downgrade(cfg, PREVIOUS)

    names = _names(engine)
    assert names["c-server"] == "web01.kunde.example · SSH"
    assert names["c-case"] == "web01.kunde.example · RDP"
    assert names["c-address"] == "mail · SSH"
    assert names["c-auto"] == "web01.kunde.example · SSH (FRP)"
    assert names["c-tunnel"] == "web01.kunde.example · Web (FRP)"
    assert names["c-own"] == "root on web01"
    assert names["c-free"] == "web01.kunde.example"
