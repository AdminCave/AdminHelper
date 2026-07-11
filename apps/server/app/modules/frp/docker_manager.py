# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Writes generated FRP configs into the shared volume for the frps container."""

import logging
import os
from pathlib import Path

from app.core.config import FRP_CONFIG_DIR
from app.modules.frp.config_generator import generate_frps_toml

logger = logging.getLogger(__name__)


def write_frps_config(config, *, warn_restart: bool = False) -> Path:
    """Writes frps.toml into FRP_CONFIG_DIR. Returns the file path.

    frps has no config hot-reload, and the server container has no docker socket to trigger
    a restart. So a config change made at runtime (auth_token / dashboard credentials / ports
    via the web UI) is written to disk immediately but the RUNNING frps keeps the old config
    until a manual `docker compose restart frps` — a security-relevant inconsistency on e.g.
    token rotation. warn_restart=True surfaces that in the log; at startup frps boots straight
    from the fresh file, so no restart is needed and no warning is emitted (4.7).
    """
    toml = generate_frps_toml(config)
    path = FRP_CONFIG_DIR / "frps.toml"
    # frps.toml carries the global auth.token + dashboard password and lives in
    # the volume shared with the internet-facing frps container -> 0600
    # (umask-robust, no brief world-readable window). frps reads it as root.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, toml.encode("utf-8"))
    finally:
        os.close(fd)
    # O_CREAT leaves an existing file's mode unchanged -> enforce it explicitly.
    path.chmod(0o600)
    logger.info("frps.toml geschrieben: %s", path)
    if warn_restart:
        logger.warning(
            "frps.toml wurde zur Laufzeit geändert (%s) — das laufende frps liest die Datei "
            "NICHT automatisch neu. Für Wirksamkeit (z. B. Token-Rotation): "
            "'docker compose restart frps'.",
            path,
        )
    return path


def remove_frps_config() -> None:
    """Removes frps.toml from FRP_CONFIG_DIR."""
    path = FRP_CONFIG_DIR / "frps.toml"
    if path.exists():
        path.unlink()
        logger.info("frps.toml entfernt: %s", path)
