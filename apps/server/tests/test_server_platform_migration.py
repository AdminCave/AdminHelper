# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Revision 6a4e9feea1c5 maps the free-text servers.os_type to a platform value (R-1594):
Linux distribution names -> linux, win... -> windows, freebsd, opnsense, anything else ->
other, empty or blank -> NULL. The downgrade leaves the values. Same pattern as
test_server_hostname_migration.py: a throwaway database, migrated up to the revision
before, seeded, then upgraded.
"""

import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

import app.core.config as app_config

SERVER_DIR = Path(__file__).resolve().parents[1]
REVISION = "6a4e9feea1c5"
PREVIOUS = "d7b2e4c6a8f0"

# id -> (os_type before, os_type after the upgrade)
ROWS = {
    "s-ubuntu": ("Ubuntu 24.04", "linux"),
    "s-debian": ("debian", "linux"),
    "s-rocky": ("Rocky Linux 9", "linux"),
    "s-pve": ("Proxmox VE 8", "linux"),
    "s-linux": ("linux", "linux"),
    "s-win": ("Windows Server 2022", "windows"),
    "s-win-short": ("win", "windows"),
    "s-win10": ("Win10", "windows"),
    "s-ms-win": ("Microsoft Windows Server 2019", "windows"),
    "s-win-late": ("Server 2022 (Windows)", "windows"),
    "s-wind-river": ("Wind River Linux", "linux"),
    "s-rhel": ("Red Hat Enterprise Linux 9", "linux"),
    "s-rhel-short": ("rhel9", "linux"),
    "s-redis": ("Redis box", "other"),
    "s-solaris": ("Oracle Solaris 11", "other"),
    "s-archive": ("Archive box", "other"),
    "s-freebsd": ("FreeBSD 14.1", "freebsd"),
    "s-opnsense": ("OPNsense 25.1 (FreeBSD)", "opnsense"),
    "s-mac": ("macOS", "other"),
    "s-darwin": ("Darwin", "other"),
    "s-other": ("other", "other"),
    "s-empty": ("", None),
    "s-blank": ("   ", None),
    "s-null": (None, None),
}


@pytest.fixture()
def before_upgrade(pg_engine, monkeypatch):
    admin_url = pg_engine.url
    dbname = f"alembic_platform_{uuid.uuid4().hex[:8]}"
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
            for sid, (before, _) in ROWS.items():
                conn.execute(
                    text("INSERT INTO servers (id, name, os_type) VALUES (:id, :id, :os)"),
                    {"id": sid, "os": before},
                )
        yield cfg, engine
    finally:
        engine.dispose()
        with admin_engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{dbname}"'))
        admin_engine.dispose()


def _os_types(engine) -> dict[str, str | None]:
    with engine.connect() as conn:
        return dict(conn.execute(text("SELECT id, os_type FROM servers")).all())


def test_the_upgrade_maps_free_text_to_a_platform(before_upgrade):
    cfg, engine = before_upgrade

    command.upgrade(cfg, REVISION)

    assert _os_types(engine) == {sid: after for sid, (_, after) in ROWS.items()}


def test_the_downgrade_keeps_the_platform_values(before_upgrade):
    cfg, engine = before_upgrade
    command.upgrade(cfg, REVISION)

    command.downgrade(cfg, PREVIOUS)

    assert _os_types(engine) == {sid: after for sid, (_, after) in ROWS.items()}
