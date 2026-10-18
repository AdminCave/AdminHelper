# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Writes generated FRP configs into the shared volume for the frps container."""

import logging
import os
import tempfile
from pathlib import Path

from app.core.config import FRP_CONFIG_DIR
from app.modules.frp.config_generator import generate_frps_toml

logger = logging.getLogger(__name__)


def write_frps_config(config, *, warn_restart: bool = False) -> Path:
    """Writes frps.toml into FRP_CONFIG_DIR. Returns the file path.

    The file is swapped in atomically (temp file in the same directory, fsync, os.replace):
    frps watches it and picks a change up by itself, so it must never see an empty or
    half-written file. warn_restart=True marks a change made at runtime (create/update via
    the web UI) and logs that frps applies it; at startup frps boots straight from the
    fresh file, so nothing is logged about it.
    """
    toml = generate_frps_toml(config)
    path = FRP_CONFIG_DIR / "frps.toml"
    # frps.toml carries the global auth.token + dashboard password and lives in
    # the volume shared with the internet-facing frps container -> 0600
    # (umask-robust, no brief world-readable window). frps reads it as root.
    fd, tmp = tempfile.mkstemp(dir=FRP_CONFIG_DIR, prefix=".frps.toml.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            os.fchmod(f.fileno(), 0o600)
            f.write(toml.encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    logger.info("frps.toml geschrieben: %s", path)
    if warn_restart:
        logger.info("frps.toml changed at runtime (%s); frps applies the change by itself", path)
    return path


def remove_frps_config() -> None:
    """Removes frps.toml from FRP_CONFIG_DIR, best effort: the DB is the source of truth, so
    a failed removal is logged, never raised; the next server start removes a file that no
    DB config backs (_ensure_frps_config)."""
    path = FRP_CONFIG_DIR / "frps.toml"
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        logger.exception("could not remove frps.toml (%s)", path)
        return
    logger.info("frps.toml entfernt: %s", path)
