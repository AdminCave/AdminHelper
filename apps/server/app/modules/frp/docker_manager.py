# SPDX-FileCopyrightText: 2026 Kevin Stenzel
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Writes generated FRP configs into the shared volume for the frps container."""

import logging
import os
import stat
import tempfile
import time
from pathlib import Path

from app.core.config import FRP_CONFIG_DIR, fsync_dir
from app.modules.frp.config_generator import generate_frps_toml

logger = logging.getLogger(__name__)

_TEMP_PREFIX = ".frps.toml."
_TEMP_SUFFIX = ".tmp"
# Every uvicorn worker cleans up at its start: a younger temp file may be one another worker
# is writing right now.
STALE_TEMP_AGE = 60  # seconds


def write_frps_config(config, *, warn_restart: bool = False) -> Path:
    """Writes frps.toml into FRP_CONFIG_DIR. Returns the file path.

    The file is swapped in atomically (temp file in the same directory, fsync, os.replace,
    then an fsync of the directory so the swap survives a crash): frps watches it and picks a
    change up by itself, so it must never see an empty or half-written file. warn_restart=True
    marks a change made at runtime (create/update via the web UI) and logs that frps applies
    it; at startup frps boots straight from the fresh file, so nothing is logged about it.
    """
    toml = generate_frps_toml(config)
    path = FRP_CONFIG_DIR / "frps.toml"
    # frps.toml carries the global auth.token + dashboard password and lives in
    # the volume shared with the internet-facing frps container -> 0600
    # (umask-robust, no brief world-readable window). frps reads it as root.
    fd, tmp = tempfile.mkstemp(dir=FRP_CONFIG_DIR, prefix=_TEMP_PREFIX, suffix=_TEMP_SUFFIX)
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
    fsync_dir(FRP_CONFIG_DIR)
    logger.info("frps.toml geschrieben: %s", path)
    if warn_restart:
        logger.info("frps.toml changed at runtime (%s); frps applies the change by itself", path)
    return path


def remove_stale_temp_files() -> int:
    """Removes the temp files of write_frps_config older than STALE_TEMP_AGE from
    FRP_CONFIG_DIR; returns how many. A write killed between mkstemp and os.replace (SIGKILL,
    OOM) leaves its 0600 temp file, with the token of its time, in the volume shared with the
    frps container. Only regular files go, a symlink is neither followed nor removed. Best
    effort: an error is logged with its type, never raised."""
    try:
        names = os.listdir(FRP_CONFIG_DIR)
    except OSError as exc:
        logger.warning("frps temp files not cleaned up (%s)", type(exc).__name__)
        return 0
    now = time.time()
    removed = 0
    for name in names:
        if not (name.startswith(_TEMP_PREFIX) and name.endswith(_TEMP_SUFFIX)):
            continue
        path = FRP_CONFIG_DIR / name
        try:
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or now - info.st_mtime <= STALE_TEMP_AGE:
                continue
            path.unlink()
        except FileNotFoundError:
            continue  # another worker removed it first
        except OSError as exc:
            logger.warning("frps temp file %s not removed (%s)", name, type(exc).__name__)
            continue
        removed += 1
    logger.info("stale frps temp files removed: %d", removed)
    return removed


def remove_frps_config() -> None:
    """Removes frps.toml from FRP_CONFIG_DIR, best effort: the DB is the source of truth, so
    a failed removal is logged, never raised; the next server start removes a file that no
    DB config backs (_ensure_frps_config)."""
    path = FRP_CONFIG_DIR / "frps.toml"
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError as exc:
        logger.error("could not remove frps.toml (%s): %s", path, type(exc).__name__)
        return
    logger.info("frps.toml entfernt: %s", path)
